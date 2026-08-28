from django.db.models import Q
from rest_framework.permissions import BasePermission

from apps.accounts.models import CustomUser
from apps.common.error_codes import ErrorCode
from apps.common.exceptions import DataScopeDenied
from apps.permissions.models import DataScope
from apps.permissions.services import check_user_permission, get_permission_data_scopes


class AlertActionPermission(BasePermission):
    permission_code = None

    def has_permission(self, request, view):
        user = request.user
        allowed = bool(
            self.permission_code
            and user
            and user.is_authenticated
            and user.user_type == CustomUser.UserType.INTERNAL
            and check_user_permission(user, self.permission_code)
        )
        if allowed and not get_permission_data_scopes(user, self.permission_code):
            raise DataScopeDenied("The declared permission has no data scope.", error_code=ErrorCode.DATA_SCOPE_MISSING)
        return allowed


class IsAlertViewer(AlertActionPermission):
    permission_code = "alerts.view"


class IsAlertEvaluator(AlertActionPermission):
    permission_code = "alerts.evaluate"


class IsAlertManager(AlertActionPermission):
    permission_code = "alerts.manage"


def filter_inventory_alerts(user, queryset, permission_code="alerts.view"):
    queryset = queryset.filter(tenant=user.tenant)
    if user.is_superuser:
        return queryset
    scopes = get_permission_data_scopes(user, permission_code)
    if any(scope["scope_type"] == DataScope.ScopeType.ALL for scope in scopes):
        return queryset
    allowed = Q(pk__in=[])
    for scope in scopes:
        if scope["scope_type"] != DataScope.ScopeType.CUSTOM:
            continue
        config = scope.get("config") or {}
        sku_ids = config.get("sku_ids", [])
        warehouse_codes = config.get("warehouse_codes", [])
        if not sku_ids and not warehouse_codes:
            continue
        scope_filter = Q()
        if sku_ids:
            scope_filter &= Q(sku_id__in=sku_ids)
        if warehouse_codes:
            scope_filter &= Q(warehouse_code__in=warehouse_codes)
        allowed |= scope_filter
    return queryset.filter(allowed)


def filter_business_alerts(user, queryset, permission_code="alerts.view"):
    queryset = queryset.filter(tenant=user.tenant)
    if user.is_superuser:
        return queryset
    scopes = get_permission_data_scopes(user, permission_code)
    if any(scope["scope_type"] == DataScope.ScopeType.ALL for scope in scopes):
        return queryset
    allowed = Q(pk__in=[])
    for scope in scopes:
        if scope["scope_type"] == DataScope.ScopeType.OWN:
            allowed |= Q(assigned_to=user)
        elif scope["scope_type"] == DataScope.ScopeType.CUSTOM:
            config = scope.get("config") or {}
            business_types = config.get("business_types", [])
            business_ids = [str(value) for value in config.get("business_ids", [])]
            if not business_types and not business_ids:
                continue
            scope_filter = Q()
            if business_types:
                scope_filter &= Q(business_type__in=business_types)
            if business_ids:
                scope_filter &= Q(business_id__in=business_ids)
            allowed |= scope_filter
    return queryset.filter(allowed)
