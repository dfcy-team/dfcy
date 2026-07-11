from django.db.models import Q
from rest_framework.permissions import BasePermission

from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope
from apps.permissions.services import check_user_permission, get_user_data_scope


class AnalyticsActionPermission(BasePermission):
    permission_code = None

    def has_permission(self, request, view):
        user = request.user
        return bool(
            self.permission_code
            and user
            and user.is_authenticated
            and user.user_type == CustomUser.UserType.INTERNAL
            and check_user_permission(user, self.permission_code)
        )


class IsAnalyticsViewer(AnalyticsActionPermission):
    permission_code = "analytics.view"


class IsAnalyticsCalculator(AnalyticsActionPermission):
    permission_code = "analytics.calculate"


class IsReportViewer(AnalyticsActionPermission):
    permission_code = "reports.view"


class IsReportExporter(AnalyticsActionPermission):
    permission_code = "reports.export"


def get_analytics_dimension_scopes(user):
    if getattr(user, "is_superuser", False):
        return None

    scopes = get_user_data_scope(user)
    if any(scope["scope_type"] == DataScope.ScopeType.ALL for scope in scopes):
        return None

    dimension_scopes = []
    for scope in scopes:
        if scope["scope_type"] != DataScope.ScopeType.CUSTOM:
            continue
        configured_scopes = scope.get("config", {}).get("analytics_dimensions", [])
        dimension_scopes.extend(value for value in configured_scopes if isinstance(value, dict) and value)
    return dimension_scopes


def filter_analytics_aggregates(user, queryset):
    dimension_scopes = get_analytics_dimension_scopes(user)
    if dimension_scopes is None:
        return queryset
    if not dimension_scopes:
        return queryset.none()

    allowed = Q()
    for dimensions in dimension_scopes:
        condition = Q()
        for key, value in dimensions.items():
            condition &= Q(**{f"dimensions__{key}": value})
        allowed |= condition
    return queryset.filter(allowed)


def can_access_analytics_dimensions(user, dimensions):
    dimension_scopes = get_analytics_dimension_scopes(user)
    if dimension_scopes is None:
        return True
    return any(all(dimensions.get(key) == value for key, value in scope.items()) for scope in dimension_scopes)


def filter_authorized_metric_definitions(user, queryset):
    permission_codes = queryset.values_list("permission_code", flat=True).distinct()
    allowed_codes = [code for code in permission_codes if check_user_permission(user, code)]
    return queryset.filter(permission_code__in=allowed_codes)
