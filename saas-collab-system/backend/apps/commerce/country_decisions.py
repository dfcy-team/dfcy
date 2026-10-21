"""Country/SKU observations shared by inventory decisions and operating-order previews.

Missing source fields remain unknown. WMS transit is observational and is never
added to the supply-chain projection. All monetary totals retain their currency.
"""
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone as dt_timezone
from decimal import Decimal, ROUND_CEILING
from fractions import Fraction
from itertools import islice
from math import ceil
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, NotFound

from apps.masterdata.models import CountrySiteMaster, StoreMaster, WarehouseMaster
from apps.products.models import ProductSKU
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from apps.sales_management.scopes import filter_inventory_queryset, filter_sales_queryset, _custom_scope_configs
from apps.supply_chain.dates import business_date
from apps.supply_chain.supplier_products import product_details
from apps.integrations.models import HistorySyncSegment, SyncJob, SyncRun
from .models import InventorySnapshot, SalesOrder, SalesOrderItem, RefundReturn, RefundReturnItem
from .supply_pipeline import pipeline_for

INVENTORY = 'sales_management.view'
SALES = 'sales_management.skus.view'
NOTICE = ('可用库存来自仓库 API 最新快照，已锁数量不再次扣减。销量为店铺当地已完成自然日的已付款有效订单商品件数；'
          '组合商品按订单不可变组成快照折算为组件需求件数；金额与退款金额只按原订单商品行统计，不向组合组件分摊。'
          '已采集的已完成退款按申请日单列，不扣减销量；退款采集覆盖可能与销量不同。WMS 在途仅观察，不与供应阶段相加。'
          '超采、追加数量是发货数量的子集；已对账收货为累计事实，不是当前库存。建议须人工复核。')


def permission_signature(actor, permission_cache=None):
    from .supply_pipeline import SUMMARY_PERMISSION
    from apps.supply_chain.services import request_hash
    states = []
    for code, resource in ((INVENTORY, 'commerce.inventory'), (SALES, 'sales_management.sales'),
                           (SUMMARY_PERMISSION, 'sales_management.supply_summary')):
        scopes = get_permission_data_scopes(actor, code, resource_code=resource, cache=permission_cache)
        states.append({'permission': code, 'allowed': check_user_permission(actor, code, cache=permission_cache),
            'scopes': sorted([{'scope_type': s['scope_type'], 'config': s.get('config') or {}} for s in scopes],
                             key=lambda s: request_hash(s))})
    return request_hash(states)


def require_metrics(actor, permission_cache=None):
    if (not actor.is_active or actor.user_type != 'internal' or
        not all(check_user_permission(actor, code, cache=permission_cache) for code in (INVENTORY, SALES))):
        raise PermissionDenied('经营汇总需要内部账号的库存查看和 SKU 销售查看权限。')
    for code, resource in ((INVENTORY, 'commerce.inventory'), (SALES, 'sales_management.sales')):
        if not actor.is_superuser and not get_permission_data_scopes(actor, code, resource_code=resource, cache=permission_cache):
            raise PermissionDenied('缺少经营数据范围授权。')


def _config_countries(actor, config):
    codes = None
    if config.get('regions'):
        codes = {str(value).upper() for value in config['regions']}
    if config.get('store_ids'):
        values = [str(value) for value in config['store_ids']]
        stores = StoreMaster.objects.filter(tenant_id=actor.tenant_id).filter(
            Q(pk__in=[int(v) for v in values if v.isdigit()]) | Q(code__in=values))
        selected = {code.upper() for code in stores.values_list('country_code', flat=True)}
        codes = selected if codes is None else codes & selected
    if config.get('warehouse_ids'):
        selected = {code.upper() for code in WarehouseMaster.objects.filter(tenant_id=actor.tenant_id,
            pk__in=config['warehouse_ids']).values_list('country_code', flat=True)}
        codes = selected if codes is None else codes & selected
    if config.get('platforms') and 'jifeng_wms' not in config['platforms']:
        return set()
    return codes


def countries_for(actor, permission_cache=None):
    require_metrics(actor, permission_cache)
    rows = CountrySiteMaster.objects.filter(tenant_id=actor.tenant_id, status='active')
    configs = _custom_scope_configs(actor, INVENTORY, permission_cache, resource_code='commerce.inventory')
    if configs is not None:
        codes = set()
        for config in configs:
            values = _config_countries(actor, config)
            if values is None and set(config) & {'sku_ids', 'spu_ids'}:
                return rows
            codes.update(values or [])
        rows = rows.filter(country_code__in=codes)
    return rows.order_by('country_code', 'pk')


