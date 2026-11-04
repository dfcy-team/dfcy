"""Store-aware finance scope, without widening legacy platform-only endpoints."""
from django.db.models import Q
from rest_framework.exceptions import PermissionDenied

from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.permissions.models import DataScope
from apps.permissions.services import get_permission_data_scopes


def scoped(user, queryset, permission='finance.view', *, records=False, money_currency=None):
    scopes = get_permission_data_scopes(user, permission)
    queryset = queryset.filter(tenant=user.tenant)
    if any(scope['scope_type'] == DataScope.ScopeType.ALL for scope in scopes):
        return queryset
    prefix = 'store__' if records else ''
    fields = {'store_ids': prefix + 'pk', 'platform_ids': prefix + 'platform_id',
              'platforms': prefix + 'platform__platform_type', 'regions': prefix + 'country_code'}
    allowed = Q(pk__in=[])
    for scope in scopes:
        config = scope.get('config') or {}
        if scope['scope_type'] != DataScope.ScopeType.CUSTOM or not config or set(config) - (set(fields) | {'currencies'}):
            continue
        branch = Q()
        for key, values in config.items():
            if not isinstance(values, list) or not values:
                raise PermissionDenied('财务店铺范围配置无效。')
            if key in {'store_ids', 'platform_ids'}:
                model = StoreMaster if key == 'store_ids' else PlatformMaster
                if any(type(v) is not int or v <= 0 for v in values) or model.objects.filter(tenant=user.tenant, pk__in=set(values)).count() != len(set(values)):
                    raise PermissionDenied('财务店铺范围包含无效或跨租户标识。')
            if key == 'currencies':
                if records:
                    branch &= Q(currency__in=values)
                elif money_currency is not None and money_currency not in values:
                    branch &= Q(pk__in=[])
            else:
                branch &= Q(**{fields[key] + '__in': values})
        allowed |= branch
    return queryset.filter(allowed).distinct()


def scoped_money_stores(user, queryset, permission, currency):
    return scoped(user, queryset, permission, money_currency=currency)
