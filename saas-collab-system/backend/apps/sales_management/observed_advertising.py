"""Read-only estimates from observed advertising, with explicit comparison scope."""
from decimal import Decimal

from django.db.models import Count, F, Q, Sum

from apps.permissions.services import check_user_permission
from apps.reports.advertising_dataset import _metric, advertising_queryset
from apps.sales_management.views import _decimal_string


def attach_operations_advertising(request, params, orders, period, previous, groups, rows):
    targets = [*groups, *rows]
    if not check_user_permission(request.user, 'analytics.view', cache=getattr(request, '_permission_resolution_cache', None)):
        return
    if params['view'] == 'products':
        for row in targets:
            row['ad_reason'] = '商品行金额不能与整店广告消耗直接计算 ROI；请查看店铺经营表现。'
        return
    sales = orders.exclude(normalized_status='cancelled').filter(platform__platform_type='shopee')
    aggregates = list(sales.order_by().values('store_id', 'currency').annotate(
        current=Sum('order_total_amount', filter=period),
        previous=Sum('order_total_amount', filter=previous),
        conflicts=Count('pk', filter=~Q(region='') & ~Q(region__iexact=F('store__country_code'))),
    ))
    filters = {'date_from': params['previous_from'], 'date_to': params['date_to'], 'platform': 'shopee'}
    if params['currency']:
        filters['currency'] = params['currency']
    # Both tenant/sales row scope and analytics scope are applied before aggregation.
    facts = advertising_queryset(request, filters, 'analytics.view').filter(
        store_id__in=sales.order_by().values('store_id'), store__tenant=request.user.tenant,
        store__platform__platform_type='shopee',
    )
    current_days = Q(report_date__gte=params['date_from'], report_date__lte=params['date_to'])
    previous_days = Q(report_date__gte=params['previous_from'], report_date__lte=params['previous_to'])
    expenses = {(r['store_id'], r['currency']): r for r in facts.values('store_id', 'currency').annotate(
        current=Sum(_metric('expense'), filter=current_days),
        previous=Sum(_metric('expense'), filter=previous_days),
    )}
    pairs = {}
    totals = {}
    for sale in aggregates:
        key = (sale['store_id'], sale['currency'])
        expense = expenses.get(key)
        if sale['conflicts'] or expense is None:
            continue
        pair = {}
        for name in ('current', 'previous'):
            amount, spend = sale[name], expense[name]
            if amount is not None and spend is not None:
                pair[name] = (Decimal(amount), Decimal(spend))
                total = totals.setdefault(sale['currency'], {}).setdefault(name, [Decimal(0), Decimal(0), 0])
                total[0] += amount
                total[1] += spend
                total[2] += 1
        pairs[key] = pair

    def apply(target, values, aggregate=False):
        target['ad_status'] = 'unavailable'
        target['ad_reason'] = '没有可比的已拉取广告数据，或店铺国家存在冲突；其他销售数据正常展示。'
        cur, prev = values.get('current'), values.get('previous')
        if cur is None:
            return
        target['ad_spend'] = _decimal_string(cur[1])
        target['ad_sales_amount'] = _decimal_string(cur[0])
        target['roi'] = _decimal_string(cur[0] / cur[1]) if cur[1] > 0 else None
        target['ad_status'] = 'provisional'
        target['ad_reason'] = '暂估 ROI，按目前已拉取数据计算；部分数据可能尚未拉取，后续同步可能调整。'
        if aggregate:
            target['ad_reason'] += ' 仅统计同店铺、同币种具有广告观测值的销售范围。'
            target['ad_observed_store_count'] = cur[2]
        if cur[1] == 0:
            target['ad_reason'] += ' 已观测广告消耗为零，ROI 无法计算。'
        if prev is not None and prev[1] > 0 and cur[1] > 0:
            target['roi_delta'] = _decimal_string(cur[0] / cur[1] - prev[0] / prev[1])
    for group in groups:
        apply(group, totals.get(group['currency'], {}), True)
    for row in rows:
        apply(row, pairs.get((row['store_id'], row['currency']), {}))
