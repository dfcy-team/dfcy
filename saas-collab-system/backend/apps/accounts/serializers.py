from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings

from .credential_auth import require_credential_lease
from .external_auth import (
    refresh_supplier_web_tokens,
    resolve_supplier_web_binding,
    stamp_supplier_web_claims,
)
from apps.permissions.services import get_user_data_scope, get_user_permission_categories

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
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    roles = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()
    menu_permission_codes = serializers.SerializerMethodField()
    action_permission_codes = serializers.SerializerMethodField()
    field_permission_codes = serializers.SerializerMethodField()
    data_scope = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = (
            "user_id",
            "username",
            "email",
            "user_type",
            "tenant_id",
            "is_superuser",
            "roles",
            "permissions",
            "menu_permission_codes",
            "action_permission_codes",
            "field_permission_codes",
            "data_scope",
        )

    user_id = serializers.IntegerField(source="id", read_only=True)

    def get_roles(self, obj):
        return list(
            obj.user_roles.filter(tenant=obj.tenant, role__status="active")
            .select_related("role")
            .values_list("role__code", flat=True)
            .distinct()
        )

    def get_permissions(self, obj):
        if obj.is_superuser:
            categories = self._permission_categories(obj)
            return sorted({code for values in categories.values() for code in values})
        return list(
            obj.user_roles.filter(tenant=obj.tenant, role__status="active")
            .select_related("role")
            .prefetch_related("role__permissions")
            .values_list("role__permissions__code", flat=True)
            .exclude(role__permissions__code__isnull=True)
            .distinct()
        )

    def _permission_categories(self, obj):
        # Avoid performing three independent role traversals for one /me
        # response.  The serializer instance is request-scoped and safe to
        # cache for the duration of this representation.
        categories = getattr(obj, "_permission_categories", None)
        if categories is None:
            categories = get_user_permission_categories(obj)
            setattr(obj, "_permission_categories", categories)
        return categories

    def get_menu_permission_codes(self, obj):
        return self._permission_categories(obj)["menu"]

    def get_action_permission_codes(self, obj):
        return self._permission_categories(obj)["action"]

    def get_field_permission_codes(self, obj):
        return self._permission_categories(obj)["field"]

    def get_data_scope(self, obj):
        if obj.is_superuser:
            return [{"scope_type": "all", "config": {"all": True}, "role_id": None}]
        return get_user_data_scope(obj)
