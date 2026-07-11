from rest_framework.permissions import BasePermission

from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope
from apps.permissions.services import check_user_permission, get_user_data_scope


class IsSupplierPerformanceViewer(BasePermission):
    permission_code = "suppliers.performance.view"

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.user_type == CustomUser.UserType.INTERNAL
            and check_user_permission(user, self.permission_code)
        )


class IsSupplierPerformanceCalculator(BasePermission):
    permission_code = "suppliers.performance.calculate"

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.user_type == CustomUser.UserType.INTERNAL
            and check_user_permission(user, self.permission_code)
        )


def get_supplier_performance_scope(user):
    if getattr(user, "is_superuser", False):
        return None

    scopes = get_user_data_scope(user)
    if any(scope["scope_type"] == DataScope.ScopeType.ALL for scope in scopes):
        return None

    supplier_ids = set()
    for scope in scopes:
        if scope["scope_type"] != DataScope.ScopeType.CUSTOM:
            continue
        configured_ids = scope.get("config", {}).get("supplier_ids", [])
        supplier_ids.update(int(value) for value in configured_ids if str(value).isdigit())
    return supplier_ids


def can_access_supplier_performance(user, supplier_id):
    allowed_supplier_ids = get_supplier_performance_scope(user)
    return allowed_supplier_ids is None or supplier_id in allowed_supplier_ids
