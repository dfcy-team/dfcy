from collections import defaultdict
from hashlib import sha256
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.cache import cache
from django.db.models import Count, Max, Q, Sum
from django.utils import timezone

from apps.commerce.models import RefundReturn, RefundReturnItem, SalesOrder, SalesOrderItem
from apps.integrations.models import HistorySyncSegment
from apps.masterdata.models import StoreMaster
from apps.products.models import ProductSKU
from apps.sales_management.inventory_queries import prefer_sales_order_time, eligible_inventory_orders
from apps.sales_management.scopes import filter_sales_queryset


def _bundle_product_source(source):
    """Select bundle order items without an unbounded SKU join."""
    bundle_ids = list(ProductSKU.objects.filter(product_type='bundle').order_by()
                      .values_list('pk', flat=True)[:2001])
    if len(bundle_ids) > 2000:
        # Keep the historical FK predicate when a literal IN list would be large.
        return source.filter(internal_sku__product_type='bundle')
    return source.filter(internal_sku_id__in=bundle_ids)


def sales_windows(actor, country, sku_ids, windows, *, end_date=None,
                  platform_type=None, permission_cache=None, inventory_only=False):
    from . import country_decisions as domain

    requested_skus = dict(ProductSKU.objects.filter(
        tenant_id=actor.tenant_id, pk__in=sku_ids).values_list('pk', 'product_type'))
    requested_ids = set(requested_skus)
    ordinary_ids = [pk for pk, kind in requested_skus.items() if kind != 'bundle']
    bundle_ids = [pk for pk, kind in requested_skus.items() if kind == 'bundle']
    stores = filter_sales_queryset(actor, domain.SALES, StoreMaster.objects.filter(
        tenant_id=actor.tenant_id, country_code__iexact=country.country_code, status='active'),
        {'store_ids': 'id', 'platforms': 'platform__platform_type', 'regions': 'country_code'},
        permission_cache=permission_cache)
    if platform_type:
        stores = stores.filter(platform__platform_type__iexact=platform_type, platform__status='active')
    stores = list(stores)
    cache_key = None
    if inventory_only and tuple(windows) == (30,):
        now = timezone.now()
        store_scope = []
        for store in stores:
            try:
                local_date = now.astimezone(ZoneInfo(store.timezone)).date().isoformat()
            except (ZoneInfoNotFoundError, ValueError, TypeError):
                local_date = None
            store_scope.append((store.pk, store.timezone, local_date))
        identity = (
            actor.tenant_id, actor.pk, country.country_code.upper(), platform_type,
            end_date, sorted(store_scope), sorted(requested_skus.items()),
        )
        digest = sha256(repr(identity).encode("utf-8")).hexdigest()
        cache_key = f"warehouse-inventory-sales:v1:{digest}"
        try:
            cached = cache.get(cache_key)
        except Exception:
            cached = None
        if cached is not None:
            return {30: cached}
    aggregate = {days: {
        'days': days, 'start_date': None, 'end_date': None,
        'units_by_sku': defaultdict(int), 'direct_sales_by_sku': defaultdict(int),
        'bundle_sales_by_sku': defaultdict(int),
        'amounts': defaultdict(lambda: defaultdict(Decimal)),
        'refund_units': defaultdict(int), 'refund_amounts': defaultdict(lambda: defaultdict(Decimal)),
        'coverage_complete': True, 'source_run_ids': set(), 'unmapped': False,
        'bundle_composition_unverified': False, 'stores': [], 'issues': [],
    } for days in windows}
    if not aggregate:
        return aggregate

    spans = defaultdict(list)
    segments = HistorySyncSegment.objects.filter(
        batch__tenant_id=actor.tenant_id, sync_job__resource_type='sales_order',
        sync_job__store_authorization__store_id__in=[store.pk for store in stores],
        status='success', runs__status='success', runs__failed_count=0,
    ).values_list('sync_job__store_authorization__store_id', 'scope').distinct()
    for store_id, scope in segments:
        if scope.get('time_basis') != 'created':
            continue
        try:
            lower, upper = int(scope['time_from']), int(scope['time_to']) + 1
            if lower < upper:
                spans[store_id].append((lower, upper))
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    for values in spans.values():
        values.sort()

    groups = defaultdict(list)
    for store in stores:
        try:
            zone = ZoneInfo(store.timezone)
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            for value in aggregate.values():
                value['coverage_complete'] = False
                value['issues'].append('invalid_store_timezone')
            continue
        local_today = timezone.now().astimezone(zone).date()
        end = end_date or local_today - timedelta(days=1)
        upper = datetime.combine(end + timedelta(days=1), time.min, tzinfo=zone)
        for days, value in aggregate.items():
            start = end - timedelta(days=days - 1)
            lower = datetime.combine(start, time.min, tzinfo=zone)
            value['start_date'] = min(value['start_date'] or start, start)
            value['end_date'] = max(value['end_date'] or end, end)
            value['stores'].append({'id': store.pk, 'timezone': store.timezone,
                                    'start_date': str(start), 'end_date': str(end)})
            value['coverage_complete'] &= end < local_today and domain._complete_history(
                store, lower, upper, spans=spans[store.pk])
            if end >= local_today:
                value['issues'].append('unfinished_store_day')
        if end < local_today:
            groups[(zone, end, upper)].append(store.pk)

    for (zone, end, upper), store_ids in groups.items():
        lower_bounds = {days: datetime.combine(end - timedelta(days=days - 1), time.min, tzinfo=zone)
                        for days in aggregate}
        earliest = min(lower_bounds.values())
        orders = prefer_sales_order_time(SalesOrder.objects.filter(
            tenant_id=actor.tenant_id, store_id__in=store_ids,
            created_at_utc__gte=earliest, created_at_utc__lt=upper,
            paid_at_utc__isnull=False, paid_at_utc__lt=upper,
            normalized_status__in=['confirmed', 'fulfilled', 'completed'],
            source_run__status='success', source_run__failed_count=0))
        with eligible_inventory_orders(orders) as eligible:
            source = SalesOrderItem.objects.filter(sales_order_id__in=eligible)
            conditions = {days: Q(sales_order__created_at_utc__gte=lower) for days, lower in lower_bounds.items()}
            missing = source.filter(internal_sku_id__isnull=True).aggregate(
                **{f'w{days}': Count('pk', filter=condition) for days, condition in conditions.items()})
            metrics = {}
            for days, condition in conditions.items():
                aggregate[days]['unmapped'] |= bool(missing[f'w{days}'])
                metrics[f'units_{days}'] = Sum('quantity', filter=condition)
                if not inventory_only:
                    metrics[f'amount_{days}'] = Sum('line_total_amount', filter=condition)
            direct_sources = []
            if ordinary_ids:
                direct_sources.append(source.filter(internal_sku_id__in=ordinary_ids).exclude(
                    Q(bundle_snapshot__isnull=False) | Q(internal_sku__product_type='bundle')))
            if bundle_ids:
                direct_sources.append(source.filter(internal_sku_id__in=bundle_ids))
            for direct in direct_sources:
                for row in direct.order_by().values('internal_sku_id', 'currency').annotate(**metrics):
                    for days, value in aggregate.items():
                        if row[f'units_{days}'] is not None:
                            value['direct_sales_by_sku'][row['internal_sku_id']] += row[f'units_{days}']
                            if not inventory_only:
                                value['amounts'][row['internal_sku_id']][row['currency']] += row[f'amount_{days}']

            # Resolve each of the two supported bundle representations through its
            # selective relation, then deduplicate immutable order-item identities.
            bundle_sources = [
                _bundle_product_source(source),
                source.filter(bundle_snapshot__isnull=False),
            ]
            pending_bundles = defaultdict(list)
            seen_bundle_items = set()

            def merge_bundles(membership, members):
                demand, unverified = domain._bundle_components_for_orders(actor, members, requested_ids)
                for days in membership:
                    value = aggregate[days]
                    value['bundle_composition_unverified'] |= unverified
                    if unverified:
                        value['issues'].append('bundle_composition_unverified')
                    for sku_id, units in demand.items():
                        value['bundle_sales_by_sku'][sku_id] += units

            for bundle_source in bundle_sources:
                items = bundle_source.order_by().values(
                    'id', 'sales_order__tenant_id', 'sales_order__created_at_utc', 'internal_sku_id', 'quantity'
                ).iterator(chunk_size=1000)
                for item in items:
                    if item['id'] in seen_bundle_items:
                        continue
                    seen_bundle_items.add(item['id'])
                    membership = tuple(days for days, lower in lower_bounds.items()
                                       if item['sales_order__created_at_utc'] >= lower)
                    pending = pending_bundles[membership]
                    pending.append(item)
                    if len(pending) == 500:
                        merge_bundles(membership, pending)
                        pending.clear()
            for membership, members in pending_bundles.items():
                if members:
                    merge_bundles(membership, members)
            if not inventory_only:
                for row in SalesOrder.objects.filter(pk__in=eligible).order_by().values('source_run_id').annotate(last_created=Max('created_at_utc')):
                    for days, lower in lower_bounds.items():
                        if row['last_created'] >= lower:
                            aggregate[days]['source_run_ids'].add(row['source_run_id'])

        if not inventory_only:
            refunds = RefundReturn.objects.filter(
                tenant_id=actor.tenant_id, store_id__in=store_ids,
                requested_at_utc__gte=earliest, requested_at_utc__lt=upper,
                normalized_status='completed', source_run__status='success', source_run__failed_count=0)
            refund_metrics = {}
            for days, lower in lower_bounds.items():
                condition = Q(refund_return__requested_at_utc__gte=lower)
                refund_metrics[f'units_{days}'] = Sum('quantity', filter=condition)
                refund_metrics[f'amount_{days}'] = Sum('refund_amount', filter=condition)
            for row in RefundReturnItem.objects.filter(
                refund_return_id__in=refunds.values('pk'), internal_sku_id__in=sku_ids
            ).order_by().values('internal_sku_id', 'currency').annotate(**refund_metrics):
                for days, value in aggregate.items():
                    if row[f'units_{days}'] is not None:
                        value['refund_units'][row['internal_sku_id']] += row[f'units_{days}']
                        value['refund_amounts'][row['internal_sku_id']][row['currency']] += row[f'amount_{days}']

    for value in aggregate.values():
        for sku_id in requested_ids if groups else ():
            value['units_by_sku'][sku_id] = value['direct_sales_by_sku'][sku_id]
            if requested_skus[sku_id] != 'bundle':
                value['units_by_sku'][sku_id] += value['bundle_sales_by_sku'][sku_id]
        if not stores:
            value['coverage_complete'] = False
            value['issues'].append('no_authorized_sales_store')
    if cache_key:
        value = aggregate[30]
        result = {key: dict(item) if isinstance(item, defaultdict) else item
                  for key, item in value.items()}
        try:
            cache.set(cache_key, result, timeout=60)
        except Exception:
            pass
    return aggregate
