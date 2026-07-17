from rest_framework.permissions import BasePermission

from apps.accounts.models import CustomUser
from apps.permissions.services import check_user_permission, get_permission_data_scopes


class IsPurchaseOrderReadOrManage(BasePermission):
    def has_permission(self, request, view):
        permission_code = "purchasing.orders.view" if request.method == "GET" else "purchasing.orders.manage"
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and user.user_type == CustomUser.UserType.INTERNAL
            and check_user_permission(user, permission_code)
            and get_permission_data_scopes(user, permission_code)
        )
