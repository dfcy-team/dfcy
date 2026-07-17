from django.db.models import Q
from rest_framework.exceptions import PermissionDenied

from .models import DataScope
from .services import get_permission_data_scopes


def _configured_ids(scope, key):
    values = (scope.get("config") or {}).get(key, [])
    if not isinstance(values, list):
        return set()
    return {int(value) for value in values if str(value).isdigit()}


def _scopes(user, permission_code):
    return get_permission_data_scopes(user, permission_code)


def _has_all(scopes):
    return any(scope["scope_type"] == DataScope.ScopeType.ALL for scope in scopes)


def require_create_scope(user, permission_code, *, allow_own=False):
    scopes = _scopes(user, permission_code)
    if _has_all(scopes):
        return
    if allow_own and any(scope["scope_type"] == DataScope.ScopeType.OWN for scope in scopes):
        return
    raise PermissionDenied("Creating this resource requires all-tenant or supported own data scope.")


def filter_product_research(user, queryset, permission_code):
    scopes = _scopes(user, permission_code)
    if _has_all(scopes):
        return queryset
    allowed = Q(pk__in=[])
    for scope in scopes:
        if scope["scope_type"] == DataScope.ScopeType.OWN:
            allowed |= Q(created_by=user)
        elif scope["scope_type"] == DataScope.ScopeType.CUSTOM:
            ids = _configured_ids(scope, "research_ids")
            platforms = (scope.get("config") or {}).get("platforms", [])
            if ids:
                allowed |= Q(pk__in=ids)
            if isinstance(platforms, list) and platforms:
                allowed |= Q(platform__in=[str(value) for value in platforms])
    return queryset.filter(allowed).distinct()


def filter_product_spus(user, queryset, permission_code):
    scopes = _scopes(user, permission_code)
    if _has_all(scopes):
        return queryset
    ids = set()
    for scope in scopes:
        if scope["scope_type"] == DataScope.ScopeType.CUSTOM:
            ids.update(_configured_ids(scope, "spu_ids"))
    return queryset.filter(pk__in=ids)


def filter_product_skus(user, queryset, permission_code):
    scopes = _scopes(user, permission_code)
    if _has_all(scopes):
        return queryset
    sku_ids = set()
    spu_ids = set()
    for scope in scopes:
        if scope["scope_type"] == DataScope.ScopeType.CUSTOM:
            sku_ids.update(_configured_ids(scope, "sku_ids"))
            spu_ids.update(_configured_ids(scope, "spu_ids"))
    return queryset.filter(Q(pk__in=sku_ids) | Q(spu_id__in=spu_ids)).distinct()


def filter_purchase_orders(user, queryset, permission_code):
    scopes = _scopes(user, permission_code)
    if _has_all(scopes):
        return queryset
    allowed = Q(pk__in=[])
    for scope in scopes:
        if scope["scope_type"] == DataScope.ScopeType.OWN:
            allowed |= Q(created_by=user)
        elif scope["scope_type"] == DataScope.ScopeType.CUSTOM:
            order_ids = _configured_ids(scope, "purchase_order_ids")
            supplier_ids = _configured_ids(scope, "supplier_ids")
            if order_ids:
                allowed |= Q(pk__in=order_ids)
            if supplier_ids:
                allowed |= Q(supplier_id__in=supplier_ids)
    return queryset.filter(allowed).distinct()
