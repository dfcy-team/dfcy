from django.core.exceptions import ValidationError as DjangoValidationError
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

    def validate(self, attrs):
        attrs = super().validate(attrs)
        site_id = attrs.get("platform_site_id", getattr(self.instance, "platform_site_id", None))
        platform_id = attrs.get("platform_id", getattr(self.instance, "platform_id", None))
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
        return attrs

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
