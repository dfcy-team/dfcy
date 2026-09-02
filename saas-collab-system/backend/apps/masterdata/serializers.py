from rest_framework import serializers
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection

from apps.accounts.models import CustomUser
from apps.products.models import ProductCategory

from .models import (
    CountrySiteMaster,
    PlatformMaster,
    StatusChoices,
    StoreMaster,
    SupplierMaster,
    WarehouseMaster,
    WAREHOUSE_SERVICE_PLATFORM_TYPES,
    WAREHOUSE_TYPE_TO_PLATFORM_TYPE,
)


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
    class Meta:
        model = PlatformMaster
        fields = ("id", "tenant_id", "code", "name", "platform_type", "status", "created_at", "updated_at")
        read_only_fields = ("id", "tenant_id", "created_at", "updated_at")

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if not self.instance or "platform_type" not in attrs:
            return attrs
        platform_type = attrs["platform_type"]
        if self.instance.stores.exists() and platform_type in WAREHOUSE_SERVICE_PLATFORM_TYPES:
            raise serializers.ValidationError({
                "platform_type": "已有店铺引用的平台不能改为仓储服务平台。",
            })
        warehouses = self.instance.service_warehouses.all()
        if warehouses.exists():
            if platform_type not in WAREHOUSE_SERVICE_PLATFORM_TYPES:
                raise serializers.ValidationError({
                    "platform_type": "已有仓库引用的服务平台不能改为商城或其他平台。",
                })
            incompatible = warehouses.exclude(
                warehouse_type__in=[
                    warehouse_type
                    for warehouse_type, expected_type in WAREHOUSE_TYPE_TO_PLATFORM_TYPE.items()
                    if expected_type == platform_type
                ]
            )
            if incompatible.exists():
                raise serializers.ValidationError({
                    "platform_type": "平台类型必须与所有已绑定仓库的仓库类型一致。",
                })
        return attrs


class StoreMasterSerializer(TenantOwnedSerializer):
    platform_id = serializers.IntegerField()
    platform_name = serializers.CharField(source="platform.name", read_only=True)
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
    api_connected = serializers.SerializerMethodField()
    authorization_status = serializers.SerializerMethodField()
    mapping_status = serializers.SerializerMethodField()
    last_sync_at = serializers.SerializerMethodField()
    last_sync_status = serializers.SerializerMethodField()

    class Meta:
        model = StoreMaster
        fields = (
            "id", "tenant_id", "platform_id", "platform_name", "code", "name", "platform_store_name",
            "category_id", "category_name", "operator_id", "operator_name", "bd_id", "bd_name",
            "leader_id", "leader_name", "is_connected", "tactical_client", "country_code", "currency",
            "timezone", "status", "created_at", "updated_at",
            "api_connected", "authorization_status", "mapping_status", "last_sync_at", "last_sync_status",
        )
        read_only_fields = (
            "id", "tenant_id", "platform_name", "category_name", "operator_name", "bd_name", "leader_name",
            "created_at", "updated_at",
            "api_connected", "authorization_status", "mapping_status", "last_sync_at", "last_sync_status",
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

    def _latest_authorization(self, obj):
        from apps.integrations.models import MarketplaceStoreAuthorization

        if not hasattr(obj, "_latest_marketplace_authorization"):
            obj._latest_marketplace_authorization = MarketplaceStoreAuthorization.objects.filter(
                tenant=obj.tenant, store=obj
            ).order_by("-updated_at").first()
        return obj._latest_marketplace_authorization

    def get_api_connected(self, obj):
        authorization = self._latest_authorization(obj)
        return bool(authorization and authorization.status in {"authorized", "active"})

    def get_authorization_status(self, obj):
        authorization = self._latest_authorization(obj)
        return authorization.status if authorization else "not_connected"

    def get_mapping_status(self, obj):
        from apps.integrations.models import MarketplaceStoreMapping

        mapping = MarketplaceStoreMapping.objects.filter(tenant=obj.tenant, store=obj).order_by("-updated_at").first()
        return mapping.status if mapping else "unmapped"

    def _latest_order_run(self, obj):
        from apps.commerce.models import SalesOrder

        if not hasattr(obj, "_latest_sales_order_run"):
            order = SalesOrder.objects.filter(tenant=obj.tenant, store=obj).select_related("source_run").order_by("-ingested_at").first()
            obj._latest_sales_order_run = order.source_run if order else None
        return obj._latest_sales_order_run

    def get_last_sync_at(self, obj):
        run = self._latest_order_run(obj)
        return run.finished_at if run else None

    def get_last_sync_status(self, obj):
        run = self._latest_order_run(obj)
        return run.status if run else "pending"

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

    def validate(self, attrs):
        attrs = super().validate(attrs)
        category = attrs.get("category")
        if category and category.level != ProductCategory.Level.L1:
            raise serializers.ValidationError({"category_id": "Store category must be a top-level category."})
        return attrs

    def validate_platform_id(self, value):
        request = self.context["request"]
        from apps.permissions.ui_p2_scopes import filter_master_data

        queryset = PlatformMaster.objects.filter(pk=value, tenant=request.user.tenant)
        queryset = filter_master_data(request.user, queryset, "masterdata.manage", "platforms")
        if not queryset.exists():
            raise serializers.ValidationError("Platform is outside the current tenant or permitted data scope.")
        if queryset.filter(platform_type__in=WAREHOUSE_SERVICE_PLATFORM_TYPES).exists():
            raise serializers.ValidationError("仓储服务平台只能绑定到仓库档案，不能用于店铺档案。")
        return value


class CountrySiteMasterSerializer(TenantOwnedSerializer):
    class Meta:
        model = CountrySiteMaster
        fields = (
            "id", "tenant_id", "code", "name", "country_code", "currency", "timezone", "platform", "status",
            "created_at", "updated_at",
        )
        read_only_fields = ("id", "tenant_id", "created_at", "updated_at")


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
            "api_access_available",
            "api_connected", "site_code", "last_sync_at", "last_sync_status",
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
            raise serializers.ValidationError({
                "service_platform_id": "仓储服务平台类型必须与仓库类型一致。",
            })
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
        table = "integrations_warehouseauthorization"
        with connection.cursor() as cursor:
            if table not in connection.introspection.table_names(cursor):
                return False
            columns = {column.name for column in connection.introspection.get_table_description(cursor, table)}
            if not {"tenant_id", "warehouse_id", "status"}.issubset(columns):
                return False
            cursor.execute(
                f"SELECT 1 FROM {table} WHERE tenant_id=%s AND warehouse_id=%s "
                "AND status IN ('authorized','active') LIMIT 1",
                [obj.tenant_id, obj.id],
            )
            return cursor.fetchone() is not None

    def get_site_code(self, obj):
        snapshot = self._latest_snapshot(obj)
        return snapshot.site_code if snapshot else ""

    def get_last_sync_at(self, obj):
        snapshot = self._latest_snapshot(obj)
        return snapshot.source_run.finished_at if snapshot else None

    def get_last_sync_status(self, obj):
        snapshot = self._latest_snapshot(obj)
        return snapshot.source_run.status if snapshot else "pending"


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
    "stores": StoreMasterSerializer,
    "sites": CountrySiteMasterSerializer,
    "warehouses": WarehouseMasterSerializer,
    "suppliers": SupplierMasterSerializer,
}

MODEL_BY_RESOURCE = {
    "platforms": PlatformMaster,
    "stores": StoreMaster,
    "sites": CountrySiteMaster,
    "warehouses": WarehouseMaster,
    "suppliers": SupplierMaster,
}
