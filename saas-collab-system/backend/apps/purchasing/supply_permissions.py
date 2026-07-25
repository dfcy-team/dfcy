from django.db.models import Q
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from apps.accounts.models import CustomUser
from apps.accounts.miniapp_auth import MINIAPP_TOKEN_CHANNEL
from apps.permissions.models import DataScope
from apps.permissions.services import check_user_permission, get_permission_data_scopes


def _configured_ids(scope, key):
    values = (scope.get("config") or {}).get(key, [])
    if not isinstance(values, list):
        return set()
    return {int(value) for value in values if str(value).isdigit()}


class IsNonMiniAppChannel(BasePermission):
    """Keep Mini Program tokens inside the /api/miniapp/* route partition."""

    message = "A Mini Program token cannot access this API channel."

    def has_permission(self, request, view):
        token = request.auth
        return not (token and token.get("channel") == MINIAPP_TOKEN_CHANNEL)


def require_internal_supply_permission(user, permission_code):
    if not (
        user
        and user.is_authenticated
        and user.user_type == CustomUser.UserType.INTERNAL
        and check_user_permission(user, permission_code)
        and get_permission_data_scopes(user, permission_code)
    ):
        raise PermissionDenied("The requested supply-chain permission is not available.")


def filter_internal_supply_orders(user, queryset, permission_code):
    queryset = queryset.filter(tenant=user.tenant)
    scopes = get_permission_data_scopes(user, permission_code)
    if any(scope["scope_type"] == DataScope.ScopeType.ALL for scope in scopes):
        return queryset

    allowed = Q(pk__in=[])
    for scope in scopes:
        if scope["scope_type"] == DataScope.ScopeType.OWN:
            allowed |= Q(created_by=user)
        elif scope["scope_type"] == DataScope.ScopeType.CUSTOM:
            order_ids = _configured_ids(scope, "supply_purchase_order_ids")
            supplier_ids = _configured_ids(scope, "supplier_ids")
            if order_ids:
                allowed |= Q(pk__in=order_ids)
            if supplier_ids:
                allowed |= Q(supplier_id__in=supplier_ids)
    return queryset.filter(allowed).distinct()


def authorize_internal_supplier(user, permission_code, supplier_id):
    scopes = get_permission_data_scopes(user, permission_code)
    if any(scope["scope_type"] in {DataScope.ScopeType.ALL, DataScope.ScopeType.OWN} for scope in scopes):
        return
    allowed_supplier_ids = set()
    for scope in scopes:
        if scope["scope_type"] == DataScope.ScopeType.CUSTOM:
            allowed_supplier_ids.update(_configured_ids(scope, "supplier_ids"))
    if supplier_id not in allowed_supplier_ids:
        raise PermissionDenied("The supplier is outside the authorized data scope.")


def supplier_id_for_user(user):
    if not (
        user
        and user.is_authenticated
        and user.user_type == CustomUser.UserType.EXTERNAL
    ):
        raise PermissionDenied("An active supplier account is required.")
    profile = getattr(user, "external_profile", None)
    if not profile or not profile.supplier_id:
        raise PermissionDenied("The supplier account is not bound to a supplier master record.")
    return profile.supplier_id


def filter_supplier_supply_orders(user, queryset):
    supplier_id = supplier_id_for_user(user)
    return queryset.filter(tenant=user.tenant, supplier_id=supplier_id)
