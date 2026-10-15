from django.db.models import Q
from rest_framework.exceptions import PermissionDenied

from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope
from apps.permissions.services import get_permission_data_scopes
from apps.purchasing.supply_permissions import require_internal_supply_permission, supplier_id_for_user


VIEW = "supply.v2.view"
MANAGE = "supply.v2.manage"


def internal_orders(user, queryset, permission=VIEW):
    if not user.is_active:
        raise PermissionDenied("An active procurement account is required.")
    require_internal_supply_permission(user, permission)
    queryset = queryset.filter(tenant_id=user.tenant_id)
    scopes = get_permission_data_scopes(user, permission)
    if any(s["scope_type"] == DataScope.ScopeType.ALL for s in scopes):
        return queryset
    allowed = Q(pk__in=[])
    for scope in scopes:
        if scope["scope_type"] == DataScope.ScopeType.OWN:
            allowed |= Q(created_by=user)
        elif scope["scope_type"] == DataScope.ScopeType.CUSTOM:
            config = scope.get("config") or {}
            # Use a dimension supported by the existing permission editor.
            # Legacy purchase IDs must never authorize unrelated new order IDs.
            ids = config.get("supplier_ids", [])
            if isinstance(ids, list):
                allowed |= Q(supplier_id__in=[int(v) for v in ids if str(v).isdigit()])
    return queryset.filter(allowed).distinct()


def supplier_orders(user, queryset):
    if not user.is_active:
        raise PermissionDenied("An active supplier account is required.")
    supplier_id = supplier_id_for_user(user)
    return queryset.filter(tenant_id=user.tenant_id, supplier_id=supplier_id, status="confirmed")


def accessible_orders(user, queryset, permission=VIEW):
    if user.user_type == CustomUser.UserType.EXTERNAL:
        return supplier_orders(user, queryset)
    return internal_orders(user, queryset, permission)
