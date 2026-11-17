from apps.commerce.country_decisions import *
from apps.commerce.country_decisions import _history_spans, _complete_history, _bundle_components_for_orders

def reference_sales_windows(actor, country, sku_ids, windows, *, end_date=None, platform_type=None, permission_cache=None):
    requested_skus = {row.pk: row.product_type for row in ProductSKU.objects.filter(
        tenant_id=actor.tenant_id, pk__in=sku_ids).select_related('spu')}
    requested_ids = set(requested_skus)
    stores = filter_sales_queryset(actor, SALES,
        StoreMaster.objects.filter(tenant_id=actor.tenant_id, country_code__iexact=country.country_code, status='active'),
        {'store_ids': 'id', 'platforms': 'platform__platform_type', 'regions': 'country_code'},
        permission_cache=permission_cache)
    if platform_type:
        stores = stores.filter(platform__platform_type__iexact=platform_type, platform__status='active')
    aggregate = {days: {'days': days, 'start_date': None, 'end_date': None, 'units_by_sku': defaultdict(int),
        'direct_sales_by_sku': defaultdict(int), 'bundle_sales_by_sku': defaultdict(int),
        'amounts': defaultdict(lambda: defaultdict(Decimal)), 'refund_units': defaultdict(int),
        'refund_amounts': defaultdict(lambda: defaultdict(Decimal)), 'coverage_complete': True,
        'source_run_ids': set(), 'unmapped': False, 'bundle_composition_unverified': False,
        'stores': [], 'issues': []} for days in windows}
    store_count = 0
    for store in stores:
        store_count += 1
        try:
            zone = ZoneInfo(store.timezone)
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            for value in aggregate.values():
                value['coverage_complete'] = False
                value['issues'].append('invalid_store_timezone')
            continue
        local_today = timezone.now().astimezone(zone).date()
        end = end_date or local_today - timedelta(days=1)
        spans = _history_spans(store) if end < local_today else []
        for days, value in aggregate.items():
            start = end - timedelta(days=days - 1)
            lower = datetime.combine(start, time.min, tzinfo=zone)
            upper = datetime.combine(end + timedelta(days=1), time.min, tzinfo=zone)
            value['start_date'] = min(value['start_date'] or start, start)
            value['end_date'] = max(value['end_date'] or end, end)
            value['stores'].append({'id': store.pk, 'timezone': store.timezone,
                                    'start_date': str(start), 'end_date': str(end)})
            complete = end < local_today and _complete_history(store, lower, upper, spans=spans)
            value['coverage_complete'] &= complete
            if end >= local_today:
                value['issues'].append('unfinished_store_day')
                continue
            orders = SalesOrder.objects.filter(tenant_id=actor.tenant_id, store=store,
                created_at_utc__gte=lower, created_at_utc__lt=upper, paid_at_utc__isnull=False,
                paid_at_utc__lt=upper, normalized_status__in=['confirmed', 'fulfilled', 'completed'],
                source_run__status='success', source_run__failed_count=0)
            source = SalesOrderItem.objects.filter(sales_order__in=orders)
            value['unmapped'] |= source.filter(internal_sku__isnull=True).exists()
            ordinary_ids = [pk for pk, product_type in requested_skus.items() if product_type != 'bundle']
            bundle_ids = [pk for pk, product_type in requested_skus.items() if product_type == 'bundle']
            rows = source.filter(internal_sku_id__in=ordinary_ids).exclude(
                Q(bundle_snapshot__isnull=False) | Q(internal_sku__product_type='bundle')).values('internal_sku_id', 'currency')
            for row in rows.annotate(units=Sum('quantity'), amount=Sum('line_total_amount')):
                value['direct_sales_by_sku'][row['internal_sku_id']] += row['units']
                value['amounts'][row['internal_sku_id']][row['currency']] += row['amount']
            if bundle_ids:
                own_bundle_rows = source.filter(internal_sku_id__in=bundle_ids).values('internal_sku_id', 'currency')
                for row in own_bundle_rows.annotate(units=Sum('quantity'), amount=Sum('line_total_amount')):
                    value['direct_sales_by_sku'][row['internal_sku_id']] += row['units']
                    value['amounts'][row['internal_sku_id']][row['currency']] += row['amount']
            bundle_items = source.filter(Q(internal_sku__product_type='bundle') |
                Q(bundle_snapshot__isnull=False)).values(
                    'id', 'sales_order__tenant_id', 'sales_order__created_at_utc', 'internal_sku_id', 'quantity'
                ).iterator(chunk_size=500)
            while item_chunk := list(islice(bundle_items, 500)):
                bundle_demand, unverified = _bundle_components_for_orders(actor, item_chunk, requested_ids)
                value['bundle_composition_unverified'] |= unverified
                if unverified:
                    value['issues'].append('bundle_composition_unverified')
                for sku_id, units in bundle_demand.items():
                    value['bundle_sales_by_sku'][sku_id] += units
            for sku_id in requested_ids:
                direct_units = value['direct_sales_by_sku'][sku_id]
                bundle_units = value['bundle_sales_by_sku'][sku_id] if requested_skus[sku_id] != 'bundle' else 0
                value['units_by_sku'][sku_id] = direct_units + bundle_units
            value['source_run_ids'].update(orders.values_list('source_run_id', flat=True).distinct())
            refunds = RefundReturn.objects.filter(tenant_id=actor.tenant_id, store=store,
                requested_at_utc__gte=lower, requested_at_utc__lt=upper,
                normalized_status='completed', source_run__status='success', source_run__failed_count=0)
            for row in RefundReturnItem.objects.filter(refund_return__in=refunds,
                    internal_sku_id__in=sku_ids).values('internal_sku_id', 'currency').annotate(
                        units=Sum('quantity'), amount=Sum('refund_amount')):
                value['refund_units'][row['internal_sku_id']] += row['units']
                value['refund_amounts'][row['internal_sku_id']][row['currency']] += row['amount']
    if not store_count:
        for value in aggregate.values():
            value['coverage_complete'] = False
            value['issues'].append('no_authorized_sales_store')
    return aggregate
