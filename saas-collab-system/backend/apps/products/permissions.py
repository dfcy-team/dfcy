from rest_framework.permissions import BasePermission

from apps.accounts.models import CustomUser
from apps.common.error_codes import ErrorCode
from apps.common.exceptions import DataScopeDenied
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from apps.permissions.ui_p6_scopes import filter_lifecycle_queryset


class ProductStatusActionPermission(BasePermission):
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
        if not allowed:
            return False
        if not get_permission_data_scopes(user, self.permission_code):
            raise DataScopeDenied("The declared permission has no data scope.", error_code=ErrorCode.DATA_SCOPE_MISSING)
        return True


class IsProductStatusViewer(ProductStatusActionPermission):
    permission_code = "products.status.view"


class IsProductStatusEvaluator(ProductStatusActionPermission):
    permission_code = "products.status.evaluate"


class IsProductStatusConfirmer(ProductStatusActionPermission):
    permission_code = "products.status.confirm"


class IsLifecycleViewer(ProductStatusActionPermission):
    permission_code = "products.lifecycle.view"


class IsLifecycleEvaluator(ProductStatusActionPermission):
    permission_code = "products.lifecycle.evaluate"


class IsLifecycleConfirmer(ProductStatusActionPermission):
    permission_code = "products.lifecycle.confirm"


class ProductBusinessPermission(BasePermission):
    read_permission_code = None
    write_permission_code = None

    def has_permission(self, request, view):
        permission_code = self.read_permission_code if request.method == "GET" else self.write_permission_code
        user = request.user
        return bool(
            permission_code
            and user
            and user.is_authenticated
            and user.user_type == CustomUser.UserType.INTERNAL
            and check_user_permission(user, permission_code)
            and get_permission_data_scopes(user, permission_code)
        )


class IsProductResearchReadOrManage(ProductBusinessPermission):
    read_permission_code = "products.research.view"
    write_permission_code = "products.research.manage"


class IsProductMasterReadOrManage(ProductBusinessPermission):
    read_permission_code = "products.master.view"
    write_permission_code = "products.master.manage"


class IsProductCodeFreezer(ProductBusinessPermission):
    write_permission_code = "products.master.freeze"


def filter_lifecycle_reviews(user, queryset, permission_code="products.lifecycle.view"):
    queryset = queryset.filter(tenant=user.tenant)
    return filter_lifecycle_queryset(user, queryset, permission_code)
