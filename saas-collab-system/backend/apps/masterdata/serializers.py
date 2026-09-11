from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from apps.accounts.models import CustomUser
from apps.products.models import ProductCategory

from .models import (
    CountrySiteMaster, PlatformMaster, PlatformSiteMaster, StatusChoices, StoreMaster,
    SupplierMaster, WarehouseMaster, WAREHOUSE_SERVICE_PLATFORM_TYPES, WAREHOUSE_TYPE_TO_PLATFORM_TYPE,
)
from .platform_catalog import normalize_platform_code, platform_catalog_item, resolve_platform_connector


def mask_email(value):
    if not value or "@" not in value:
        return ""
    local, domain = value.split("@", 1)
    return f"{local[:1]}***@{domain}"


def mask_phone(value):
    return f"***{value[-4:]}" if value else ""


class TenantOwnedSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)

    def validate(self, attrs):
        request = self.context["request"]
        code = attrs.get("code", getattr(self.instance, "code", None))
        if code and self.Meta.model.objects.filter(tenant=request.user.tenant, code=code).exclude(
            pk=getattr(self.instance, "pk", None)
        ).exists():
            raise serializers.ValidationError({"code": "Code must be unique within the current tenant."})
        return attrs


class PlatformMasterSerializer(TenantOwnedSerializer):
    platform_type = serializers.CharField()
    canonical_code = serializers.SerializerMethodField()
    platform_category = serializers.SerializerMethodField()
    priority_level = serializers.SerializerMethodField()
    default_integration_mode = serializers.SerializerMethodField()
    connector_key = serializers.SerializerMethodField()
    connector_name = serializers.SerializerMethodField()
    connector_status = serializers.SerializerMethodField()
    connector_hint = serializers.SerializerMethodField()

    class Meta:
        model = PlatformMaster
        fields = (
            "id", "tenant_id", "code", "name", "platform_type", "canonical_code",
            "platform_category", "priority_level", "default_integration_mode",
            "connector_key", "connector_name", "connector_status", "connector_hint",
            "status", "created_at", "updated_at",
        )
        read_only_fields = ("id", "tenant_id", "created_at", "updated_at")

    def _catalog_value(self, obj, key):
        item = platform_catalog_item(obj.platform_type)
        return item.get(key, "") if item else ""

    def _connector_resolution(self, obj):
        cached = getattr(obj, "_platform_connector_resolution", None)
        if cached is None:
            cached = resolve_platform_connector(
                platform_type=getattr(obj, "platform_type", ""),
                code=getattr(obj, "code", ""),
                name=getattr(obj, "name", ""),
            )
            try:
                obj._platform_connector_resolution = cached
            except (AttributeError, TypeError):
                pass
        return cached

    def validate_platform_type(self, value):
        normalized = normalize_platform_code(value)
        if not normalized:
            raise serializers.ValidationError("Unknown platform type.")
        return normalized

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if self.instance and "platform_type" in attrs:
            previous_type = str(self.instance.platform_type or "").strip().lower()
            next_type = str(attrs["platform_type"] or "").strip().lower()
            if previous_type != next_type:
                stores = self.instance.stores
                if stores.exclude(external_store_id="").exists() or stores.filter(
                    marketplace_authorizations__status="active"
                ).exists():
                    raise serializers.ValidationError(
                        {"platform_type": "已有店铺外部身份或有效平台授权绑定该平台，不能直接修改平台类型。"}
                    )
        return attrs

    def get_canonical_code(self, obj):
        return self._catalog_value(obj, "canonical_code")

    def get_platform_category(self, obj):
        return self._catalog_value(obj, "platform_category")

    def get_priority_level(self, obj):
        return self._catalog_value(obj, "priority_level")

    def get_default_integration_mode(self, obj):
        return self._catalog_value(obj, "default_integration_mode")

    def get_connector_key(self, obj):
        return self._connector_resolution(obj)["connector_key"]

    def get_connector_name(self, obj):
        return self._connector_resolution(obj)["connector_name"]

    def get_connector_status(self, obj):
        return self._connector_resolution(obj)["connector_status"]

    def get_connector_hint(self, obj):
        return self._connector_resolution(obj)["connector_hint"]


