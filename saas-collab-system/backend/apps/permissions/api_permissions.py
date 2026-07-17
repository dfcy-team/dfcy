from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.models import CustomUser
from apps.common.error_codes import ErrorCode
from apps.common.exceptions import DataScopeDenied
from apps.permissions.services import (
    check_user_permission,
    get_permission_data_scopes,
    user_has_finance_access,
    user_has_finance_permission,
    user_has_integration_access,
    user_has_integration_permission,
)


class DeclaredApplicationPermission(BasePermission):
    """Authorize an internal endpoint using permission codes declared by its view."""

    def has_permission(self, request, view):
        permission_code = (
            getattr(view, "read_permission_code", None)
            if request.method in SAFE_METHODS
            else getattr(view, "write_permission_code", None)
        )
        return bool(
            permission_code
            and request.user
            and request.user.is_authenticated
            and request.user.user_type == CustomUser.UserType.INTERNAL
            and check_user_permission(request.user, permission_code)
            and bool(get_permission_data_scopes(request.user, permission_code))
        )


class IsInternalUser(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.user_type == CustomUser.UserType.INTERNAL)


class IsExternalUser(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.user_type == CustomUser.UserType.EXTERNAL)


class IsRPAAgent(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.user_type == CustomUser.UserType.RPA)


class IsFinanceUser(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.user_type == CustomUser.UserType.INTERNAL
            and user_has_finance_access(request.user)
        )


class IsIntegrationAdmin(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.user_type == CustomUser.UserType.INTERNAL
            and user_has_integration_access(request.user)
        )


class FinanceActionPermission(BasePermission):
    permission_code = None

    def has_permission(self, request, view):
        allowed = bool(
            self.permission_code
            and request.user
            and request.user.is_authenticated
            and request.user.user_type == CustomUser.UserType.INTERNAL
            and user_has_finance_permission(request.user, self.permission_code)
        )
        if not allowed:
            return False
        if not get_permission_data_scopes(request.user, self.permission_code):
            raise DataScopeDenied("The declared permission has no data scope.", error_code=ErrorCode.DATA_SCOPE_MISSING)
        return True


class IsFinanceViewer(FinanceActionPermission):
    permission_code = "finance.view"


class IsFinanceImporter(FinanceActionPermission):
    permission_code = "finance.import"


class IsFinanceReconciler(FinanceActionPermission):
    permission_code = "finance.reconcile"


class IsFinanceExceptionHandler(FinanceActionPermission):
    permission_code = "finance.exception.handle"


class IntegrationActionPermission(BasePermission):
    permission_code = None

    def has_action_permission(self, request, permission_code):
        allowed = bool(
            permission_code
            and request.user
            and request.user.is_authenticated
            and request.user.user_type == CustomUser.UserType.INTERNAL
            and user_has_integration_permission(request.user, permission_code)
        )
        if not allowed:
            return False
        if not get_permission_data_scopes(request.user, permission_code):
            raise DataScopeDenied("The declared permission has no data scope.", error_code=ErrorCode.DATA_SCOPE_MISSING)
        return True

    def has_permission(self, request, view):
        return self.has_action_permission(request, self.permission_code)


class IsIntegrationViewer(IntegrationActionPermission):
    permission_code = "integrations.view"


class IsIntegrationManager(IntegrationActionPermission):
    permission_code = "integrations.manage"


class IsIntegrationCredentialRotator(IntegrationActionPermission):
    permission_code = "integrations.rotate"


class IsIntegrationRunner(IntegrationActionPermission):
    permission_code = "integrations.run"


class IsIntegrationReadOrManage(IntegrationActionPermission):
    def has_permission(self, request, view):
        permission_code = "integrations.view" if request.method in SAFE_METHODS else "integrations.manage"
        return self.has_action_permission(request, permission_code)
