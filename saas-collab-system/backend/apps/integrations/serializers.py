from django.conf import settings
from rest_framework import serializers

from .models import (
    IntegrationAuditLog,
    MarketplaceProductMapping,
    MarketplaceStoreAuthorization,
    MarketplaceStoreMapping,
    PlatformChoices,
    PlatformIntegrationConfig,
    SyncJob,
    SyncRun,
)
from .platform_schema_service import get_platform_schema, validate_platform_config


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
        if platform in {PlatformChoices.SHOPEE, PlatformChoices.TIKTOK}:
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
        if platform in {PlatformChoices.SHOPEE, PlatformChoices.TIKTOK} and not callback_url:
            raise serializers.ValidationError({"callback_url": "Platform callback URL is required."})
        if callback_url and not str(callback_url).startswith("https://"):
            raise serializers.ValidationError({"callback_url": "Callback URL must use HTTPS."})
        redirect_allowlist = set(getattr(settings, "LIVE_OAUTH_REDIRECT_ALLOWLIST", []) or [])
        expected_callback = {
            PlatformChoices.SHOPEE: getattr(settings, "LIVE_SHOPEE_REDIRECT_URI", ""),
            PlatformChoices.TIKTOK: getattr(settings, "LIVE_TIKTOK_REDIRECT_URI", ""),
        }.get(platform, "")
        if expected_callback and callback_url != expected_callback:
            raise serializers.ValidationError({"callback_url": "Callback URL does not match the platform registration."})
        if callback_url and redirect_allowlist and callback_url not in redirect_allowlist:
            raise serializers.ValidationError({"callback_url": "Callback URL is not in the approved allowlist."})
        if (
            platform in {PlatformChoices.SHOPEE, PlatformChoices.TIKTOK}
            and environment in {
                PlatformIntegrationConfig.Environment.PILOT,
                PlatformIntegrationConfig.Environment.PRODUCTION,
            }
            and not redirect_allowlist
        ):
            raise serializers.ValidationError({"callback_url": "Live callback allowlist approval is not configured."})
        connect_timeout = attrs.get(
            "connect_timeout_seconds", getattr(self.instance, "connect_timeout_seconds", 3)
        )
        read_timeout = attrs.get("read_timeout_seconds", getattr(self.instance, "read_timeout_seconds", 8))
        if not 1 <= connect_timeout <= 10:
            raise serializers.ValidationError({"connect_timeout_seconds": "Connect timeout must be 1-10 seconds."})
        if not 1 <= read_timeout <= 30:
            raise serializers.ValidationError({"read_timeout_seconds": "Read timeout must be 1-30 seconds."})
        if attrs.get("network_enabled") and not (
            getattr(settings, "PLATFORM_NETWORK_MODE", "") == "approved-live-test"
            and getattr(settings, "LIVE_PLATFORM_SECURITY_APPROVED", False)
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


class RotateCredentialsSerializer(serializers.Serializer):
    credential_id = serializers.CharField(max_length=160)
    token_id = serializers.CharField(max_length=160)
    credential_reference_version = serializers.IntegerField(min_value=1)


class CredentialPayloadSerializer(serializers.Serializer):
    app_secret = serializers.CharField(max_length=4096, required=False, write_only=True, trim_whitespace=False)
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
        )
        read_only_fields = fields


class MarketplaceOAuthStartSerializer(serializers.Serializer):
    """OAuth start request; raw credential fields are rejected by the view."""

    platform = serializers.ChoiceField(choices=[PlatformChoices.SHOPEE, PlatformChoices.TIKTOK])
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

    class Meta:
        model = SyncJob
        fields = (
            "id",
            "tenant_id",
            "integration_config_id",
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

    def validate_max_retry_count(self, value):
        if value > 5:
            raise serializers.ValidationError("max_retry_count cannot exceed 5 in phase 2.")
        return value

    def validate_backoff_base_seconds(self, value):
        if not 1 <= value <= 5:
            raise serializers.ValidationError("backoff_base_seconds must be between 1 and 5 in phase 2.")
        return value


class SyncRunSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    sync_job_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = SyncRun
        fields = (
            "id",
            "tenant_id",
            "sync_job_id",
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
