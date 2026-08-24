from rest_framework import serializers

from apps.accounts.models import CustomUser
from apps.products.models import ProductCategory

from .models import CountrySiteMaster, PlatformMaster, StatusChoices, StoreMaster, SupplierMaster, WarehouseMaster


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

    class Meta:
        model = StoreMaster
        fields = (
            "id", "tenant_id", "platform_id", "platform_name", "code", "name", "platform_store_name",
            "category_id", "category_name", "operator_id", "operator_name", "bd_id", "bd_name",
            "leader_id", "leader_name", "is_connected", "tactical_client", "country_code", "currency",
            "timezone", "status", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "tenant_id", "platform_name", "category_name", "operator_name", "bd_name", "leader_name",
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
        return value


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
    class Meta:
        model = WarehouseMaster
        fields = (
            "id", "tenant_id", "code", "name", "country_code", "warehouse_type", "status", "created_at", "updated_at",
        )
        read_only_fields = ("id", "tenant_id", "created_at", "updated_at")


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