def country_for(actor, pk, permission_cache=None):
    country = countries_for(actor, permission_cache).filter(pk=pk).first()
    if not country:
        raise NotFound('国家不存在或不在库存数据授权范围内。')
    return country


def skus_for(actor, country, permission_cache=None):
    rows = ProductSKU.objects.filter(tenant_id=actor.tenant_id, is_active=True)
    configs = _custom_scope_configs(actor, INVENTORY, permission_cache, resource_code='commerce.inventory')
    if configs is None:
        return rows
    allowed = Q(pk__in=[])
    for config in configs:
        codes = _config_countries(actor, config)
        if codes is not None and country.country_code.upper() not in codes:
            continue
        branch = Q(tenant_id=actor.tenant_id)
        constrained = False
        for key, field in (('sku_ids', 'pk'), ('spu_ids', 'spu_id')):
            if key in config:
                values = config[key]
                if not isinstance(values, list) or not values or any(type(v) is not int or v <= 0 for v in values):
                    raise PermissionDenied('库存商品范围配置无效。')
                branch &= Q(**{field + '__in': values})
                constrained = True
        if constrained or codes is not None:
            allowed |= branch
    return rows.filter(allowed)


def _warehouse_ids(actor, country, sku, *, branches):
    """None means all warehouses; a set preserves branch-wise product/warehouse scope."""
    if branches is None:
        return None
    ids = set()
    for config, codes in branches:
        if codes is not None and country.country_code.upper() not in codes:
            continue
        if 'sku_ids' in config and sku.pk not in config['sku_ids']:
            continue
        if 'spu_ids' in config and sku.spu_id not in config['spu_ids']:
            continue
        if not config.get('warehouse_ids'):
            if set(config) & {'sku_ids', 'spu_ids', 'regions', 'store_ids'}:
                return None
            continue
        ids.update(config['warehouse_ids'])
    return ids


def suggestion_quantity(sales, ratio, available, incoming=0, reserved_demand=0, *, target_days=None, window_days=None):
    # A rational ratio avoids ceil(7 * (8 / 7)) becoming 9 through Decimal division rounding.
    factor = Fraction(target_days, window_days) if target_days is not None else Fraction(Decimal(ratio))
    demand = (Fraction(Decimal(sales)) * factor - Fraction(Decimal(available))
              - Fraction(Decimal(incoming)) - Fraction(Decimal(reserved_demand)))
    return max(0, ceil(demand))


def _history_spans(store):
    """Load immutable successful coverage once for this store and request."""
    segments = HistorySyncSegment.objects.filter(batch__tenant_id=store.tenant_id,
        sync_job__resource_type='sales_order', sync_job__store_authorization__store=store,
        status='success', runs__status='success', runs__failed_count=0).values_list('scope', flat=True).distinct()
    spans = []
    for scope in segments:
        if scope.get('time_basis') != 'created':
            continue
        try:
            lower, upper = int(scope['time_from']), int(scope['time_to']) + 1
            if lower < upper:
                spans.append((lower, upper))
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return sorted(spans)


def _complete_history(store, start, end, *, spans=None):
    """Only immutable successful history segments can prove zero-sales coverage."""
    if spans is None:
        spans = _history_spans(store)
    cursor, stop = int(start.timestamp()), int(end.timestamp())
    for lower, upper in spans:
        if upper <= cursor:
            continue
        if lower > cursor:
            break
        cursor = max(cursor, upper)
        if cursor >= stop:
            return True
    return False


