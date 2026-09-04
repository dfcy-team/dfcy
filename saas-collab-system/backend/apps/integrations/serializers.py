from urllib.parse import urlsplit

from django.conf import settings
from rest_framework import serializers

from .models import (
    ConnectionCapability,
    IntegrationAuditLog,
    MarketplaceProductMapping,
    MarketplaceStoreAuthorization,
    MarketplaceStoreMapping,
    PlatformChoices,
    PlatformIntegrationConfig,
    SyncJob,
    SyncAlertIncident,
    SyncRun,
    WarehouseAuthorization,
)
from .audit_sanitizer import (
    _AUDIT_SENSITIVE_KEYS,
    is_sensitive_audit_key as _is_sensitive_audit_key,
    sanitize_audit_detail as _sanitize_audit_detail,
)
from .platform_schema_service import get_platform_schema, validate_platform_config
from .production_settings import get_runtime_platform_config, get_runtime_setting


PILOT_LOOPBACK_CALLBACKS = {
    PlatformChoices.LAZADA: "/api/internal/integrations/store-authorizations/oauth/callback/lazada/",
    PlatformChoices.SHOPEE: "/api/internal/integrations/store-authorizations/oauth/callback/shopee/",
    PlatformChoices.TIKTOK: "/api/internal/integrations/store-authorizations/oauth/callback/tiktok/",
}

def _is_approved_callback_transport(callback_url, environment, platform):
    try:
        parsed = urlsplit(str(callback_url))
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme == "https":
        return True
    return (
        environment == PlatformIntegrationConfig.Environment.PILOT
        and parsed.scheme == "http"
        and parsed.hostname == "127.0.0.1"
        and port == 8000
        and parsed.path == PILOT_LOOPBACK_CALLBACKS.get(platform)
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    )


def validate_marketplace_callback_url(callback_url, *, environment, platform):
    """Validate a callback URL against transport, registration and allowlist policy."""

    callback_url = serializers.URLField(max_length=500).run_validation(callback_url)
    if not _is_approved_callback_transport(callback_url, environment, platform):
        raise serializers.ValidationError(
            "Callback URL must use HTTPS; controlled Pilot testing may use only the exact "
            "http://127.0.0.1:8000 marketplace callback."
        )
    redirect_allowlist = set(get_runtime_setting("network", "oauth_redirect_allowlist", default=[]) or [])
    expected_callback = (get_runtime_platform_config(str(platform or "").lower()) or {}).get("redirect_uri", "")
    if expected_callback and callback_url != expected_callback:
        raise serializers.ValidationError("Callback URL does not match the platform registration.")
    if redirect_allowlist and callback_url not in redirect_allowlist:
        raise serializers.ValidationError("Callback URL is not in the approved allowlist.")
    if (
        environment
        in {
            PlatformIntegrationConfig.Environment.PILOT,
            PlatformIntegrationConfig.Environment.PRODUCTION,
        }
        and not redirect_allowlist
    ):
        raise serializers.ValidationError("Live callback allowlist approval is not configured.")
    return callback_url


class PlatformIntegrationConfigSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    created_by_id = serializers.IntegerField(source="created_by.id", read_only=True)

    class Meta:
        model = PlatformIntegrationConfig
        fields = (
            "id",
            "tenant_id",
            "platform",
            "account_alias",
            "environment",
            "status",
            "regions",
            "contract_version",
            "callback_url",
            "scopes",
            "platform_config",
            "connect_timeout_seconds",
            "read_timeout_seconds",
            "proxy_profile",
            "network_enabled",
            "sync_read_enabled",
            "sync_write_enabled",
            "config_version",
            "credential_key_version",
            "credential_fingerprint",
            "credential_mask",
            "credential_reference_version",
            "credential_status",
            "credential_expires_at",
            "credential_revoked_at",
            "credential_operation_id_hash",
            "last_rotated_at",
            "last_verified_at",
            "created_by_id",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "tenant_id",
            "credential_key_version",
            "credential_fingerprint",
            "credential_mask",
            "credential_reference_version",
            "credential_status",
            "config_version",
            "credential_expires_at",
            "credential_revoked_at",
            "credential_operation_id_hash",
            "last_rotated_at",
            "last_verified_at",
            "created_by_id",
            "created_at",
            "updated_at",
        )

    def validate_regions(self, value):
        regions = [str(region).strip().upper() for region in value]
        if not regions or len(regions) != len(set(regions)):
            raise serializers.ValidationError("Select one or more unique regions.")
        return regions

    def validate_scopes(self, value):
        scopes = [str(scope).strip() for scope in value if str(scope).strip()]
        if len(scopes) != len(set(scopes)):
            raise serializers.ValidationError("Scopes must be unique.")
        return scopes

    def validate(self, attrs):
        if {"credential_id", "token_id"}.intersection(self.initial_data):
            raise serializers.ValidationError(
                "Credential references must be changed through the rotate endpoint."
            )
        environment = attrs.get("environment", getattr(self.instance, "environment", None))
        platform = attrs.get("platform", getattr(self.instance, "platform", None))
        if self.instance and "platform" in attrs and attrs["platform"] != self.instance.platform:
            raise serializers.ValidationError({"platform": "Platform cannot be changed after creation."})
        if self.instance and "environment" in attrs and attrs["environment"] != self.instance.environment:
            raise serializers.ValidationError({"environment": "Environment changes require a new configuration."})
        marketplace_platforms = {PlatformChoices.LAZADA, PlatformChoices.SHOPEE, PlatformChoices.TIKTOK}
        if platform in marketplace_platforms:
            schema = get_platform_schema(platform, environment=environment)
            allowed_regions = {item["value"] for item in schema["regions"]}
            contract_version = attrs.get("contract_version", getattr(self.instance, "contract_version", ""))
            if contract_version not in schema["contract_versions"]:
                raise serializers.ValidationError({"contract_version": "Select an approved platform contract version."})
            regions = attrs.get("regions", getattr(self.instance, "regions", []))
            if not regions:
                raise serializers.ValidationError({"regions": "Select at least one approved platform region."})
            if not set(regions) <= allowed_regions:
                raise serializers.ValidationError({"regions": "Unsupported platform region."})
            scopes = attrs.get("scopes", getattr(self.instance, "scopes", []))
            allowed_scopes = {item["value"] for item in schema["scope_options"]}
            if scopes and not set(scopes) <= allowed_scopes:
                raise serializers.ValidationError({"scopes": "Unsupported or non-minimal scope."})
            if platform == PlatformChoices.TIKTOK and "seller.authorization.info" not in scopes:
                raise serializers.ValidationError({"scopes": "TikTok authorized-shop read scope is required."})
            platform_config = attrs.get("platform_config", getattr(self.instance, "platform_config", {}))
            attrs["platform_config"] = validate_platform_config(platform, platform_config)
        callback_url = attrs.get("callback_url", getattr(self.instance, "callback_url", ""))
        if platform in marketplace_platforms and not callback_url:
            raise serializers.ValidationError({"callback_url": "Platform callback URL is required."})
        if callback_url:
            try:
                if platform in marketplace_platforms:
                    attrs["callback_url"] = validate_marketplace_callback_url(
                        callback_url,
                        environment=environment,
                        platform=platform,
                    )
                elif not _is_approved_callback_transport(callback_url, environment, platform):
                    raise serializers.ValidationError(
                        "Callback URL must use HTTPS; controlled Pilot testing may use only the exact "
                        "http://127.0.0.1:8000 marketplace callback."
                    )
            except serializers.ValidationError as exc:
                raise serializers.ValidationError({"callback_url": exc.detail}) from exc
        connect_timeout = attrs.get(
            "connect_timeout_seconds", getattr(self.instance, "connect_timeout_seconds", 3)
        )
        read_timeout = attrs.get("read_timeout_seconds", getattr(self.instance, "read_timeout_seconds", 8))
        if not 1 <= connect_timeout <= 10:
            raise serializers.ValidationError({"connect_timeout_seconds": "Connect timeout must be 1-10 seconds."})
        if not 1 <= read_timeout <= 30:
            raise serializers.ValidationError({"read_timeout_seconds": "Read timeout must be 1-30 seconds."})
        if attrs.get("network_enabled") and not (
            get_runtime_setting("network", "mode", default="") == "approved-live-test"
            and get_runtime_setting("network", "security_approved", default=False)
        ):
            raise serializers.ValidationError({"network_enabled": "Live network approval is not active."})
        if attrs.get("sync_read_enabled") or attrs.get("sync_write_enabled"):
            raise serializers.ValidationError("Marketplace synchronization is outside this task and must remain disabled.")
        status = attrs.get("status", getattr(self.instance, "status", PlatformIntegrationConfig.Status.DISABLED))
        if (
            environment == PlatformIntegrationConfig.Environment.PRODUCTION
            and status == PlatformIntegrationConfig.Status.ACTIVE
        ):
            raise serializers.ValidationError(
                {"status": "Production configs can only be disabled or pending review in phase 2."}
            )
        return attrs


