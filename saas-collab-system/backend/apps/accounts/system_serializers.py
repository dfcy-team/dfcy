from django.db import transaction
from rest_framework import serializers

from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Department

from .models import CustomUser, InternalUserProfile


def mask_email(value):
    if not value or "@" not in value:
        return ""
    local, domain = value.split("@", 1)
    return f"{local[:1]}***@{domain}"


def mask_phone(value):
    return f"***{value[-4:]}" if value else ""


class DepartmentAdminSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    parent_id = serializers.IntegerField(required=False, allow_null=True)
    parent_name = serializers.CharField(source="parent.name", read_only=True)

    class Meta:
        model = Department
        fields = ("id", "tenant_id", "name", "parent_id", "parent_name", "status")
        read_only_fields = ("id", "tenant_id", "parent_name")

    def validate_parent_id(self, value):
        if value is None:
            return value
        if not Department.objects.filter(pk=value, tenant=self.context["request"].user.tenant).exists():
            raise serializers.ValidationError("Parent department does not belong to the current tenant.")
        return value

    def validate(self, attrs):
        request = self.context["request"]
        name = attrs.get("name", getattr(self.instance, "name", None))
        parent_id = attrs.get("parent_id", getattr(self.instance, "parent_id", None))
        if Department.objects.filter(tenant=request.user.tenant, name=name, parent_id=parent_id).exclude(
            pk=getattr(self.instance, "pk", None)
        ).exists():
            raise serializers.ValidationError({"name": "Department name must be unique under the same parent."})
        return attrs


class UserAdminSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    email_masked = serializers.SerializerMethodField()
    phone_masked = serializers.SerializerMethodField()
    department_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    department_name = serializers.SerializerMethodField()
    role_codes = serializers.ListField(
        child=serializers.SlugField(max_length=80), write_only=True, required=False, default=list
    )
    roles = serializers.SerializerMethodField()
    initial_password = serializers.CharField(write_only=True, min_length=12, required=False)

    class Meta:
        model = CustomUser
        fields = (
            "id", "tenant_id", "username", "email_masked", "phone_masked", "user_type", "is_active",
            "department_id", "department_name", "role_codes", "roles", "initial_password", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "tenant_id", "email_masked", "phone_masked", "department_name", "roles", "created_at", "updated_at",
        )

    def get_email_masked(self, obj):
        return mask_email(obj.email)

    def get_phone_masked(self, obj):
        return mask_phone(obj.phone)

    def get_department_name(self, obj):
        profile = getattr(obj, "internal_profile", None)
        return profile.department.name if profile and profile.department else ""

    def get_roles(self, obj):
        return list(
            obj.user_roles.filter(tenant=obj.tenant).select_related("role").values_list("role__code", flat=True)
        )

    def validate(self, attrs):
        request = self.context["request"]
        if self.instance is None and not attrs.get("initial_password"):
            raise serializers.ValidationError({"initial_password": "An initial password is required."})
        if attrs.get("user_type", CustomUser.UserType.INTERNAL) != CustomUser.UserType.INTERNAL:
            raise serializers.ValidationError({"user_type": "This endpoint only creates internal users."})
        department_id = attrs.get("department_id")
        if department_id and not Department.objects.filter(pk=department_id, tenant=request.user.tenant).exists():
            raise serializers.ValidationError({"department_id": "Department does not belong to the current tenant."})
        role_codes = attrs.get("role_codes", [])
        if role_codes:
            found = set(Role.objects.filter(tenant=request.user.tenant, code__in=role_codes).values_list("code", flat=True))
            missing = sorted(set(role_codes) - found)
            if missing:
                raise serializers.ValidationError({"role_codes": f"Unknown tenant role codes: {', '.join(missing)}"})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        tenant = self.context["request"].user.tenant
        password = validated_data.pop("initial_password")
        role_codes = validated_data.pop("role_codes", [])
        department_id = validated_data.pop("department_id", None)
        user = CustomUser.objects.create_user(password=password, tenant=tenant, **validated_data)
        InternalUserProfile.objects.create(user=user, tenant=tenant, department_id=department_id)
        for role in Role.objects.filter(tenant=tenant, code__in=role_codes):
            UserRole.objects.create(tenant=tenant, user=user, role=role)
        return user


class PermissionAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ("id", "code", "name", "module", "action", "description")
        read_only_fields = fields


class RoleAdminSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    permission_codes = serializers.SerializerMethodField()
    data_scopes = serializers.SerializerMethodField()

    class Meta:
        model = Role
        fields = (
            "id", "tenant_id", "name", "code", "status", "permission_codes", "data_scopes", "created_at", "updated_at",
        )
        read_only_fields = ("id", "tenant_id", "permission_codes", "data_scopes", "created_at", "updated_at")

    def get_permission_codes(self, obj):
        return list(obj.permissions.order_by("code").values_list("code", flat=True))

    def get_data_scopes(self, obj):
        return list(obj.data_scopes.values("scope_type", "config"))

    def validate_code(self, value):
        tenant = self.context["request"].user.tenant
        if Role.objects.filter(tenant=tenant, code=value).exclude(pk=getattr(self.instance, "pk", None)).exists():
            raise serializers.ValidationError("Role code must be unique within the current tenant.")
        return value


class RoleOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ("id", "name", "code", "status")
        read_only_fields = fields


class RolePermissionUpdateSerializer(serializers.Serializer):
    permission_codes = serializers.ListField(child=serializers.CharField(max_length=120), allow_empty=True)
    scope_type = serializers.ChoiceField(choices=DataScope.ScopeType.choices)
    scope_config = serializers.JSONField(required=False, default=dict)

    def validate_permission_codes(self, value):
        found = set(Permission.objects.filter(code__in=value).values_list("code", flat=True))
        missing = sorted(set(value) - found)
        if missing:
            raise serializers.ValidationError(f"Unknown permission codes: {', '.join(missing)}")
        return sorted(set(value))


class UserRoleUpdateSerializer(serializers.Serializer):
    role_codes = serializers.ListField(child=serializers.SlugField(max_length=80), allow_empty=True)

    def validate_role_codes(self, value):
        tenant = self.context["request"].user.tenant
        found = set(Role.objects.filter(tenant=tenant, code__in=value).values_list("code", flat=True))
        missing = sorted(set(value) - found)
        if missing:
            raise serializers.ValidationError(f"Unknown tenant role codes: {', '.join(missing)}")
        return sorted(set(value))
