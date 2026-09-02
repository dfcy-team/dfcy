from rest_framework.permissions import BasePermission

from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope
from apps.permissions.services import check_user_permission, get_permission_data_scopes


class ConfigActionPermission(BasePermission):
    permission_code = None

    def has_permission(self, request, view):
        user = request.user
        return bool(
            self.permission_code
            and user
            and user.is_authenticated
            and user.user_type == CustomUser.UserType.INTERNAL
            and check_user_permission(user, self.permission_code)
            # Configuration is tenant-wide governance data.  A role that only
            # has own/department scope must not read or mutate the complete
            # configuration surface through this endpoint.
            and any(
                scope["scope_type"] == DataScope.ScopeType.ALL
                for scope in get_permission_data_scopes(user, self.permission_code)
            )
        )


class IsConfigViewer(ConfigActionPermission):
    permission_code = "config.view"


class IsConfigManager(ConfigActionPermission):
    permission_code = "config.manage"


class IsConfigApprover(ConfigActionPermission):
    permission_code = "config.approve"


class IsConfigRollbackManager(ConfigActionPermission):
    permission_code = "config.rollback"