class ReadinessContractRepairSerializer(serializers.Serializer):
    """Validate the explicit confirmation used by the readiness contract action."""

    confirm = serializers.BooleanField(required=True)
    dry_run = serializers.BooleanField(required=False, default=False)
    expected_version = serializers.IntegerField(required=True, min_value=1)


class ReadonlyApprovalSerializer(serializers.Serializer):
    """Validate the small, non-secret production-readonly state transition."""

    approved = serializers.BooleanField(required=True)
    confirm = serializers.BooleanField(required=True)
    expected_version = serializers.IntegerField(required=True, min_value=1)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=240, trim_whitespace=True)


class RotateCredentialsSerializer(serializers.Serializer):
    credential_id = serializers.CharField(max_length=160)
    token_id = serializers.CharField(max_length=160)
    credential_reference_version = serializers.IntegerField(min_value=1)


class CredentialPayloadSerializer(serializers.Serializer):
    partner_id = serializers.CharField(max_length=32, required=False, write_only=True)
    partner_key = serializers.CharField(max_length=4096, required=False, write_only=True, trim_whitespace=False)
    ads_app_id = serializers.CharField(max_length=255, required=False, write_only=True)
    ads_secret = serializers.CharField(max_length=4096, required=False, write_only=True, trim_whitespace=False)
    redirect_uri = serializers.URLField(max_length=500, required=False, write_only=True)
    app_key = serializers.CharField(max_length=255, required=False, write_only=True)
    service_id = serializers.CharField(max_length=255, required=False, write_only=True)
    api_secret = serializers.CharField(max_length=4096, required=False, write_only=True, trim_whitespace=False)
    app_secret = serializers.CharField(max_length=4096, required=False, write_only=True, trim_whitespace=False)
    api_base_url = serializers.URLField(max_length=500, required=False, write_only=True)
    domain = serializers.CharField(max_length=255, required=False, write_only=True)
    client_id = serializers.CharField(max_length=255, required=False, write_only=True)
    client_secret = serializers.CharField(max_length=4096, required=False, write_only=True, trim_whitespace=False)
    signing_secret = serializers.CharField(max_length=4096, required=False, write_only=True, trim_whitespace=False)
    webhook_secret = serializers.CharField(max_length=4096, required=False, write_only=True, trim_whitespace=False)
    access_token = serializers.CharField(max_length=8192, required=False, write_only=True, trim_whitespace=False)
    refresh_token = serializers.CharField(max_length=8192, required=False, write_only=True, trim_whitespace=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Provide at least one credential value.")
        if any(not value for value in attrs.values()):
            raise serializers.ValidationError("Credential values cannot be blank.")
        if any(value == "********" for value in attrs.values()):
            raise serializers.ValidationError("The fixed credential mask is not a credential value.")
        return attrs


class CredentialRotateWriteSerializer(serializers.Serializer):
    version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(min_length=5, max_length=240, write_only=True)
    credentials = CredentialPayloadSerializer(write_only=True)
    verify_after_save = serializers.BooleanField(default=False, write_only=True)

    def validate_verify_after_save(self, value):
        if value:
            raise serializers.ValidationError("Connection verification must use the separate verify action.")
        return value


class CredentialClearSerializer(serializers.Serializer):
    version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(min_length=5, max_length=240, write_only=True)


class MarketplaceStoreAuthorizationSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(read_only=True)
    integration_config_id = serializers.IntegerField(read_only=True)
    store_id = serializers.IntegerField(read_only=True)
    store_code = serializers.CharField(source="store.code", read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)
    created_by_id = serializers.IntegerField(read_only=True)
    updated_by_id = serializers.IntegerField(read_only=True)
    capabilities_summary = serializers.SerializerMethodField()

    class Meta:
        model = MarketplaceStoreAuthorization
        fields = (
            "id",
            "tenant_id",
            "integration_config_id",
            "store_id",
            "store_code",
            "store_name",
            "platform",
            "region",
            "platform_store_id",
            "credential_mask",
            "credential_reference_version",
            "status",
            "scopes",
            "authorized_at",
            "expires_at",
            "refreshed_at",
            "revoked_at",
            "last_error_code",
            "created_by_id",
            "updated_by_id",
            "created_at",
            "updated_at",
            "capabilities_summary",
        )
        read_only_fields = fields

    def get_capabilities_summary(self, obj):
        items = list(obj.connection_capabilities.all())
        latest_success = max((item.last_success_at for item in items if item.last_success_at), default=None)
        return {
            "total": len(items),
            "active": sum(item.status == ConnectionCapability.Status.ACTIVE for item in items),
            "read_enabled": sum(item.read_enabled for item in items),
            "write_enabled": sum(item.write_enabled for item in items),
            "last_success_at": latest_success,
        }


class WarehouseAuthorizationSerializer(serializers.ModelSerializer):
    """Expose only masked warehouse binding metadata, never custody references."""

    tenant_id = serializers.IntegerField(read_only=True)
    integration_config_id = serializers.IntegerField(read_only=True)
    warehouse_id = serializers.IntegerField(read_only=True)
    warehouse_code = serializers.CharField(source="warehouse.code", read_only=True)
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    country_code = serializers.CharField(source="warehouse.country_code", read_only=True)
    created_by_id = serializers.IntegerField(read_only=True)
    updated_by_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = WarehouseAuthorization
        fields = (
            "id",
            "tenant_id",
            "integration_config_id",
            "warehouse_id",
            "warehouse_code",
            "warehouse_name",
            "country_code",
            "provider",
            "status",
            "authorized_at",
            "last_verified_at",
            "revoked_at",
            "last_error_code",
            "created_by_id",
            "updated_by_id",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class WarehouseAuthorizationBindSerializer(serializers.Serializer):
    """Request contract for binding a managed config to a warehouse."""

    warehouse_id = serializers.IntegerField(min_value=1)
    integration_config_id = serializers.IntegerField(min_value=1)
    replace = serializers.BooleanField(default=False)
    expected_authorization_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    idempotency_key = serializers.CharField(min_length=8, max_length=120, required=False, allow_blank=True)


class ConnectionCapabilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = ConnectionCapability
        fields = (
            "id", "authorization_id", "capability_code", "read_enabled", "write_enabled",
            "sync_mode", "sync_cursor", "last_success_at", "last_failure_at",
            "source_priority", "status", "created_at", "updated_at",
        )
        read_only_fields = fields


class ConnectionCapabilityWriteSerializer(serializers.Serializer):
    capability_code = serializers.ChoiceField(choices=ConnectionCapability.CapabilityCode.choices)
    read_enabled = serializers.BooleanField(default=False)
    write_enabled = serializers.BooleanField(default=False)
    sync_mode = serializers.ChoiceField(
        choices=ConnectionCapability.SyncMode.choices, default=ConnectionCapability.SyncMode.MANUAL
    )
    source_priority = serializers.IntegerField(min_value=1, max_value=65535, default=100)
    status = serializers.ChoiceField(
        choices=ConnectionCapability.Status.choices, default=ConnectionCapability.Status.DISABLED
    )

    def validate_write_enabled(self, value):
        if value:
            raise serializers.ValidationError("Live write capabilities are disabled in this phase.")
        return value

class MarketplaceOAuthStartSerializer(serializers.Serializer):
    """OAuth start request; raw credential fields are rejected by the view."""

    platform = serializers.ChoiceField(
        choices=[PlatformChoices.LAZADA, PlatformChoices.SHOPEE, PlatformChoices.TIKTOK]
    )
    integration_config_id = serializers.IntegerField(min_value=1)
    store_id = serializers.IntegerField(min_value=1)
    region = serializers.CharField(max_length=8)
    redirect_uri = serializers.CharField(max_length=500)
    scopes = serializers.ListField(child=serializers.CharField(max_length=64), required=False, default=list)

    def validate_region(self, value):
        region = str(value or "").strip().upper()
        if not region or len(region) > 8 or not all(ch.isalnum() or ch == "-" for ch in region):
            raise serializers.ValidationError("region must be a short alphanumeric region code.")
        return region

    def validate_redirect_uri(self, value):
        redirect_uri = str(value or "").strip()
        if not redirect_uri.startswith("https://"):
            raise serializers.ValidationError("OAuth redirect URI must be an https URL.")
        return redirect_uri

    def validate_scopes(self, value):
        scopes = [str(scope).strip() for scope in value if str(scope).strip()]
        if len(set(scopes)) != len(scopes):
            raise serializers.ValidationError("OAuth scopes must be unique.")
        if len(scopes) > 20:
            raise serializers.ValidationError("Too many OAuth scopes requested.")
        return scopes


class MarketplaceStoreMappingSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(read_only=True)
    store_code = serializers.CharField(source="store.code", read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)
    authorization_id = serializers.IntegerField(read_only=True)
    mapped_by_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = MarketplaceStoreMapping
        fields = (
            "id",
            "tenant_id",
            "platform",
            "store_id",
            "store_code",
            "store_name",
            "authorization_id",
            "platform_store_id",
            "region",
            "timezone",
            "currency",
            "status",
            "mapping_source",
            "mapped_by_id",
            "mapped_at",
            "last_verified_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class StoreMappingCreateSerializer(serializers.Serializer):
    store_id = serializers.IntegerField(min_value=1)
    authorization_id = serializers.IntegerField(min_value=1)
    timezone = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    currency = serializers.CharField(max_length=3, required=False, allow_blank=True, default="")

    def validate_currency(self, value):
        currency = str(value or "").strip().upper()
        if currency and (len(currency) != 3 or not currency.isalpha()):
            raise serializers.ValidationError("Currency must be an uppercase ISO 4217 code.")
        return currency

    def validate(self, attrs):
        forbidden = {"tenant", "tenant_id", "mapped_by", "mapped_by_id", "platform_store_id", "platform_identity_key"}
        provided = forbidden.intersection({str(key).lower() for key in self.initial_data})
        if provided:
            raise serializers.ValidationError("Tenant, operator and platform identity fields are not accepted.")
        return attrs


class StoreMappingUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=MarketplaceStoreMapping.Status.choices, required=False)
    timezone = serializers.CharField(max_length=64, required=False, allow_blank=True)
    currency = serializers.CharField(max_length=3, required=False, allow_blank=True)

    def validate_currency(self, value):
        currency = str(value or "").strip().upper()
        if currency and (len(currency) != 3 or not currency.isalpha()):
            raise serializers.ValidationError("Currency must be an uppercase ISO 4217 code.")
        return currency


class MarketplaceProductMappingSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(read_only=True)
    store_mapping_id = serializers.IntegerField(read_only=True)
    product_id = serializers.IntegerField(read_only=True)
    sku_id = serializers.IntegerField(read_only=True)
    sku_code = serializers.CharField(source="sku.sku_code", read_only=True, default=None)

    class Meta:
        model = MarketplaceProductMapping
        fields = (
            "id",
            "tenant_id",
            "platform",
            "store_mapping_id",
            "platform_product_id",
            "platform_variant_id",
            "platform_sku",
            "product_id",
            "sku_id",
            "sku_code",
            "status",
            "mapping_source",
            "confidence",
            "manually_confirmed",
            "result_code",
            "first_seen_at",
            "last_verified_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class ProductMappingCreateSerializer(serializers.Serializer):
    store_mapping_id = serializers.IntegerField(min_value=1)
    platform_product_id = serializers.CharField(max_length=160)
    platform_variant_id = serializers.CharField(max_length=160)
    platform_sku = serializers.CharField(max_length=160, required=False, allow_blank=True, default="")

    def validate(self, attrs):
        forbidden = {
            "tenant",
            "tenant_id",
            "created_by",
            "updated_by",
            "status",
            "sku_id",
            "product_id",
            "manually_confirmed",
            "confidence",
        }
        provided = forbidden.intersection({str(key).lower() for key in self.initial_data})
        if provided:
            raise serializers.ValidationError("Status, identity and confirmation fields are not accepted on create.")
        return attrs


class ProductMappingUpdateSerializer(serializers.Serializer):
    sku_id = serializers.IntegerField(min_value=1, required=False)
    confidence = serializers.IntegerField(min_value=0, max_value=100, required=False)
    manually_confirmed = serializers.BooleanField(required=False, default=False)
    status = serializers.ChoiceField(choices=[MarketplaceProductMapping.Status.INACTIVE], required=False)


class IntegrationAuditLogSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(read_only=True)
    integration_config_id = serializers.IntegerField(read_only=True)
    platform = serializers.CharField(source="integration_config.platform", read_only=True)
    environment = serializers.CharField(source="integration_config.environment", read_only=True)
    masked_detail = serializers.SerializerMethodField()

    def get_masked_detail(self, obj):
        return _sanitize_audit_detail(obj.masked_detail)

    class Meta:
        model = IntegrationAuditLog
        fields = (
            "id",
            "tenant_id",
            "integration_config_id",
            "platform",
            "environment",
            "action",
            "actor_id",
            "result",
            "masked_detail",
            "created_at",
        )
        read_only_fields = fields


class SyncJobSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    integration_config_id = serializers.IntegerField()
    store_authorization_id = serializers.IntegerField(required=False, allow_null=True)
    warehouse_authorization_id = serializers.IntegerField(required=False, allow_null=True)
    platform = serializers.CharField(source="integration_config.platform", read_only=True)
    config_alias = serializers.CharField(source="integration_config.account_alias", read_only=True)
    environment = serializers.CharField(source="integration_config.environment", read_only=True)
    regions = serializers.JSONField(source="integration_config.regions", read_only=True)

    class Meta:
        model = SyncJob
        fields = (
            "id",
            "tenant_id",
            "integration_config_id",
            "store_authorization_id",
            "warehouse_authorization_id",
            "platform",
            "config_alias",
            "environment",
            "regions",
            "resource_type",
            "schedule_type",
            "status",
            "is_enabled",
            "max_retry_count",
            "backoff_base_seconds",
            "last_run_at",
            "next_run_at",
            "lock_expires_at",
            "lock_heartbeat_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "tenant_id",
            "status",
            "last_run_at",
            "next_run_at",
            "lock_expires_at",
            "lock_heartbeat_at",
            "created_at",
            "updated_at",
        )

    def validate_integration_config_id(self, value):
        request = self.context["request"]
        if not PlatformIntegrationConfig.objects.filter(id=value, tenant=request.user.tenant).exists():
            raise serializers.ValidationError("Integration config does not belong to current tenant.")
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        request = self.context["request"]
        config_id = attrs.get("integration_config_id") or getattr(self.instance, "integration_config_id", None)
        resource_type = attrs.get("resource_type") or getattr(self.instance, "resource_type", None)
        if not config_id or not resource_type:
            return attrs
        config = PlatformIntegrationConfig.objects.get(id=config_id, tenant=request.user.tenant)
        store_authorization_id = attrs.get(
            "store_authorization_id", getattr(self.instance, "store_authorization_id", None)
        )
        warehouse_authorization_id = attrs.get(
            "warehouse_authorization_id", getattr(self.instance, "warehouse_authorization_id", None)
        )
        if store_authorization_id is not None and warehouse_authorization_id is not None:
            raise serializers.ValidationError("A sync job can bind either a store or warehouse authorization, not both.")
        if (
            config.environment
            in {
                PlatformIntegrationConfig.Environment.PILOT,
                PlatformIntegrationConfig.Environment.PRODUCTION,
            }
            and store_authorization_id is None
            and warehouse_authorization_id is None
        ):
            raise serializers.ValidationError(
                "Production readonly sync jobs must bind one concrete store or warehouse authorization."
            )
        if store_authorization_id is not None:
            authorization = MarketplaceStoreAuthorization.objects.filter(
                id=store_authorization_id,
                tenant=request.user.tenant,
                integration_config_id=config_id,
            ).first()
            if authorization is None:
                raise serializers.ValidationError(
                    {"store_authorization_id": "Store authorization must belong to the current tenant and configuration."}
                )
            if authorization.status != MarketplaceStoreAuthorization.Status.ACTIVE:
                raise serializers.ValidationError(
                    {"store_authorization_id": "Only an active store authorization can create a sync job."}
                )
            if self.instance is None and SyncJob.objects.filter(
                tenant=request.user.tenant,
                store_authorization_id=store_authorization_id,
                resource_type=resource_type,
            ).exists():
                raise serializers.ValidationError(
                    {"resource_type": "This store authorization already has a sync job for the selected resource."}
                )
        if warehouse_authorization_id is not None:
            warehouse_authorization = WarehouseAuthorization.objects.filter(
                id=warehouse_authorization_id,
                tenant=request.user.tenant,
                integration_config_id=config_id,
            ).first()
            if warehouse_authorization is None:
                raise serializers.ValidationError(
                    {"warehouse_authorization_id": "Warehouse authorization must belong to the current tenant and configuration."}
                )
            if warehouse_authorization.status != WarehouseAuthorization.Status.ACTIVE:
                raise serializers.ValidationError(
                    {"warehouse_authorization_id": "Only an active warehouse authorization can create a sync job."}
                )
        if config.environment not in {
            PlatformIntegrationConfig.Environment.PILOT,
            PlatformIntegrationConfig.Environment.PRODUCTION,
        }:
            return attrs
        supported = {
            PlatformChoices.SHOPEE: {SyncJob.ResourceType.SALES_ORDER, SyncJob.ResourceType.REFUND_RETURN},
            PlatformChoices.TIKTOK: {SyncJob.ResourceType.SALES_ORDER, SyncJob.ResourceType.REFUND_RETURN},
            PlatformChoices.JIFENG_WMS: {SyncJob.ResourceType.INVENTORY_SNAPSHOT},
        }
        if resource_type not in supported.get(config.platform, set()):
            raise serializers.ValidationError("Platform and readonly resource type are incompatible.")
        if config.sync_write_enabled:
            raise serializers.ValidationError("Readonly production jobs reject write-enabled integration configs.")
        return attrs

    def validate_max_retry_count(self, value):
        if value > 5:
            raise serializers.ValidationError("max_retry_count cannot exceed 5.")
        return value

    def validate_backoff_base_seconds(self, value):
        if not 1 <= value <= 5:
            raise serializers.ValidationError("backoff_base_seconds must be between 1 and 5.")
        return value


class SyncAlertIncidentSerializer(serializers.ModelSerializer):
    sync_job_id = serializers.IntegerField(read_only=True)
    platform = serializers.CharField(source="sync_job.integration_config.platform", read_only=True)
    resource_type = serializers.CharField(source="sync_job.resource_type", read_only=True)
    account_alias = serializers.CharField(source="sync_job.integration_config.account_alias", read_only=True)
    assignee_name = serializers.CharField(source="assignee.username", read_only=True, allow_null=True)
    acknowledged_by_name = serializers.CharField(source="acknowledged_by.username", read_only=True, allow_null=True)
    resolved_by_name = serializers.CharField(source="resolved_by.username", read_only=True, allow_null=True)
    last_sync_run_id = serializers.IntegerField(read_only=True)
    last_run_id = serializers.CharField(source="last_sync_run.run_id", read_only=True, allow_null=True)

    class Meta:
        model = SyncAlertIncident
        fields = (
            "id", "sync_job_id", "platform", "resource_type", "account_alias",
            "status", "assignee", "assignee_name", "acknowledged_by",
            "acknowledged_by_name", "acknowledged_at", "resolved_by",
            "resolved_by_name", "resolved_at", "occurrence_count",
            "last_sync_run_id", "last_run_id", "last_error_code", "masked_message",
            "resolution_note", "created_at", "updated_at",
        )
        read_only_fields = fields


class SyncRunSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    sync_job_id = serializers.IntegerField(read_only=True)
    platform = serializers.CharField(source="sync_job.integration_config.platform", read_only=True)
    config_alias = serializers.CharField(source="sync_job.integration_config.account_alias", read_only=True)
    resource_type = serializers.CharField(source="sync_job.resource_type", read_only=True)

    class Meta:
        model = SyncRun
        fields = (
            "id",
            "tenant_id",
            "sync_job_id",
            "platform",
            "config_alias",
            "resource_type",
            "run_id",
            "idempotency_key",
            "status",
            "started_at",
            "finished_at",
            "fetched_count",
            "created_count",
            "updated_count",
            "skipped_count",
            "failed_count",
            "retry_count",
            "error_code",
            "masked_error_message",
            "masked_log",
        )
        read_only_fields = fields
