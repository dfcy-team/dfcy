from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import F, IntegerField, Value
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings

from .credential_auth import require_credential_lease
from .external_auth import (
    refresh_supplier_web_tokens,
    resolve_supplier_web_binding,
    stamp_supplier_web_claims,
)
from apps.permissions.lifecycle import effective_permissions, inactive_permissions, permission_is_effective
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.permissions.resource_policies import active_bindings, permission_resource
from apps.permissions.services import MENU_ACTION_FALLBACKS

from .models import CustomUser


class InternalTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        if self.user.user_type not in (CustomUser.UserType.INTERNAL, CustomUser.UserType.RPA):
            raise serializers.ValidationError("Only internal or RPA users can log in here.")
        require_credential_lease(self.user)
        return data


class UATAwareTokenRefreshSerializer(TokenRefreshSerializer):
    """Reject refresh before issuing a new access token for expired UAT users."""

    def validate(self, attrs):
        refresh = self.token_class(attrs["refresh"])
        user_id = refresh.payload.get(api_settings.USER_ID_CLAIM)
        if user_id is not None:
            user = get_user_model().objects.select_related("tenant").filter(pk=user_id).first()
            if user is not None:
                if not user.is_active:
                    raise serializers.ValidationError("账户已停用，不能刷新令牌。")
                require_credential_lease(user)
        return super().validate(attrs)


class SupplierWebTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Password login for an active, tenant-bound supplier-web identity."""

    @classmethod
    def get_token(cls, user):
        tenant, profile, supplier = resolve_supplier_web_binding(user)
        return stamp_supplier_web_claims(
            super().get_token(user),
            tenant_id=tenant.id,
            supplier_id=profile.supplier_id,
        )

    def validate(self, attrs):
        data = super().validate(attrs)
        # get_token above checks user type, tenant, profile and supplier status;
        # this final guard covers UAT leases without changing ordinary external
        # users whose lease fields are empty.
        require_credential_lease(self.user)
        return data


class SupplierWebTokenRefreshSerializer(TokenRefreshSerializer):
    """Refresh only a still-valid supplier-web token/binding."""

    def validate(self, attrs):
        refresh = self.token_class(attrs["refresh"])
        return refresh_supplier_web_tokens(refresh)


class CurrentUserSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(read_only=True)
    full_name = serializers.CharField(read_only=True)
    phone = serializers.CharField(read_only=True)
    roles = serializers.SerializerMethodField()
    role_labels = serializers.SerializerMethodField()
    identity_label = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()
    menu_permission_codes = serializers.SerializerMethodField()
    action_permission_codes = serializers.SerializerMethodField()
    field_permission_codes = serializers.SerializerMethodField()
    data_scope = serializers.SerializerMethodField()
    all_scope_permission_codes = serializers.SerializerMethodField()
    authorization_version = serializers.SerializerMethodField()
    inactive_permission_codes = serializers.SerializerMethodField()
    hidden_menu_permission_codes = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = (
            "user_id",
            "username",
            "email",
            "full_name",
            "phone",
            "user_type",
            "tenant_id",
            "is_superuser",
            "roles",
            "role_labels",
            "identity_label",
            "permissions",
            "menu_permission_codes",
            "action_permission_codes",
            "field_permission_codes",
            "data_scope",
            "all_scope_permission_codes",
            "authorization_version",
            "inactive_permission_codes", "hidden_menu_permission_codes",
        )

    user_id = serializers.IntegerField(source="id", read_only=True)

    @staticmethod
    def _menu_action_codes(row):
        metadata = row.get("metadata") or {}
        action_codes = metadata.get("action_codes") or []
        if action_codes:
            return action_codes
        menu_code = metadata.get("code") or row.get("code") or ""
        return MENU_ACTION_FALLBACKS.get(
            menu_code,
            (str(menu_code).removeprefix("menu."),),
        )

    def _authorization_snapshot(self, obj):
        """Resolve all /auth/me role capabilities in a bounded query set.

        Serializer instances are request-scoped, so this snapshot never
        survives a request and cannot hide role or scope revocations.
        """
        cached = getattr(self, "_authorization_snapshot_cache", None)
        if cached is not None:
            return cached

        if obj.is_superuser:
            permission_rows = list(
                Permission.objects.order_by("code").values(
                    "code", "permission_type", "metadata"
                )
            )
            inactive_codes = {row["code"] for row in permission_rows if not permission_is_effective(row["metadata"])}
            permission_rows = [row for row in permission_rows if row["code"] not in inactive_codes]
            categories = {
                permission_type: [
                    row["code"]
                    for row in permission_rows
                    if row["permission_type"] == permission_type
                ]
                for permission_type in (
                    Permission.PermissionType.MENU,
                    Permission.PermissionType.ACTION,
                    Permission.PermissionType.FIELD,
                )
            }
            snapshot = {
                "roles": [],
                "role_labels": ["平台超级管理员"],
                "permissions": [row["code"] for row in permission_rows],
                "categories": categories,
                "data_scope": [
                    {"scope_type": DataScope.ScopeType.ALL, "config": {"all": True}, "role_id": None}
                ],
                "all_scope_permission_codes": [row["code"] for row in permission_rows],
                "_inactive_codes": sorted(inactive_codes),
                "_hidden_menu_codes": [row["code"] for row in permission_rows if row["permission_type"] == "menu" and (row["metadata"] or {}).get("navigation_hidden")],
            }
            self._authorization_snapshot_cache = snapshot
            return snapshot

        role_rows = list(
            active_bindings(obj)
            .order_by("role__name", "role_id")
            .values("role_id", "role__code", "role__name").distinct()
        )
        role_ids = [row["role_id"] for row in role_rows]
        snapshot_fields = ("grant_role_id", "code", "permission_type", "metadata")
        granted_rows = effective_permissions().filter(roles__id__in=role_ids).order_by().annotate(
            grant_role_id=F("roles__id")
        ).values(*snapshot_fields)
        retired_rows = inactive_permissions().order_by().annotate(
            grant_role_id=Value(None, output_field=IntegerField())
        ).values(*snapshot_fields)
        # Fetch revoked implied actions with the grants in one query. This
        # keeps the existing three-query /me budget without a global M2M join.
        catalog_rows = list(granted_rows.union(retired_rows))
        inactive_codes = {row["code"] for row in catalog_rows if row["grant_role_id"] is None}
        permission_rows = [row for row in catalog_rows if row["grant_role_id"] is not None]
        from apps.permissions.models import RoleResourcePolicy
        scope_fields = ("scope_type", "config", "role_id", "resource_code", "permission_code")
        base_scopes = (
            DataScope.objects.filter(
                tenant_id=obj.tenant_id,
                role_id__in=role_ids,
                role__status=Role.Status.ACTIVE,
            ).order_by().annotate(resource_code=Value(""), permission_code=Value("*")).values(*scope_fields)
        )
        resource_scopes = RoleResourcePolicy.objects.filter(
            tenant_id=obj.tenant_id, role_id__in=role_ids,
        ).order_by().values(*scope_fields)
        data_scope = sorted(list(base_scopes.union(resource_scopes)), key=lambda row: (row["role_id"], row["resource_code"], row["permission_code"]))

        explicit_codes = {row["code"] for row in permission_rows}
        menu_codes = {
            row["code"]
            for row in permission_rows
            if row["permission_type"] == Permission.PermissionType.MENU
        }
        action_codes = {
            row["code"]
            for row in permission_rows
            if row["permission_type"] == Permission.PermissionType.ACTION
        }
        field_codes = {
            row["code"]
            for row in permission_rows
            if row["permission_type"] == Permission.PermissionType.FIELD
        }
        action_codes.update(
            action_code
            for row in permission_rows
            if row["permission_type"] == Permission.PermissionType.MENU
            for action_code in self._menu_action_codes(row)
            if str(action_code).endswith(".view") and action_code not in inactive_codes
        )
        all_scope_role_ids = {
            row["role_id"]
            for row in data_scope
            if row["scope_type"] == DataScope.ScopeType.ALL and not row["resource_code"]
        }
        all_scope_codes = {
            row["code"]
            for row in permission_rows
            if row["grant_role_id"] in all_scope_role_ids
        }
        all_scope_codes.update(
            action_code
            for row in permission_rows
            if row["grant_role_id"] in all_scope_role_ids
            and row["permission_type"] == Permission.PermissionType.MENU
            for action_code in self._menu_action_codes(row)
            if str(action_code).endswith(".view") and action_code not in inactive_codes
        )
        def unrestricted(row, code):
            resource = permission_resource(code)
            matches = [scope for scope in data_scope if scope["role_id"] == row["grant_role_id"]
                       and scope["resource_code"] == resource and scope["permission_code"] in ("*", code)] if resource else []
            exact = [scope for scope in matches if scope["permission_code"] == code]
            return any(scope["scope_type"] == "all" for scope in (exact or matches)) if matches else row["grant_role_id"] in all_scope_role_ids
        all_scope_codes = {
            code for code in all_scope_codes if any(
                unrestricted(row, code) and (row["code"] == code or (
                    row["permission_type"] == Permission.PermissionType.MENU and code in self._menu_action_codes(row)
                )) for row in permission_rows
            )
        }
        snapshot = {
            "roles": [row["role__code"] for row in role_rows],
            "role_labels": [row["role__name"] for row in role_rows],
            "permissions": sorted(explicit_codes),
            "categories": {
                "menu": sorted(menu_codes),
                "action": sorted(action_codes),
                "field": sorted(field_codes),
            },
            "data_scope": data_scope,
            "all_scope_permission_codes": sorted(all_scope_codes),
            "_inactive_codes": sorted(inactive_codes),
            "_hidden_menu_codes": sorted({row["code"] for row in permission_rows if row["permission_type"] == "menu" and (row["metadata"] or {}).get("navigation_hidden")}),
        }
        self._authorization_snapshot_cache = snapshot
        return snapshot

    def get_roles(self, obj):
        return self._authorization_snapshot(obj)["roles"]

    def get_role_labels(self, obj):
        return self._authorization_snapshot(obj)["role_labels"]

    def get_identity_label(self, obj):
        labels = self._authorization_snapshot(obj)["role_labels"]
        return " / ".join(labels) if labels else "未分配角色"

    def get_permissions(self, obj):
        return self._authorization_snapshot(obj)["permissions"]

    def _permission_categories(self, obj):
        return self._authorization_snapshot(obj)["categories"]

    def get_menu_permission_codes(self, obj):
        return self._permission_categories(obj)["menu"]

    def get_action_permission_codes(self, obj):
        return self._permission_categories(obj)["action"]

    def get_field_permission_codes(self, obj):
        return self._permission_categories(obj)["field"]

    def get_data_scope(self, obj):
        return [row if row.get("resource_code") else {key: row[key] for key in ("scope_type", "config", "role_id")}
                for row in self._authorization_snapshot(obj)["data_scope"]]

    def get_all_scope_permission_codes(self, obj):
        """Expose permission-specific all-scope grants for UI capability gating."""
        return self._authorization_snapshot(obj)["all_scope_permission_codes"]

    def get_authorization_version(self, obj):
        import hashlib
        import json
        snapshot = self._authorization_snapshot(obj)
        payload = {"user_id": obj.pk, "tenant_id": obj.tenant_id, "active": obj.is_active,
                   "membership_id": getattr(obj, "_active_membership_id", None), "snapshot": snapshot}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()

    def get_inactive_permission_codes(self, obj):
        return self._authorization_snapshot(obj)["_inactive_codes"]

    def get_hidden_menu_permission_codes(self, obj):
        return self._authorization_snapshot(obj)["_hidden_menu_codes"]


class CurrentUserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ("username", "full_name", "email", "phone")
        read_only_fields = ("username",)


class CurrentUserPasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(
        write_only=True,
        min_length=12,
        max_length=128,
        trim_whitespace=False,
    )
    confirm_password = serializers.CharField(
        write_only=True,
        min_length=12,
        max_length=128,
        trim_whitespace=False,
    )

    def validate(self, attrs):
        user = self.context.get("user") or self.context["request"].user
        if not user.check_password(attrs["current_password"]):
            raise serializers.ValidationError({"current_password": "当前密码不正确。"})
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "两次输入的密码不一致。"})
        try:
            validate_password(attrs["new_password"], user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": list(exc.messages)}) from exc
        return attrs
