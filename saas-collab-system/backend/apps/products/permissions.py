from rest_framework.permissions import BasePermission

from apps.accounts.models import CustomUser
from apps.permissions.services import check_user_permission


class ProductStatusActionPermission(BasePermission):
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


class IsProductStatusViewer(ProductStatusActionPermission):
    permission_code = "products.status.view"


class IsProductStatusEvaluator(ProductStatusActionPermission):
    permission_code = "products.status.evaluate"


class IsProductStatusConfirmer(ProductStatusActionPermission):
    permission_code = "products.status.confirm"
