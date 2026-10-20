"""Paginated, read-only operating-order reference candidates."""
from decimal import ROUND_CEILING
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers
from rest_framework.response import Response

from apps.commerce import country_decisions
from apps.supply_chain.api import validated
from apps.supply_chain.dates import business_date
from . import operating
from .operating_api import OperatingAPI, PreviewInput

UNKNOWN_SALES_ISSUES = {
    'no_sales_facts', 'no_authorized_sales_store', 'invalid_store_timezone', 'unfinished_store_day',
}


class ReferenceInput(PreviewInput):
    source_kind = serializers.ChoiceField(choices=('cycle', 'season'))
    analysis_mode = serializers.ChoiceField(choices=('country', 'platform'), default='country')
    platform_type = serializers.CharField(max_length=80, allow_blank=True, default='')
    search = serializers.CharField(max_length=160, allow_blank=True, default='')
    limit = serializers.IntegerField(min_value=1, max_value=20, default=20)
    offset = serializers.IntegerField(min_value=0, default=0)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.pop('sku_ids', None)


class OperatingReferences(OperatingAPI):
    """Calculate metrics only for the requested page; this creates no preview token."""

    def post(self, request):
        values = validated(ReferenceInput, request)
        operating._require(request.user, operating.MANAGE)
        operating._country(request.user, values['country_id'])
        country = country_decisions.country_for(request.user, values['country_id'])
        platform_options = country_decisions.sales_platform_options(request.user, country)
        available_platform_types = {row['platform_type'].casefold() for row in platform_options}
        selected_platform = values['platform_type'].strip()
        if values['analysis_mode'] == 'platform':
            if not selected_platform or selected_platform.casefold() not in available_platform_types:
                raise serializers.ValidationError({'platform_type': '所选平台不在当前国家的授权活跃店铺范围内。'})
            selected_platform = next(row['platform_type'] for row in platform_options
                                     if row['platform_type'].casefold() == selected_platform.casefold())
        edited_id = values.get('exclude_operating_order_id')
        if edited_id:
            edited = operating.order_for(request.user, edited_id)
            if edited.status != 'draft' or edited.country_id != country.pk:
                raise serializers.ValidationError('仅编辑同一国家且有权维护的草稿时可排除本单预留量。')

        start, end = values['sales_start'], values['sales_end']
        if start > end or end >= business_date() or (end - start).days > 365:
            raise serializers.ValidationError('销量周期须为已完成日期范围，最多 366 天。')

        candidates = country_decisions.skus_for(request.user, country).filter(
            is_active=True, spu__product_type='standard').select_related('spu__category_node')
        term = values['search'].strip()
        if term:
            candidates = candidates.filter(Q(sku_code__icontains=term) |
                Q(legacy_sku_code__icontains=term) | Q(product_name__icontains=term))
        candidates = candidates.order_by('sku_code', 'pk')
        count = candidates.count()
        skus = list(candidates[values['offset']:values['offset'] + values['limit']])

        days = int(values.get('sales_window_days') or (end - start).days + 1)
        target_days = values.get('target_days') or max(1, int((values['target_stock_sales_ratio'] * days).to_integral_value(rounding=ROUND_CEILING)))
        ratio = None if values.get('sales_window_days') else values['target_stock_sales_ratio']
        rows = country_decisions.decision_rows(request.user, country, skus,
            target_days=target_days, window_days=days,
            end_date=None if values.get('sales_window_days') else end,
            ratio=ratio, include_in_transit=values['include_in_transit'],
            windows=(days,), exclude_order_id=edited_id) if skus else []

        lines = []
        platform_sales = {}
        if values['analysis_mode'] == 'platform' and skus:
            platform_sales = country_decisions.sales_windows(request.user, country,
                [sku.pk for sku in skus], (days,),
                end_date=None if values.get('sales_window_days') else end,
                platform_type=selected_platform)
        for row in rows:
            observed = row['sales_windows'][0]
            country_unknown = bool(UNKNOWN_SALES_ISSUES.intersection(row['issues']))
            line = {**row, 'sales_quantity': None if country_unknown else observed['units'],
                'daily_sales': None if country_unknown else row.get('daily_sales'),
                'in_transit_stock': str(row['pipeline']['effective_incoming']) if row['pipeline']['authorized'] else None,
                'source_kind': values['source_kind'],
                'issues': sorted(set(row['issues'] + ['refunds_not_deducted']))}
            if country_unknown:
                line['sales_windows'] = [{**window, 'units': None, 'daily_units': None}
                                         for window in row['sales_windows']]
            if values['analysis_mode'] == 'platform':
                selected = platform_sales[days]
                platform_quantity = selected['units_by_sku'][row['sku_id']]
                platform_issues = list(selected['issues'])
                if selected['unmapped']:
                    platform_issues.append('unmapped_sales_lines')
                if not selected['coverage_complete']:
                    platform_issues.append('collection_coverage_unproven')
                platform_unknown = (bool(UNKNOWN_SALES_ISSUES.intersection(platform_issues)) or
                                    (platform_quantity == 0 and not selected['coverage_complete']))
                country_quantity = observed['units']
                platform_complete = selected['coverage_complete'] and not selected['unmapped']
                country_blocked = country_unknown or not observed['coverage_complete'] or 'unmapped_sales_lines' in row['issues']
                share_comparable = (country_quantity > 0 and platform_quantity <= country_quantity and
                                    platform_complete and not country_blocked)
                complete = share_comparable
                if platform_quantity > country_quantity:
                    platform_issues.append('platform_sales_exceeds_country_total')
                share = (str((Decimal(platform_quantity) / Decimal(country_quantity)).quantize(Decimal('0.0001')))
                         if share_comparable else None)
                if not observed['coverage_complete']:
                    platform_issues.append('country_sales_coverage_unproven')
                line['platform_analysis'] = {
                    'platform_type': selected_platform,
                    'sales_quantity': None if platform_unknown else platform_quantity,
                    'daily_sales': None if platform_unknown else f'{Decimal(platform_quantity) / days:.4f}',
                    'country_sales_share': share,
                    'complete': complete,
                    'issues': sorted(set(platform_issues)),
                }
            lines.append(line)

        notice = (country_decisions.NOTICE + ' 当前国家授权普通商品，缺数据列待核对。周期订货与季节订货共用所选历史销量区间的库销比计算；'
                  '季节参考期间由操作人员手动选择，当前不提供独立季节预测模型。')
        return Response({'data': {
            'lines': lines, 'count': count, 'limit': values['limit'], 'offset': values['offset'],
            'candidate_scope': 'authorized_standard_products',
            'analysis_mode': values['analysis_mode'], 'platform_options': platform_options,
            'generated_at': timezone.now().isoformat(),
            'formula': 'max(0, ceil(周期商品销量 × 目标库销比 - WMS可用库存 - 按期有效到货 - 开放运营需求))',
            'notice': notice,
        }})
