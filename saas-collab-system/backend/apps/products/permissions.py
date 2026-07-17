from rest_framework.permissions import BasePermission

from apps.accounts.models import CustomUser
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from apps.permissions.models import DataScope
from apps.permissions.services import get_user_data_scope
from django.db.models import Q


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


def filter_lifecycle_reviews(user, queryset):
    queryset = queryset.filter(tenant=user.tenant)
    if user.is_superuser:
        return queryset
    scopes = get_user_data_scope(user)
    if any(scope["scope_type"] == DataScope.ScopeType.ALL for scope in scopes):
        return queryset
    allowed = Q(pk__in=[])
    for scope in scopes:
        if scope["scope_type"] != DataScope.ScopeType.CUSTOM:
            continue
        config = scope.get("config") or {}
        sku_ids = config.get("sku_ids", [])
        spu_ids = config.get("spu_ids", [])
        if not sku_ids and not spu_ids:
            continue
        scope_filter = Q()
        if sku_ids:
            scope_filter &= Q(sku_id__in=sku_ids)
        if spu_ids:
            scope_filter &= Q(spu_id__in=spu_ids)
        allowed |= scope_filter
    return queryset.filter(allowed)
