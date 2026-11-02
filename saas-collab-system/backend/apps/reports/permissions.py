from rest_framework.permissions import BasePermission

from apps.accounts.models import CustomUser
from apps.common.error_codes import ErrorCode
from apps.common.exceptions import DataScopeDenied
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from apps.permissions.ui_p6_scopes import analytics_dimension_configs, filter_analytics_queryset


class AnalyticsActionPermission(BasePermission):
    permission_code = None

    def has_permission(self, request, view):
        user = request.user
        cache = getattr(request, "_permission_resolution_cache", None)
        if cache is None:
            cache = {}
            request._permission_resolution_cache = cache
        allowed = bool(
            self.permission_code
            and user
            and user.is_authenticated
            and user.user_type == CustomUser.UserType.INTERNAL
            and check_user_permission(user, self.permission_code, cache=cache)
        )
        if not allowed:
            return False
        if not get_permission_data_scopes(user, self.permission_code, cache=cache):
            raise DataScopeDenied("The declared permission has no data scope.", error_code=ErrorCode.DATA_SCOPE_MISSING)
        return True


class IsAnalyticsViewer(AnalyticsActionPermission):
    permission_code = "analytics.view"


class IsAdvertisingViewer(BasePermission):
    """Authorize advertising reads by action grant and the unified store boundary."""
    permission_code = "analytics.view"

    def has_permission(self, request, view):
        user = request.user
        cache = getattr(request, "_permission_resolution_cache", None)
        if cache is None:
            cache = {}
            request._permission_resolution_cache = cache
        if (not user or not user.is_authenticated or not user.is_active
                or user.user_type != CustomUser.UserType.INTERNAL or not user.tenant_id
                or not user.tenant or user.tenant.status != "active"
                or not check_user_permission(user, self.permission_code, cache=cache)):
            return False
        from .advertising_dataset import advertising_store_scope, _uses_legacy_advertising_scope
        mode, store_ids = advertising_store_scope(user)
        if not store_ids and mode != "superuser" and not _uses_legacy_advertising_scope(user):
            return False
        return True


class IsAnalyticsCalculator(AnalyticsActionPermission):
    permission_code = "analytics.calculate"


class IsReportViewer(AnalyticsActionPermission):
    permission_code = "reports.view"


class IsDatasetReportViewer(BasePermission):
    """Keep report actions; dataset handlers enforce each data boundary."""
    permission_code = "reports.view"

    def has_permission(self, request, view):
        user = request.user
        cache = getattr(request, "_permission_resolution_cache", None)
        if cache is None:
            cache = {}
            request._permission_resolution_cache = cache
        request._report_advertising_scope_fallback = False
        if (not user or not user.is_authenticated or not user.is_active
                or user.user_type != CustomUser.UserType.INTERNAL or not user.tenant_id
                or not user.tenant or user.tenant.status != "active"
                or not check_user_permission(user, self.permission_code, cache=cache)):
            return False
        if get_permission_data_scopes(user, self.permission_code, cache=cache):
            return True
        if not IsAdvertisingViewer().has_permission(request, view):
            return False
        request._report_advertising_scope_fallback = True
        return True


class IsReportExporter(AnalyticsActionPermission):
    permission_code = "reports.export"


class IsReportDownloader(AnalyticsActionPermission):
    permission_code = "reports.download"


def get_analytics_dimension_scopes(user, permission_code="analytics.view"):
    return analytics_dimension_configs(user, permission_code)


def filter_analytics_aggregates(user, queryset, permission_code="analytics.view"):
    return filter_analytics_queryset(user, queryset, permission_code)


def can_access_analytics_dimensions(user, dimensions, permission_code="analytics.calculate"):
    dimension_scopes = get_analytics_dimension_scopes(user, permission_code)
    if dimension_scopes is None:
        return True
    return any(all(dimensions.get(key) == value for key, value in scope.items()) for scope in dimension_scopes)


def filter_authorized_metric_definitions(user, queryset):
    permission_codes = queryset.values_list("permission_code", flat=True).distinct()
    allowed_codes = [code for code in permission_codes if check_user_permission(user, code)]
    return queryset.filter(permission_code__in=allowed_codes)