def _bundle_components_for_orders(actor, bundle_items, requested_ids):
    """Return requested component demand and whether any authorized bundle row is unverifiable."""
    if not bundle_items:
        return defaultdict(int), False
    from apps.commerce.models import SalesOrderBundleSnapshot

    item_ids = [row['id'] for row in bundle_items]
    snapshots = {snapshot.order_item_id: snapshot for snapshot in SalesOrderBundleSnapshot.objects.filter(
        tenant_id=actor.tenant_id, order_item_id__in=item_ids).select_related(
            'order_item__sales_order', 'bundle_version', 'bundle_version__bundle_sku',
            'bundle_version__bundle_sku__spu')}
    requested = set(requested_ids)
    item_quantities = {row['id']: row['quantity'] for row in bundle_items}
    component_rows = []
    unverified = False
    for item in bundle_items:
        snapshot = snapshots.get(item['id'])
        order_tenant = item['sales_order__tenant_id']
        bundle_id = item['internal_sku_id']
        if (not snapshot or snapshot.tenant_id != order_tenant or snapshot.order_item.sales_order.tenant_id != order_tenant or
                snapshot.bundle_version.tenant_id != order_tenant or snapshot.bundle_version.bundle_sku_id != bundle_id or
                snapshot.bundle_version.effective_at > item['sales_order__created_at_utc'] or
                snapshot.bundle_version.bundle_sku.tenant_id != order_tenant or
                snapshot.bundle_version.bundle_sku.spu.product_type != 'bundle'):
            unverified = True
            continue
        payload = snapshot.components_payload
        if not isinstance(payload, list) or not payload:
            unverified = True
            continue
        seen = set()
        valid = True
        for component in payload:
            if not isinstance(component, dict):
                valid = False
                break
            component_id, quantity = component.get('component_sku_id'), component.get('quantity')
            if (type(component_id) is not int or component_id <= 0 or type(quantity) is not int or quantity <= 0 or
                    component_id in seen or component_id == bundle_id):
                valid = False
                break
            seen.add(component_id)
            component_rows.append((item['id'], component_id, quantity))
        if not valid:
            # Discard any partial rows collected from this snapshot.
            component_rows = [row for row in component_rows if row[0] != item['id']]
            unverified = True
    component_ids = {row[1] for row in component_rows}
    from apps.products.models import ProductSKU
    valid_components = set(ProductSKU.objects.filter(tenant_id=actor.tenant_id, pk__in=component_ids,
        spu__product_type='standard').values_list('pk', flat=True))
    for _, component_id, _ in component_rows:
        if component_id not in valid_components:
            unverified = True
            break
    demand = defaultdict(int)
    for item_id, component_id, quantity in component_rows:
        if component_id in valid_components and component_id in requested:
            item_quantity = item_quantities[item_id]
            demand[component_id] += item_quantity * quantity
    return demand, unverified


