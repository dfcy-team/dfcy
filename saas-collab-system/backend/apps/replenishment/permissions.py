from django.db.models import Q
from rest_framework.permissions import BasePermission

from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope
from apps.permissions.services import check_user_permission, get_user_data_scope


class ReplenishmentActionPermission(BasePermission):
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


class IsReplenishmentViewer(ReplenishmentActionPermission):
    permission_code = "replenishment.view"


class IsReplenishmentEvaluator(ReplenishmentActionPermission):
    permission_code = "replenishment.evaluate"


class IsReplenishmentReviewer(ReplenishmentActionPermission):
    permission_code = "replenishment.review"


def filter_recommendations(user, queryset):
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
