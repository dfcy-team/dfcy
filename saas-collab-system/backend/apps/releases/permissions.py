from rest_framework.permissions import BasePermission

from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope
from apps.permissions.services import check_user_permission, get_permission_data_scopes


class ReleasePermission(BasePermission):
    permission_code = None

    def has_permission(self, request, view):
        user = request.user
        return bool(
            self.permission_code
            and user
            and user.is_authenticated
            and user.user_type == CustomUser.UserType.INTERNAL
            and check_user_permission(user, self.permission_code)
            and get_permission_data_scopes(user, self.permission_code)
        )


def permission_class(code, name):
    return type(name, (ReleasePermission,), {"permission_code": code})


IsReleaseViewer = permission_class("release.contract.view", "IsReleaseViewer")
IsReleaseManager = permission_class("release.contract.manage", "IsReleaseManager")
IsReleaseApprover = permission_class("release.contract.approve", "IsReleaseApprover")
IsReleaseExecutor = permission_class("release.contract.execute", "IsReleaseExecutor")


def filter_release_scope(user, permission_code, queryset):
    queryset = queryset.filter(tenant=user.tenant)
    scopes = get_permission_data_scopes(user, permission_code)
    if any(scope["scope_type"] == DataScope.ScopeType.ALL for scope in scopes):
        return queryset
    if any(scope["scope_type"] == DataScope.ScopeType.OWN for scope in scopes):
        return queryset.filter(created_by=user)
    environments = set()
    for scope in scopes:
        if scope["scope_type"] != DataScope.ScopeType.CUSTOM:
            continue
        environments.update(
            value
            for value in (scope.get("config") or {}).get("release_environments", [])
            if isinstance(value, str)
        )
    return queryset.filter(environment__in=sorted(environments)) if environments else queryset.none()
