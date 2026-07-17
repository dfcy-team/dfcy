from rest_framework.permissions import BasePermission

from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope
from apps.permissions.services import check_user_permission, get_permission_data_scopes


class WorkflowActionPermission(BasePermission):
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
    return type(name, (WorkflowActionPermission,), {"permission_code": code})


IsApprovalViewer = permission_class("workflow.approvals.view", "IsApprovalViewer")
IsApprovalSubmitter = permission_class("workflow.approvals.submit", "IsApprovalSubmitter")
IsApprovalReviewer = permission_class("workflow.approvals.review", "IsApprovalReviewer")
IsApprovalWithdrawer = permission_class("workflow.approvals.withdraw", "IsApprovalWithdrawer")
IsExceptionViewer = permission_class("workflow.exceptions.view", "IsExceptionViewer")
IsExceptionManager = permission_class("workflow.exceptions.manage", "IsExceptionManager")
IsCollaborationViewer = permission_class("workflow.collaboration.view", "IsCollaborationViewer")
IsCollaborationConfirmer = permission_class("workflow.collaboration.confirm", "IsCollaborationConfirmer")


def filter_permission_scope(user, permission_code, queryset, field_name, config_key):
    scopes = get_permission_data_scopes(user, permission_code)
    if any(scope["scope_type"] == DataScope.ScopeType.ALL for scope in scopes):
        return queryset
    allowed = set()
    for scope in scopes:
        if scope["scope_type"] != DataScope.ScopeType.CUSTOM:
            continue
        values = (scope.get("config") or {}).get(config_key, [])
        allowed.update(value for value in values if isinstance(value, str) and value)
    return queryset.filter(**{f"{field_name}__in": sorted(allowed)}) if allowed else queryset.none()


def scope_allows_value(user, permission_code, config_key, value):
    scopes = get_permission_data_scopes(user, permission_code)
    if any(scope["scope_type"] == DataScope.ScopeType.ALL for scope in scopes):
        return True
    return any(
        scope["scope_type"] == DataScope.ScopeType.CUSTOM
        and value in ((scope.get("config") or {}).get(config_key, []))
        for scope in scopes
    )
