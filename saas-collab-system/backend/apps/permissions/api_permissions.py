from rest_framework.permissions import BasePermission

from apps.accounts.models import CustomUser
from apps.permissions.services import user_has_finance_access


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