def sales_windows(actor, country, sku_ids, windows, *, end_date=None, platform_type=None, permission_cache=None):
    requested_skus = {row.pk: row.spu.product_type for row in ProductSKU.objects.filter(
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
                Q(bundle_snapshot__isnull=False) | Q(internal_sku__spu__product_type='bundle')).values('internal_sku_id', 'currency')
            for row in rows.annotate(units=Sum('quantity'), amount=Sum('line_total_amount')):
                value['direct_sales_by_sku'][row['internal_sku_id']] += row['units']
                value['amounts'][row['internal_sku_id']][row['currency']] += row['amount']
            if bundle_ids:
                own_bundle_rows = source.filter(internal_sku_id__in=bundle_ids).values('internal_sku_id', 'currency')
                for row in own_bundle_rows.annotate(units=Sum('quantity'), amount=Sum('line_total_amount')):
                    value['direct_sales_by_sku'][row['internal_sku_id']] += row['units']
                    value['amounts'][row['internal_sku_id']][row['currency']] += row['amount']
            bundle_items = source.filter(Q(internal_sku__spu__product_type='bundle') |
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



def _country_inventory_source(actor, country, now):
    # Resolve stable dimension membership without joining each historical fact.
    # Preserve the original cross-table predicates exactly; no status filter.
    run_ids = list(SyncRun.objects.filter(
        sync_job__integration_config__platform='jifeng_wms',
        sync_job__resource_type='inventory_snapshot').values_list('pk', flat=True)[:2001])
    warehouse_ids = list(WarehouseMaster.objects.filter(
        country_code__iexact=country.country_code).values_list('pk', flat=True)[:1001])
    source = InventorySnapshot.objects.filter(tenant_id=actor.tenant_id, snapshot_at_utc__lte=now)
    if len(run_ids) > 2000 or len(warehouse_ids) > 1000:
        # No truncation: retain the original joined query for larger catalogs.
        return source.filter(warehouse__country_code__iexact=country.country_code,
            source_run__sync_job__integration_config__platform='jifeng_wms',
            source_run__sync_job__resource_type='inventory_snapshot')
    return source.filter(source_run_id__in=run_ids, warehouse_id__in=warehouse_ids)


def sales_platform_options(actor, country):
    """Platform names available from this actor's authorized active country stores."""
    require_metrics(actor)
    stores = filter_sales_queryset(actor, SALES,
        StoreMaster.objects.filter(tenant_id=actor.tenant_id, country_code__iexact=country.country_code,
                                  status='active', platform__status='active'),
        {'store_ids': 'id', 'platforms': 'platform__platform_type', 'regions': 'country_code'})
    names = defaultdict(set)
    for row in stores.values_list('platform__platform_type', 'platform__name').distinct():
        names[row[0]].add(row[1])
    return [{'platform_type': platform_type, 'name': ' / '.join(sorted(platform_names))}
            for platform_type, platform_names in sorted(names.items())]


def decision_rows(actor, country, skus, *, target_days=60, window_days=30,
                  end_date=None, ratio=None, include_in_transit=True, windows=(7, 15, 30), exclude_order_id=None):
    # A fresh cache per calculation, never stored on the user or reused by a
    # later request/batch. Revocations remain visible on the very next call.
    permission_cache = {}
    require_metrics(actor, permission_cache)
    from apps.sales_management.inventory_queries import latest_country_inventory
    skus = list(skus)
    if not skus:
        return []
    ids, now = [sku.pk for sku in skus], timezone.now()
    window_sizes = tuple(sorted(set(windows) | {window_days}))
    sales = sales_windows(actor, country, ids, window_sizes, end_date=end_date, permission_cache=permission_cache)
    # Rank source identities before filtering mappings/status. A failed or unmapped newest row must not expose an older valid one.
    raw = latest_country_inventory(_country_inventory_source(actor, country, now))
    scoped = filter_inventory_queryset(actor, INVENTORY, raw, permission_cache=permission_cache)
    stock = list(scoped.filter(internal_sku_id__in=ids).select_related('source_run', 'warehouse'))
    observations = defaultdict(list)
    for record in stock:
        observations[(record.internal_sku_id, record.warehouse_id)].append(record)
    country_warehouses = WarehouseMaster.objects.filter(tenant_id=actor.tenant_id,
        country_code__iexact=country.country_code, status='active')
    # Only connected or observed warehouses belong to this API stock total. Planned archives without an API connection do not invent stock.
    connected = set(SyncJob.objects.filter(tenant_id=actor.tenant_id, resource_type='inventory_snapshot',
        integration_config__platform='jifeng_wms', warehouse_authorization__warehouse__in=country_warehouses)
        .values_list('warehouse_authorization__warehouse_id', flat=True))
    # Both facts describe the same latest identity set; rank once, without
    # pushing the unmapped predicate into source selection.
    warehouse_facts = list(raw.order_by().values('warehouse_id').annotate(
        unmapped_count=Count('pk', filter=Q(internal_sku__isnull=True))))
    connected.update(row['warehouse_id'] for row in warehouse_facts)
    warehouses = list(country_warehouses.filter(pk__in=connected))
    unmapped_warehouses = {row['warehouse_id'] for row in warehouse_facts if row['unmapped_count']}
    # Authorization is resolved per request, never cached across actors/requests.
    configs = _custom_scope_configs(actor, INVENTORY, permission_cache, resource_code='commerce.inventory')
    branches = None if configs is None else [(config, _config_countries(actor, config)) for config in configs]
    warehouse_scopes = {sku.pk: _warehouse_ids(actor, country, sku, branches=branches) for sku in skus}
    groups = defaultdict(list)
    for sku in skus:
        scope = warehouse_scopes[sku.pk]
        groups[None if scope is None else tuple(sorted(scope))].append(sku.pk)
    pipelines = {}
    for scope, group_ids in groups.items():
        pipelines.update(pipeline_for(actor, country, group_ids, today=business_date(), target_days=target_days,
                                      warehouse_ids=None if scope is None else set(scope), exclude_order_id=exclude_order_id,
                                      permission_cache=permission_cache))
    result = []
    can_view_cost_ledger = check_user_permission(actor, 'supply.v2.view', cache=permission_cache) if skus else False
    for sku in skus:
        issues, warehouse_rows, selected = [], [], []
        allowed_warehouses = warehouse_scopes[sku.pk]
        pipe = pipelines[sku.pk]
        issues.extend(pipe['issues'])
        if not pipe['authorized']:
            issues.append('supply_summary_not_authorized')
        for warehouse in warehouses:
            if allowed_warehouses is not None and warehouse.pk not in allowed_warehouses:
                continue
            candidates = sorted(observations[(sku.pk, warehouse.pk)], key=lambda r: (r.snapshot_at_utc, r.pk), reverse=True)
            row, problems = (candidates[0] if candidates else None), []
            if not row:
                problems.append('missing_inventory_snapshot')
            else:
                selected.append(row)
                if 'available_qty' not in row.provided_quantity_fields:
                    problems.append('available_quantity_unverified')
                if row.source_run.status != 'success' or row.source_run.failed_count:
                    problems.append('inventory_source_incomplete')
                if row.snapshot_at_utc < now - timedelta(hours=24):
                    problems.append('stale_inventory_snapshot')
                if len({r.source_sku for r in candidates}) > 1:
                    problems.append('ambiguous_inventory_aliases')
            issues.extend(problems)
            warehouse_rows.append({'id': warehouse.pk, 'name': warehouse.name,
                'available_qty': str(row.available_qty) if row and not problems else None,
                'snapshot_at': row.snapshot_at_utc.isoformat() if row else None, 'issues': problems})
        if not warehouse_rows:
            issues.append('missing_inventory_snapshot')
        relevant_unmapped = bool(unmapped_warehouses if allowed_warehouses is None else unmapped_warehouses & allowed_warehouses)
        if relevant_unmapped:
            issues.append('unmapped_inventory')
        complete = bool(warehouse_rows) and not relevant_unmapped and all(not r['issues'] for r in warehouse_rows)
        available = sum((r.available_qty for r in selected), Decimal(0)) if complete else None
        transit = (sum((r.in_transit_qty for r in selected), Decimal(0)) if selected and
                   all('in_transit_qty' in r.provided_quantity_fields and r.source_run.status == 'success'
                       and not r.source_run.failed_count for r in selected) else None)
        windows_output = []
        for days in window_sizes:
            observed = sales[days]
            units = observed['units_by_sku'][sku.pk]
            direct_units = observed['direct_sales_by_sku'][sku.pk]
            bundle_units = observed['bundle_sales_by_sku'][sku.pk] if sku.spu.product_type != 'bundle' else 0
            unknown_codes = set(observed['issues'])
            if not observed['coverage_complete']:
                unknown_codes.add('collection_coverage_unproven')
            if observed['unmapped']:
                unknown_codes.add('unmapped_sales_lines')
            if not units and not observed['coverage_complete']:
                unknown_codes.add('no_sales_facts')
            unknown_bundle = bool(unknown_codes & {'bundle_composition_unverified', 'no_sales_facts',
                'no_authorized_sales_store', 'invalid_store_timezone', 'unfinished_store_day'})
            direct_unknown = bool(unknown_codes & {'no_sales_facts', 'no_authorized_sales_store',
                'invalid_store_timezone', 'unfinished_store_day'})
            windows_output.append({'days': days, 'start_date': str(observed['start_date']) if observed['start_date'] else None,
                'end_date': str(observed['end_date']) if observed['end_date'] else None,
                'units': None if unknown_bundle else units,
                'direct_sales_quantity': None if direct_unknown else direct_units,
                'bundle_sales_quantity': None if unknown_bundle else bundle_units,
                'total_demand_quantity': None if unknown_bundle else units,
                'daily_units': None if unknown_bundle else f'{Decimal(units) / days:.4f}',
                'amount_by_currency': {k: f'{v:.4f}' for k, v in observed['amounts'][sku.pk].items()},
                'refund_units': observed['refund_units'][sku.pk],
                'refund_amount_by_currency': {k: f'{v:.4f}' for k, v in observed['refund_amounts'][sku.pk].items()},
                'coverage_complete': observed['coverage_complete'], 'stores': observed['stores']})
        observed = sales[window_days]
        issues.extend(observed['issues'])
        if not observed['coverage_complete']:
            issues.append('collection_coverage_unproven')
        if observed['unmapped']:
            issues.append('unmapped_sales_lines')
        units = observed['units_by_sku'][sku.pk]
        direct_units = observed['direct_sales_by_sku'][sku.pk]
        bundle_units = observed['bundle_sales_by_sku'][sku.pk] if sku.spu.product_type != 'bundle' else 0
        if not units and not observed['coverage_complete']:
            issues.append('no_sales_facts')
        unknown_codes = {'no_sales_facts', 'no_authorized_sales_store', 'invalid_store_timezone',
            'unfinished_store_day', 'bundle_composition_unverified'}
        total_unknown = bool(unknown_codes.intersection(issues))
        direct_unknown = bool((unknown_codes - {'bundle_composition_unverified'}).intersection(issues))
        total_demand = None if total_unknown else units
        daily = Decimal(units) / window_days
        invalid_sales = any(code in issues for code in ('no_sales_facts', 'unmapped_sales_lines', 'collection_coverage_unproven',
            'invalid_store_timezone', 'unfinished_store_day', 'no_authorized_sales_store', 'bundle_composition_unverified'))
        incomplete_supply = any(code in pipe['issues'] for code in ('warehouse_supply_scope_incomplete', 'unassigned_warehouse_supply',
                                                                   'wms_receipt_overlap_unresolved'))
        quantity = None
        if complete and not invalid_sales and pipe['authorized'] and not incomplete_supply:
            quantity = suggestion_quantity(units, ratio, available,
                pipe['effective_incoming'] if include_in_transit else 0, pipe['open_operating_demand'],
                target_days=target_days if ratio is None else None, window_days=window_days)
        details = product_details(sku)
        blocking = []
        if not complete:
            blocking.extend(code for code in issues if code in {
                'missing_inventory_snapshot', 'available_quantity_unverified', 'inventory_source_incomplete',
                'stale_inventory_snapshot', 'ambiguous_inventory_aliases', 'unmapped_inventory'})
        if invalid_sales:
            blocking.extend(code for code in issues if code in {
                'no_sales_facts', 'unmapped_sales_lines', 'collection_coverage_unproven', 'invalid_store_timezone',
                'unfinished_store_day', 'no_authorized_sales_store', 'bundle_composition_unverified'})
        if not pipe['authorized']:
            blocking.append('supply_summary_not_authorized')
        if incomplete_supply:
            blocking.extend(code for code in pipe['issues'] if code in {
                'warehouse_supply_scope_incomplete', 'unassigned_warehouse_supply', 'wms_receipt_overlap_unresolved'})
        result.append({'sku_id': sku.pk, 'sku': sku.sku_code, 'legacy_sku_code': sku.legacy_sku_code or '',
            'product_name': sku.product_name, 'product_details': details,
            'image_preview_url': f'/api/internal/commerce/inventory/country-decisions/{country.pk}/skus/{sku.pk}/image/' if details.get('image_url') else '',
            'available_stock': str(available) if available is not None else None, 'inventory_complete': complete,
            'warehouses': warehouse_rows, 'wms_in_transit_stock': str(transit) if transit is not None else None,
            'pipeline': pipe, 'sales_windows': windows_output,
            'daily_sales': None if total_unknown else f'{daily:.4f}',
            'direct_sales_quantity': None if direct_unknown else direct_units,
            'bundle_sales_quantity': None if total_unknown else bundle_units,
            'total_demand_quantity': total_demand,
            'coverage_days': str((available / daily).quantize(Decimal('0.01'))) if available is not None and daily > 0 and not total_unknown else None,
            'suggested_quantity': quantity, 'needs_review': True, 'issues': sorted(set(issues)),
            'decision_state': 'ready' if quantity is not None else 'pending',
            'replenishment_status': 'pending' if quantity is None else ('needed' if quantity > 0 else 'sufficient'),
            'blocking_issues': sorted(set(blocking)),
            'data_at': min((r.snapshot_at_utc for r in selected), default=None),
            'computed_at': now.isoformat(),
            'suggestion_formula': '日均销量 × 目标覆盖天数 − 可用库存 − 按期有效到货 − 已有开放运营需求，向上取整且不小于0',
            'source_snapshot_ids': [r.pk for r in selected], 'source_run_ids': sorted(observed['source_run_ids']),
            'cost_ledger_url': '/supply-chain/costs' if can_view_cost_ledger else None,
            'stock_age': {'status': 'unavailable', 'notice': '当前 API 余额不能推导精确库龄；待接入仓库库龄或完整出入库批次后启用。'}})
    return result
