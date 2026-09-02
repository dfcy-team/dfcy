import re

from django.db import transaction
from rest_framework import serializers

from apps.permissions.catalog import permission_display_name
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Department
from apps.rpa.models import RPAAgent
from apps.masterdata.models import (
    CountrySiteMaster,
    PlatformMaster,
    StoreMaster,
    SupplierMaster,
    WarehouseMaster,
)

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
        parent = Department.objects.filter(pk=value, tenant=self.context["request"].user.tenant).first()
        if parent is None:
            raise serializers.ValidationError("Parent department does not belong to the current tenant.")
        if self.instance and parent.pk == self.instance.pk:
            raise serializers.ValidationError("A department cannot be its own parent.")

        # A self-referential FK can otherwise create a cycle that makes the
        # hierarchy impossible to render and defeats scope traversal.  Walk
        # the proposed parent's ancestors before allowing the update.
        if self.instance:
            seen = set()
            current = parent
            while current is not None and current.pk not in seen:
                if current.pk == self.instance.pk:
                    raise serializers.ValidationError("A department cannot be moved below one of its descendants.")
                seen.add(current.pk)
                current = current.parent
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
    department_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False, default=list
    )
    department_name = serializers.SerializerMethodField()
    department_names = serializers.SerializerMethodField()
    role_codes = serializers.ListField(
        child=serializers.SlugField(max_length=80), write_only=True, required=False, default=list
    )
    roles = serializers.SerializerMethodField()
    role_labels = serializers.SerializerMethodField()
    initial_password = serializers.CharField(
        write_only=True,
        min_length=12,
        required=False,
        error_messages={
            "blank": "请输入初始密码。",
            "min_length": "初始密码至少需要12位。",
        },
    )

    class Meta:
        model = CustomUser
        fields = (
            "id", "tenant_id", "username", "full_name", "email_masked", "phone_masked", "user_type", "is_active",
            "department_id", "department_ids", "department_name", "department_names",
            "role_codes", "roles", "role_labels", "initial_password", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "tenant_id", "email_masked", "phone_masked", "department_name", "department_names",
            "roles", "role_labels", "created_at", "updated_at",
        )
        extra_kwargs = {
            "username": {
                "error_messages": {
                    "required": "请输入用户名。",
                    "blank": "请输入用户名。",
                    "unique": "该用户名已存在。",
                }
            }
        }

    def get_email_masked(self, obj):
        return mask_email(obj.email)

    def get_phone_masked(self, obj):
        return mask_phone(obj.phone)

    def get_department_name(self, obj):
        profile = getattr(obj, "internal_profile", None)
        return profile.department.name if profile and profile.department else ""

    def get_department_names(self, obj):
        profile = getattr(obj, "internal_profile", None)
        if not profile:
            return []
        cached_departments = getattr(profile, "_prefetched_objects_cache", {}).get("departments")
        if cached_departments is not None:
            names = sorted({department.name for department in cached_departments})
        else:
            names = list(profile.departments.order_by("name").values_list("name", flat=True))
        if profile.department and profile.department.name not in names:
            names.insert(0, profile.department.name)
        return names

    def _tenant_user_roles(self, obj):
        """Use the prefetched role links when the collection endpoint supplied them.

        The old serializer called ``filter().select_related()`` for every user,
        defeating ``prefetch_related('user_roles__role')`` and producing an
        N+1 query pattern on large tenants.  Keep the fallback query for detail
        serializers while making the list path bounded to its prefetch.
        """
        cached = getattr(obj, "_prefetched_objects_cache", {}).get("user_roles")
        if cached is not None:
            return [
                link for link in cached
                if link.tenant_id == obj.tenant_id
                and getattr(link.role, "tenant_id", obj.tenant_id) == obj.tenant_id
            ]
        return list(
            obj.user_roles.filter(
                tenant=obj.tenant,
                role__tenant=obj.tenant,
            ).select_related("role")
        )

    def get_roles(self, obj):
        return [item.role.code for item in self._tenant_user_roles(obj)]

    def get_role_labels(self, obj):
        return [
            f"{item.role.name}（{item.role.code}）"
            for item in sorted(self._tenant_user_roles(obj), key=lambda item: item.role.name)
        ]
    def validate(self, attrs):
        request = self.context["request"]
        if self.instance is None and not attrs.get("initial_password"):
            raise serializers.ValidationError({"initial_password": "请输入初始密码。"})
        user_type = attrs.get("user_type", CustomUser.UserType.INTERNAL)
        if user_type not in (CustomUser.UserType.INTERNAL, CustomUser.UserType.RPA):
            raise serializers.ValidationError({"user_type": "Only internal or RPA users can be created here."})
        department_id = attrs.get("department_id")
        if department_id and not Department.objects.filter(pk=department_id, tenant=request.user.tenant).exists():
            raise serializers.ValidationError({"department_id": "Department does not belong to the current tenant."})
        department_ids = set(attrs.get("department_ids", []))
        if department_id:
            department_ids.add(department_id)
        if department_ids:
            found = set(
                Department.objects.filter(pk__in=department_ids, tenant=request.user.tenant)
                .values_list("pk", flat=True)
            )
            if found != department_ids:
                raise serializers.ValidationError({"department_ids": "所选部门不属于当前租户。"})
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
        department_ids = validated_data.pop("department_ids", [])
        if not department_id and department_ids:
            department_id = department_ids[0]
        user = CustomUser.objects.create_user(password=password, tenant=tenant, **validated_data)
        if user.user_type == CustomUser.UserType.INTERNAL:
            profile = InternalUserProfile.objects.create(user=user, tenant=tenant, department_id=department_id)
            profile.departments.set(department_ids or ([department_id] if department_id else []))
        else:
            RPAAgent.objects.create(
                user=user,
                tenant=tenant,
                name=user.full_name or user.username,
                token_hash="managed-by-user-auth",
                execution_mode=RPAAgent.ExecutionMode.DRY_RUN,
            )
        for role in Role.objects.filter(tenant=tenant, code__in=role_codes):
            UserRole.objects.create(tenant=tenant, user=user, role=role)
        return user


class UserProfileUpdateSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    department_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, allow_empty=True
    )

    def validate_department_ids(self, value):
        tenant = self.context["request"].user.tenant
        ids = set(value)
        found = set(Department.objects.filter(tenant=tenant, pk__in=ids).values_list("pk", flat=True))
        if found != ids:
            raise serializers.ValidationError("所选部门不属于当前租户。")
        return list(dict.fromkeys(value))


class UserPasswordResetSerializer(serializers.Serializer):
    new_password = serializers.CharField(write_only=True, min_length=12, max_length=128, trim_whitespace=False)
    confirm_password = serializers.CharField(write_only=True, min_length=12, max_length=128, trim_whitespace=False)

    def validate(self, attrs):
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "两次输入的密码不一致。"})
        return attrs


class PermissionAdminSerializer(serializers.ModelSerializer):
    # Legacy migrations seeded English ``Permission.name`` values.  The
    # permission code remains the trusted API value, while this read-only
    # presentation field consistently exposes the Chinese administration label.
    name = serializers.SerializerMethodField()

    class Meta:
        model = Permission
        fields = ("id", "code", "name", "module", "action", "description")
        read_only_fields = fields

    def get_name(self, obj):
        return permission_display_name(obj.code, obj.name)


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
        cached = getattr(obj, "_prefetched_objects_cache", {}).get("permissions")
        if cached is not None:
            return [permission.code for permission in sorted(cached, key=lambda item: item.code)]
        return list(obj.permissions.order_by("code").values_list("code", flat=True))

    def get_data_scopes(self, obj):
        cached = getattr(obj, "_prefetched_objects_cache", {}).get("data_scopes")
        if cached is not None:
            return [{"scope_type": scope.scope_type, "config": scope.config} for scope in cached]
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

    def validate(self, attrs):
        """Validate scope shape and every referenced object in the actor tenant.

        The permission API is intentionally strict: a malformed custom scope
        must fail closed instead of becoming an effectively unscoped role.
        ``department`` means the actor's current department per the shared
        scope contract.  Older clients may send a department_ids hint; it is
        validated as metadata but does not widen the effective current-
        department scope.
        """
        scope_type = attrs.get("scope_type")
        config = attrs.get("scope_config")
        if config is None:
            config = {}
        if not isinstance(config, dict):
            raise serializers.ValidationError({"scope_config": "数据范围配置必须是对象。"})

        allowed_keys = {
            DataScope.ScopeType.ALL: {"all"},
            DataScope.ScopeType.OWN: {"owner_field"},
            DataScope.ScopeType.DEPARTMENT: {"department_ids"},
            DataScope.ScopeType.CUSTOM: {
                "user_ids", "department_ids", "role_ids",
                "platform_ids", "store_ids", "site_ids", "warehouse_ids", "supplier_ids",
            },
        }[scope_type]
        unknown = sorted(set(config) - allowed_keys)
        if unknown:
            raise serializers.ValidationError({"scope_config": f"不支持的数据范围字段：{', '.join(unknown)}"})

        if scope_type == DataScope.ScopeType.ALL:
            if config and config.get("all") is not True:
                raise serializers.ValidationError({"scope_config": "全部范围只能使用 all=true。"})
            attrs["scope_config"] = {"all": True} if config else {}
            return attrs

        if scope_type == DataScope.ScopeType.OWN:
            owner_field = config.get("owner_field")
            if owner_field is not None and (
                not isinstance(owner_field, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", owner_field)
            ):
                raise serializers.ValidationError({"scope_config": "owner_field 必须是合法字段名。"})
            attrs["scope_config"] = config
            return attrs

        if scope_type == DataScope.ScopeType.DEPARTMENT:
            if "department_ids" in config:
                values = config["department_ids"]
                if not isinstance(values, list):
                    raise serializers.ValidationError({"scope_config": "department_ids 必须是 ID 数组。"})
                if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in values):
                    raise serializers.ValidationError({"scope_config": "department_ids 只能包含正整数 ID。"})
                config = {"department_ids": sorted(set(values))}
            attrs["scope_config"] = config
            return attrs

        tenant = self.context.get("request").user.tenant if self.context.get("request") else None
        if not config:
            raise serializers.ValidationError({"scope_config": "custom 范围至少配置一个授权维度。"})
        normalized = {}
        model_by_key = {
            "user_ids": CustomUser,
            "department_ids": Department,
            "role_ids": Role,
            "platform_ids": PlatformMaster,
            "store_ids": StoreMaster,
            "site_ids": CountrySiteMaster,
            "warehouse_ids": WarehouseMaster,
            "supplier_ids": SupplierMaster,
        }
        for key, values in config.items():
            if not isinstance(values, list) or not values:
                raise serializers.ValidationError({"scope_config": f"{key} 必须是非空 ID 数组。"})
            ids = []
            for value in values:
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    raise serializers.ValidationError({"scope_config": f"{key} 只能包含正整数 ID。"})
                ids.append(value)
            ids = sorted(set(ids))
            model = model_by_key.get(key)
            if model is not None and tenant is not None:
                found = set(model.objects.filter(tenant=tenant, pk__in=ids).values_list("pk", flat=True))
                if found != set(ids):
                    raise serializers.ValidationError({"scope_config": f"{key} 包含当前租户之外的对象。"})
            normalized[key] = ids
        attrs["scope_config"] = normalized
        return attrs


class UserRoleUpdateSerializer(serializers.Serializer):
    role_codes = serializers.ListField(child=serializers.SlugField(max_length=80), allow_empty=True)

    def validate_role_codes(self, value):
        tenant = self.context["request"].user.tenant
        found = set(Role.objects.filter(tenant=tenant, code__in=value).values_list("code", flat=True))
        missing = sorted(set(value) - found)
        if missing:
            raise serializers.ValidationError(f"Unknown tenant role codes: {', '.join(missing)}")
        return sorted(set(value))