class PlatformSiteMasterSerializer(TenantOwnedSerializer):
    platform_id = serializers.IntegerField()
    platform_name = serializers.CharField(source="platform.name", read_only=True)

    class Meta:
        model = PlatformSiteMaster
        fields = (
            "id", "tenant_id", "platform_id", "platform_name", "site_code", "name",
            "country_code", "region_code", "currency_code", "timezone", "language_codes",
            "api_region", "api_base_url", "status", "created_at", "updated_at",
        )
        read_only_fields = ("id", "tenant_id", "platform_name", "created_at", "updated_at")

    def validate_platform_id(self, value):
        request = self.context["request"]
        if not PlatformMaster.objects.filter(tenant=request.user.tenant, pk=value).exists():
            raise serializers.ValidationError("Platform must belong to the current tenant.")
        return value

    def validate_country_code(self, value):
        value = str(value or "").strip().upper()
        if not value:
            raise serializers.ValidationError("Country code is required.")
        return value

    def validate_currency_code(self, value):
        return str(value or "").strip().upper()

    def validate_language_codes(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Language codes must be a list.")
        return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))

    def validate(self, attrs):
        attrs = super().validate(attrs)
        tenant = self.context["request"].user.tenant
        platform_id = attrs.get("platform_id", getattr(self.instance, "platform_id", None))
        site_code = attrs.get("site_code", getattr(self.instance, "site_code", None))
        if platform_id and site_code and PlatformSiteMaster.objects.filter(
            tenant=tenant, platform_id=platform_id, site_code=site_code
        ).exclude(pk=getattr(self.instance, "pk", None)).exists():
            raise serializers.ValidationError({"site_code": "Site code must be unique within the selected platform."})
        return attrs


