from rest_framework.permissions import BasePermission

from apps.accounts.models import CustomUser
from apps.permissions.services import check_user_permission


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
        )


class IsConfigViewer(ConfigActionPermission):
    permission_code = "config.view"


class IsConfigManager(ConfigActionPermission):
    permission_code = "config.manage"


class IsConfigApprover(ConfigActionPermission):
    permission_code = "config.approve"


class IsConfigRollbackManager(ConfigActionPermission):
    permission_code = "config.rollback"