class StoreMasterSerializer(TenantOwnedSerializer):
    platform_id = serializers.IntegerField()
    external_store_id = serializers.CharField(required=False, allow_blank=True, max_length=160)
    country_code = serializers.CharField(max_length=8)
    platform_name = serializers.CharField(source="platform.name", read_only=True)
    platform_site_id = serializers.IntegerField(required=False, allow_null=True)
    platform_site_name = serializers.CharField(source="platform_site.name", read_only=True, allow_null=True)
    fulfillment_modes = serializers.ListField(
        child=serializers.CharField(max_length=40), required=False, allow_empty=True,
    )
    category_id = serializers.PrimaryKeyRelatedField(
        source="category", queryset=ProductCategory.objects.none(), required=False, allow_null=True
    )
    category_name = serializers.CharField(source="category.name", read_only=True, allow_null=True)
    operator_id = serializers.PrimaryKeyRelatedField(
        source="operator", queryset=CustomUser.objects.none(), required=False, allow_null=True
    )
    operator_name = serializers.SerializerMethodField()
    bd_id = serializers.PrimaryKeyRelatedField(
        source="bd", queryset=CustomUser.objects.none(), required=False, allow_null=True
    )
    bd_name = serializers.SerializerMethodField()
    leader_id = serializers.PrimaryKeyRelatedField(
        source="leader", queryset=CustomUser.objects.none(), required=False, allow_null=True
    )
    leader_name = serializers.SerializerMethodField()

    class Meta:
        model = StoreMaster
        fields = (
            "id", "tenant_id", "platform_id", "platform_name", "platform_site_id", "platform_site_name",
            "code", "name", "external_store_id", "seller_entity_id", "business_model",
            "fulfillment_modes", "settlement_currency", "platform_store_name",
            "category_id", "category_name", "operator_id", "operator_name", "bd_id", "bd_name",
            "leader_id", "leader_name", "is_connected", "tactical_client", "country_code", "currency",
            "timezone", "status", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "tenant_id", "platform_name", "platform_site_name", "category_name", "operator_name", "bd_name", "leader_name",
            "created_at", "updated_at",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        tenant_id = getattr(getattr(request, "user", None), "tenant_id", None)
        if tenant_id:
            self.fields["category_id"].queryset = ProductCategory.objects.filter(tenant_id=tenant_id, is_active=True)
            self.fields["operator_id"].queryset = CustomUser.objects.filter(tenant_id=tenant_id, is_active=True)
            self.fields["bd_id"].queryset = CustomUser.objects.filter(tenant_id=tenant_id, is_active=True)
            self.fields["leader_id"].queryset = CustomUser.objects.filter(tenant_id=tenant_id, is_active=True)

    def _user_name(self, user):
        return (getattr(user, "full_name", "") or getattr(user, "username", "")) if user else ""

    def get_operator_name(self, obj):
        return self._user_name(obj.operator)

    def get_bd_name(self, obj):
        return self._user_name(obj.bd)

    def get_leader_name(self, obj):
        return self._user_name(obj.leader)

    def _tenant_reference(self, value, model, label, *, active=False):
        if value is None:
            return None
        request = self.context["request"]
        if value.tenant_id != request.user.tenant_id or (active and not value.is_active):
            raise serializers.ValidationError(f"{label} must belong to the current active tenant.")
        return value

    def validate_category_id(self, value):
        return self._tenant_reference(value, ProductCategory, "Category", active=True)

    def validate_operator_id(self, value):
        return self._tenant_reference(value, CustomUser, "Operator", active=True)

    def validate_bd_id(self, value):
        return self._tenant_reference(value, CustomUser, "BD", active=True)

    def validate_leader_id(self, value):
        return self._tenant_reference(value, CustomUser, "Leader", active=True)

    def validate_platform_id(self, value):
        request = self.context["request"]
        from apps.permissions.ui_p2_scopes import filter_master_data

        queryset = PlatformMaster.objects.filter(pk=value, tenant=request.user.tenant)
        queryset = filter_master_data(request.user, queryset, "masterdata.manage", "platforms")
        if not queryset.exists():
            raise serializers.ValidationError("Platform is outside the current tenant or permitted data scope.")
        return value

    def validate_platform_site_id(self, value):
        if value is None:
            return None
        request = self.context["request"]
        if not PlatformSiteMaster.objects.filter(tenant=request.user.tenant, pk=value).exists():
            raise serializers.ValidationError("Platform site must belong to the current tenant.")
        return value

    def validate_fulfillment_modes(self, value):
        if any(item not in StoreMaster.FULFILLMENT_MODES for item in value):
            raise serializers.ValidationError("Unsupported fulfillment mode.")
        return list(dict.fromkeys(value))

    def validate_settlement_currency(self, value):
        return str(value or "").strip().upper()

    def validate_external_store_id(self, value):
        # The platform OAuth identity is whitespace-insensitive.  Keep the
        # persisted value canonical so the database constraint and the
        # authorization identity key use the same value.
        return str(value or "").strip()

    def validate_country_code(self, value):
        value = str(value or "").strip().upper()
        if not value:
            raise serializers.ValidationError("店铺国家/站点代码不能为空。")
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        tenant = self.context["request"].user.tenant
        platform_id = attrs.get("platform_id", getattr(self.instance, "platform_id", None))
        platform_type = PlatformMaster.objects.filter(
            tenant=tenant,
            pk=platform_id,
        ).values_list("platform_type", flat=True).first()
        country_code = str(attrs.get("country_code", getattr(self.instance, "country_code", "")) or "").strip().upper()
        external_store_id = str(
            attrs.get("external_store_id", getattr(self.instance, "external_store_id", "")) or ""
        ).strip()
        if external_store_id and platform_id:
            candidates = StoreMaster.objects.filter(
                tenant=tenant,
                platform__platform_type=platform_type,
            ).exclude(pk=getattr(self.instance, "pk", None))
            if any(
                str(item.external_store_id or "").strip() == external_store_id
                and str(item.country_code or "").strip().upper() == country_code
                for item in candidates.only("external_store_id", "country_code")
            ):
                raise serializers.ValidationError(
                    {"external_store_id": "该平台和站点的外部店铺 ID 已绑定其他店铺档案，请复用原档案或先处理重复数据。"}
                )
        site_id = attrs.get("platform_site_id", getattr(self.instance, "platform_site_id", None))
        if site_id:
            site = PlatformSiteMaster.objects.filter(tenant=self.context["request"].user.tenant, pk=site_id).first()
            if site and site.platform_id != platform_id:
                raise serializers.ValidationError({"platform_site_id": "Platform site must belong to the selected platform."})
        category = attrs.get("category")
        if category and category.level != ProductCategory.Level.L1:
            raise serializers.ValidationError({"category_id": "Store category must be a top-level category."})
        return attrs


class CountrySiteMasterSerializer(TenantOwnedSerializer):
    class Meta:
        model = CountrySiteMaster
        fields = (
            "id", "tenant_id", "code", "name", "country_code", "currency", "timezone", "platform", "status",
            "created_at", "updated_at",
        )
        read_only_fields = ("id", "tenant_id", "created_at", "updated_at")

    def validate_country_code(self, value):
        value = str(value or "").strip().upper()
        if not value:
            raise serializers.ValidationError("Country code is required.")
        return value

    def validate_platform(self, value):
        value = str(value or "").strip().lower()
        return value or None

    def validate_currency(self, value):
        return str(value or "").strip().upper()

    def validate_timezone(self, value):
        value = str(value or "").strip()
        return value or "UTC"


class WarehouseMasterSerializer(TenantOwnedSerializer):
    api_integration_config_id = serializers.IntegerField(required=False, min_value=1, write_only=True)
    api_email = serializers.EmailField(required=False, write_only=True)
    api_token = serializers.CharField(required=False, write_only=True, allow_blank=True, max_length=4096, trim_whitespace=False)
    api_external_warehouse_code = serializers.CharField(required=False, write_only=True, allow_blank=True, max_length=160)
    service_platform_id = serializers.PrimaryKeyRelatedField(
        source="service_platform",
        queryset=PlatformMaster.objects.none(),
        required=False,
        allow_null=True,
    )
    service_platform_name = serializers.CharField(source="service_platform.name", read_only=True, allow_null=True)
    service_platform_type = serializers.CharField(source="service_platform.platform_type", read_only=True, allow_null=True)
    service_platform_integration_key = serializers.SerializerMethodField()
    api_access_available = serializers.SerializerMethodField()
    api_connected = serializers.SerializerMethodField()
    site_code = serializers.SerializerMethodField()
    last_sync_at = serializers.SerializerMethodField()
    last_sync_status = serializers.SerializerMethodField()

    class Meta:
        model = WarehouseMaster
        fields = (
            "id", "tenant_id", "code", "name", "country_code", "warehouse_type", "status", "created_at", "updated_at",
            "service_platform_id", "service_platform_name", "service_platform_type", "service_platform_integration_key",
            "api_access_available", "api_connected", "site_code", "last_sync_at", "last_sync_status",
            "api_integration_config_id", "api_email", "api_token", "api_external_warehouse_code",
        )
        read_only_fields = (
            "id", "tenant_id", "created_at", "updated_at", "api_connected", "site_code", "last_sync_at", "last_sync_status",
            "service_platform_name", "service_platform_type", "service_platform_integration_key", "api_access_available",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        tenant_id = getattr(getattr(request, "user", None), "tenant_id", None)
        if tenant_id:
            self.fields["service_platform_id"].queryset = PlatformMaster.objects.filter(
                tenant_id=tenant_id,
                status=StatusChoices.ACTIVE,
                platform_type__in=WAREHOUSE_SERVICE_PLATFORM_TYPES,
            )

    def _service_platform_key(self, obj):
        if not obj or not obj.service_platform:
            return ""
        from apps.integrations.platform_schema_service import integration_platform_key

        return integration_platform_key(
            platform_type=obj.service_platform.platform_type,
            code=obj.service_platform.code,
            name=obj.service_platform.name,
        )

    def get_service_platform_integration_key(self, obj):
        return self._service_platform_key(obj)

    def get_api_access_available(self, obj):
        if not obj.service_platform or obj.service_platform.status != StatusChoices.ACTIVE:
            return False
        expected_type = WAREHOUSE_TYPE_TO_PLATFORM_TYPE.get(obj.warehouse_type)
        if obj.service_platform.platform_type != expected_type:
            return False
        provider = self._service_platform_key(obj)
        if not provider:
            return False
        from apps.integrations.platform_capabilities import get_platform_capability

        try:
            return "inventory" in get_platform_capability(provider).api_types
        except DjangoValidationError:
            return False

    def validate_service_platform_id(self, value):
        request = self.context["request"]
        if value.tenant_id != request.user.tenant_id:
            raise serializers.ValidationError("仓储服务平台必须属于当前租户。")
        if value.status != StatusChoices.ACTIVE:
            raise serializers.ValidationError("仓储服务平台必须处于启用状态。")
        if value.platform_type not in WAREHOUSE_SERVICE_PLATFORM_TYPES:
            raise serializers.ValidationError("所选平台不是仓储服务平台类型。")
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        warehouse_type = attrs.get("warehouse_type", getattr(self.instance, "warehouse_type", None))
        service_platform = attrs.get("service_platform", getattr(self.instance, "service_platform", None))
        expected_platform_type = WAREHOUSE_TYPE_TO_PLATFORM_TYPE.get(warehouse_type)
        if expected_platform_type is None:
            raise serializers.ValidationError({"warehouse_type": "仓库类型无效。"})
        if service_platform:
            request = self.context["request"]
            if service_platform.tenant_id != request.user.tenant_id:
                raise serializers.ValidationError({"service_platform_id": "仓储服务平台必须属于当前租户。"})
            if service_platform.status != StatusChoices.ACTIVE:
                raise serializers.ValidationError({"service_platform_id": "仓储服务平台必须处于启用状态。"})
        if service_platform is None:
            if warehouse_type != WarehouseMaster.WarehouseType.OWNED:
                raise serializers.ValidationError({"service_platform_id": "三方仓和平台仓必须绑定仓储服务平台。"})
        elif service_platform.platform_type != expected_platform_type:
            raise serializers.ValidationError({"service_platform_id": "仓储服务平台类型必须与仓库类型一致。"})
        from apps.integrations.platform_schema_service import integration_platform_key
        provider = integration_platform_key(platform_type=service_platform.platform_type, code=service_platform.code, name=service_platform.name) if service_platform else ""
        if self.instance and any(attrs.get(key, getattr(self.instance, key)) != getattr(self.instance, key)
                                 for key in ("service_platform", "country_code", "warehouse_type")):
            from apps.integrations.models import WarehouseAuthorization
            if WarehouseAuthorization.objects.filter(warehouse=self.instance, status="active").exists():
                raise serializers.ValidationError("请先在 API 接入中撤销现有绑定，再更改仓库平台、国家或类型。")
        if not self.instance and provider == "jifeng_wms" and any(key.startswith("api_") for key in attrs):
            missing = [key for key in ("api_integration_config_id", "api_email", "api_token") if not attrs.get(key)]
            if missing:
                raise serializers.ValidationError({key: "首次配置极风仓库时必填。" for key in missing})
        if any(key.startswith("api_") for key in attrs) and provider != "jifeng_wms":
            raise serializers.ValidationError("仅极风平台支持这组仓库 API 凭据。")
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["api_validation_status"] = "unconfigured"
        from apps.integrations.models import WarehouseAuthorization
        from apps.permissions.services import check_user_permission
        from apps.permissions.ui_p6_scopes import filter_warehouse_authorizations

        user = getattr(self.context.get("request"), "user", None)
        if user and check_user_permission(user, "integrations.warehouse.view"):
            query = WarehouseAuthorization.objects.filter(tenant_id=user.tenant_id, warehouse=instance, status="active")
            record = filter_warehouse_authorizations(user, query, "integrations.warehouse.view").first()
            if record:
                data.update(api_integration_config_id=record.integration_config_id, api_email=record.email,
                            api_external_warehouse_code=record.external_warehouse_code,
                            api_validation_status=record.validation_status)
        return data

    def _save_api(self, instance, values):
        from apps.integrations.models import PlatformIntegrationConfig, WarehouseAuthorization
        from apps.integrations.warehouse_authorization_service import bind_warehouse_authorization
        from apps.integrations.warehouse_credential_service import save_warehouse_credentials
        from apps.permissions.services import check_user_permission
        from apps.permissions.ui_p6_scopes import integration_values_allowed

        if not values:
            return
        actor = self.context["request"].user
        if not check_user_permission(actor, "integrations.warehouse.authorize"):
            raise serializers.ValidationError("无权维护仓库 API 授权，仓库未保存。")
        current = WarehouseAuthorization.objects.select_for_update().filter(tenant_id=actor.tenant_id, warehouse=instance, status="active").first()
        config_id = values.get("api_integration_config_id") or (current.integration_config_id if current else None)
        config = PlatformIntegrationConfig.objects.filter(tenant_id=actor.tenant_id, pk=config_id).first()
        if not config:
            raise serializers.ValidationError({"api_integration_config_id": "请选择当前租户的接入配置。"})
        if (current and not current.email and not values.get("api_email") and not values.get("api_token")
                and config.pk == current.integration_config_id
                and values.get("api_external_warehouse_code", current.external_warehouse_code) == current.external_warehouse_code):
            # Metadata-only edits must not force legacy credentials to be replaced.
            return
        if not integration_values_allowed(actor, "integrations.warehouse.authorize", platform=config.platform,
                environment=config.environment, regions=config.regions or [instance.country_code], config_id=config.pk,
                resource_type="inventory_snapshot", warehouse_id=instance.pk):
            raise serializers.ValidationError("仓库 API 配置超出授权数据范围，仓库未保存。")
        record, _, _ = bind_warehouse_authorization(actor=actor, warehouse=instance, integration_config=config,
            replace=bool(current), expected_authorization_id=current.pk if current else None,
            external_warehouse_code=values.get("api_external_warehouse_code", current.external_warehouse_code if current else ""))
        save_warehouse_credentials(actor=actor, authorization=record,
            email=values.get("api_email", record.email), token=values.get("api_token", ""))

    @transaction.atomic
    def create(self, validated_data):
        values = {key: validated_data.pop(key) for key in list(validated_data) if key.startswith("api_")}
        instance = super().create(validated_data)
        self._save_api(instance, values)
        return instance

    @transaction.atomic
    def update(self, instance, validated_data):
        values = {key: validated_data.pop(key) for key in list(validated_data) if key.startswith("api_")}
        instance = super().update(instance, validated_data)
        self._save_api(instance, values)
        return instance

    def _latest_snapshot(self, obj):
        from apps.commerce.models import InventorySnapshot

        if not hasattr(obj, "_latest_inventory_snapshot"):
            obj._latest_inventory_snapshot = InventorySnapshot.objects.filter(
                tenant=obj.tenant, warehouse=obj
            ).select_related("source_run").order_by("-snapshot_at_utc").first()
        return obj._latest_inventory_snapshot

    def get_api_connected(self, obj):
        if not self.get_api_access_available(obj):
            return False
        from apps.integrations.models import WarehouseAuthorization

        return WarehouseAuthorization.objects.filter(
            tenant_id=obj.tenant_id,
            warehouse_id=obj.id,
            status__in=["authorized", WarehouseAuthorization.Status.ACTIVE],
            validation_status=WarehouseAuthorization.ValidationStatus.VERIFIED,
            last_verified_at__isnull=False,
        ).exists()

    def get_site_code(self, obj):
        snapshot = self._latest_snapshot(obj)
        return snapshot.site_code if snapshot else ""

    def get_last_sync_at(self, obj):
        snapshot = self._latest_snapshot(obj)
        return snapshot.source_run.finished_at if snapshot and snapshot.source_run else None

    def get_last_sync_status(self, obj):
        snapshot = self._latest_snapshot(obj)
        return snapshot.source_run.status if snapshot and snapshot.source_run else "pending"


class SupplierMasterSerializer(TenantOwnedSerializer):
    contact_email_masked = serializers.SerializerMethodField()
    contact_phone_masked = serializers.SerializerMethodField()
    contact_email = serializers.EmailField(write_only=True, required=False, allow_blank=True)
    contact_phone = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = SupplierMaster
        fields = (
            "id", "tenant_id", "code", "name", "contact_alias", "contact_email", "contact_phone",
            "contact_email_masked", "contact_phone_masked", "status", "created_at", "updated_at",
        )
        read_only_fields = ("id", "tenant_id", "contact_email_masked", "contact_phone_masked", "created_at", "updated_at")

    def get_contact_email_masked(self, obj):
        return mask_email(obj.contact_email)

    def get_contact_phone_masked(self, obj):
        return mask_phone(obj.contact_phone)


SERIALIZER_BY_RESOURCE = {
    "platforms": PlatformMasterSerializer,
    "platform-sites": PlatformSiteMasterSerializer,
    "stores": StoreMasterSerializer,
    "sites": CountrySiteMasterSerializer,
    "warehouses": WarehouseMasterSerializer,
    "suppliers": SupplierMasterSerializer,
}

MODEL_BY_RESOURCE = {
    "platforms": PlatformMaster,
    "platform-sites": PlatformSiteMaster,
    "stores": StoreMaster,
    "sites": CountrySiteMaster,
    "warehouses": WarehouseMaster,
    "suppliers": SupplierMaster,
}
