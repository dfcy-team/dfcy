"""Country/SKU observations shared by inventory decisions and operating-order previews.

Missing source fields remain unknown. WMS transit is observational and is never
added to the supply-chain projection. All monetary totals retain their currency.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone as dt_timezone
from decimal import Decimal, ROUND_CEILING
from fractions import Fraction
from itertools import islice
from math import ceil
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.db.models import Count, Exists, OuterRef, Q, Sum, Value
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, NotFound

from apps.masterdata.models import CountrySiteMaster, StoreMaster, WarehouseMaster
from apps.products.models import ProductSKU
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from apps.sales_management.scopes import filter_sales_queryset, _custom_scope_configs, _stores_for_config
from apps.supply_chain.dates import business_date
from apps.supply_chain.supplier_products import product_details
from apps.integrations.models import HistorySyncSegment, SyncJob, SyncRun
from .models import InventorySnapshot, SalesOrder, SalesOrderItem, RefundReturn, RefundReturnItem
from .supply_pipeline import pipeline_for
from .inventory_operations import operating_assessment

INVENTORY = 'sales_management.view'
SALES = 'sales_management.skus.view'
JIFENG = 'jifeng_wms'
BEST = 'best_ecapi'
DECISION_PROVIDERS = (JIFENG, BEST)
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


@dataclass(frozen=True)
class _InventoryBranch:
    providers: frozenset
    warehouse_ids: frozenset = frozenset()
    site_codes: frozenset | None = None
    sku_ids: frozenset = frozenset()
    spu_ids: frozenset = frozenset()
    provider_restricted: bool = False

    @property
    def product_restricted(self):
        return bool(self.sku_ids or self.spu_ids)

    def allows_product(self, sku):
        return ((not self.sku_ids or sku.pk in self.sku_ids)
                and (not self.spu_ids or sku.spu_id in self.spu_ids))

    def allows_source(self, warehouse_id, provider, site_code):
        return (provider in self.providers
                and (not self.warehouse_ids or warehouse_id in self.warehouse_ids)
                and (self.site_codes is None or site_code in self.site_codes))

    def source_filter(self):
        query = Q()
        if self.warehouse_ids:
            query &= Q(warehouse_id__in=self.warehouse_ids)
        if self.site_codes is not None:
            query &= Q(site_code__in=self.site_codes)
        return query

    def product_filter(self, *, inventory=False):
        query = Q()
        if self.sku_ids:
            query &= Q(**{('internal_sku_id' if inventory else 'pk') + '__in': self.sku_ids})
        if self.spu_ids:
            query &= Q(**{('internal_sku__spu_id' if inventory else 'spu_id') + '__in': self.spu_ids})
        return query


def _inventory_branches(actor, permission_cache, *, include_best):
    providers = frozenset(DECISION_PROVIDERS if include_best else (JIFENG,))
    configs = _custom_scope_configs(actor, INVENTORY, permission_cache, resource_code='commerce.inventory')
    if configs is None:
        return (_InventoryBranch(providers),)
    branches = []
    identity_keys = {'warehouse_ids', 'sku_ids', 'spu_ids'}
    supported = identity_keys | {'regions', 'store_ids', 'platforms'}
    for config in configs:
        if not config or set(config) - supported:
            continue
        for key in identity_keys & config.keys():
            values = config[key]
            if not isinstance(values, list) or not values or any(type(v) is not int or v <= 0 for v in values):
                raise PermissionDenied('库存商品或仓库范围配置无效。')
        if any(not isinstance(config[key], list) or not config[key]
               for key in (supported - identity_keys) & config.keys()):
            continue
        platforms = config.get('platforms')
        selected = providers.intersection(str(value) for value in platforms) if platforms else providers
        if not selected:
            continue
        sites = None
        if config.get('store_ids'):
            sites = frozenset(_stores_for_config(actor, config).values_list('country_code', flat=True))
        elif config.get('regions'):
            sites = frozenset(str(value) for value in config['regions'])
        branches.append(_InventoryBranch(selected,
            warehouse_ids=frozenset(config.get('warehouse_ids', ())), site_codes=sites,
            sku_ids=frozenset(config.get('sku_ids', ())), spu_ids=frozenset(config.get('spu_ids', ())),
            provider_restricted=bool(platforms)))
    return frozenset(branches)


def _connected_inventory_jobs(actor, providers):
    return SyncJob.objects.filter(tenant_id=actor.tenant_id, resource_type='inventory_snapshot',
        integration_config__tenant_id=actor.tenant_id, integration_config__platform__in=providers,
        warehouse_authorization__tenant_id=actor.tenant_id)


def _provider_facts(actor, providers):
    return InventorySnapshot.objects.filter(tenant_id=actor.tenant_id,
        source_run__tenant_id=actor.tenant_id, source_run__sync_job__tenant_id=actor.tenant_id,
        source_run__sync_job__integration_config__tenant_id=actor.tenant_id,
        source_run__sync_job__resource_type='inventory_snapshot',
        source_run__sync_job__integration_config__platform__in=providers)


def _config_countries(actor, branch, *, require_provider_evidence=False):
    codes = {site.upper() for site in branch.site_codes} if branch.site_codes is not None else None
    warehouses = WarehouseMaster.objects.filter(tenant_id=actor.tenant_id)
    if branch.warehouse_ids:
        warehouses = warehouses.filter(pk__in=branch.warehouse_ids)
        selected = {code.upper() for code in warehouses.values_list('country_code', flat=True)}
        codes = selected if codes is None else codes & selected
    if branch.provider_restricted and require_provider_evidence:
        # A provider-specific role can enumerate only countries with evidence
        # for that provider and its own warehouse and site constraints.
        warehouses = warehouses.filter(status='active')
        if codes is not None:
            warehouses = warehouses.filter(country_code__in=codes)
        jobs = _connected_inventory_jobs(actor, branch.providers).filter(
            warehouse_authorization__warehouse_id=OuterRef('pk'))
        now = timezone.now()
        provider_facts = _provider_facts(actor, branch.providers).filter(snapshot_at_utc__lte=now)
        facts = provider_facts.filter(
            branch.source_filter(), branch.product_filter(inventory=True), warehouse_id=OuterRef('pk'),
            site_code=OuterRef('country_code'),
        )
        if branch.product_restricted:
            provider_field = 'source_run__sync_job__integration_config__platform'
            superseding = provider_facts.filter(
                Q(snapshot_at_utc__gt=OuterRef('snapshot_at_utc'))
                | Q(snapshot_at_utc=OuterRef('snapshot_at_utc'), pk__gt=OuterRef('pk')),
                warehouse_id=OuterRef('warehouse_id'), site_code=OuterRef('site_code'),
                source_sku=OuterRef('source_sku'), **{provider_field: OuterRef(provider_field)},
            )
            facts = facts.filter(~Exists(superseding))
        selected = warehouses.filter(Q(Exists(jobs)) | Q(Exists(facts))).order_by().values_list(
            'country_code', flat=True).distinct()
        return {code.upper() for code in selected}
    return codes


def countries_for(actor, permission_cache=None, *, include_best=False):
    require_metrics(actor, permission_cache)
    rows = CountrySiteMaster.objects.filter(tenant_id=actor.tenant_id, status='active')
    branches = _inventory_branches(actor, permission_cache, include_best=include_best)
    codes = set()
    for branch in branches:
        values = _config_countries(actor, branch, require_provider_evidence=include_best)
        if values is None and (branch.product_restricted or not branch.provider_restricted):
            return rows.order_by('country_code', 'pk')
        codes.update(values or ())
    return rows.filter(country_code__in=codes).order_by('country_code', 'pk')


def country_for(actor, pk, permission_cache=None, *, include_best=False):
    country = countries_for(actor, permission_cache, include_best=include_best).filter(pk=pk).first()
    if not country:
        raise NotFound('国家不存在或不在库存数据授权范围内。')
    return country


def skus_for(actor, country, permission_cache=None, *, include_best=False):
    rows = ProductSKU.objects.filter(tenant_id=actor.tenant_id, is_active=True).exclude(inventory_type='virtual')
    allowed = Q(pk__in=[])
    for branch in _inventory_branches(actor, permission_cache, include_best=include_best):
        codes = _config_countries(actor, branch, require_provider_evidence=include_best)
        if codes is None:
            if branch.provider_restricted and not branch.product_restricted:
                continue
        elif country.country_code.upper() not in codes:
            continue
        if not branch.product_restricted:
            return rows
        allowed |= branch.product_filter()
    return rows.filter(allowed)


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
            'order_item__sales_order', 'bundle_version', 'bundle_version__bundle_sku').only(
                'tenant_id', 'order_item_id', 'bundle_version_id', 'components_payload',
                'order_item__sales_order__tenant_id', 'bundle_version__tenant_id',
                'bundle_version__effective_at', 'bundle_version__bundle_sku__tenant_id',
                'bundle_version__bundle_sku__product_type')}
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
                snapshot.bundle_version.bundle_sku.product_type != 'bundle'):
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
        product_type='standard').values_list('pk', flat=True))
    for _, component_id, _ in component_rows:
        if component_id not in valid_components:
            unverified = True
            break
    demand = defaultdict(int)
    invalid_item_ids = {item_id for item_id, component_id, _ in component_rows if component_id not in valid_components}
    for item_id, component_id, quantity in component_rows:
        if item_id not in invalid_item_ids and component_id in valid_components and component_id in requested:
            item_quantity = item_quantities[item_id]
            demand[component_id] += item_quantity * quantity
    return demand, unverified


def sales_windows(actor, country, sku_ids, windows, *, end_date=None, platform_type=None, permission_cache=None, inventory_only=False):
    from .inventory_sales import sales_windows as batched_sales_windows
    return batched_sales_windows(actor, country, sku_ids, windows, end_date=end_date,
                                 platform_type=platform_type, permission_cache=permission_cache, inventory_only=inventory_only)


def _country_inventory_source(actor, country, now):
    from django.conf import settings

    if settings.INVENTORY_COMPLETE_BATCH_READS_ENABLED:
        from apps.sales_management.inventory_batches import published_inventory_filter

        return InventorySnapshot.objects.filter(
            published_inventory_filter(actor.tenant_id, country_code=country.country_code, as_of=now),
            tenant_id=actor.tenant_id, snapshot_at_utc__lte=now,
        )
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


def _inventory_identity(actor, country):
    return actor.tenant_id, actor.pk, getattr(actor, '_active_membership_id', None), country.pk


def inventory_context_for(actor, country, *, include_best=False, permission_cache=None, sku_ids=None, now=None):
    """Read each provider's latest identities before checking product mappings."""
    from apps.sales_management.inventory_queries import latest_country_inventory
    require_metrics(actor, permission_cache)
    branches = _inventory_branches(actor, permission_cache, include_best=include_best)
    now = now or timezone.now()
    country_warehouses = WarehouseMaster.objects.filter(tenant_id=actor.tenant_id,
        country_code__iexact=country.country_code, status='active')
    by_sku = defaultdict(list)
    coverage, unmapped = set(), set()
    providers = {provider for branch in branches for provider in branch.providers}
    for provider in sorted(providers):
        provider_branches = [branch for branch in branches if provider in branch.providers]
        source = (_country_inventory_source(actor, country, now) if provider == JIFENG else
                  _provider_facts(actor, (BEST,)).filter(warehouse__in=country_warehouses, snapshot_at_utc__lte=now))
        envelope, mapped = Q(pk__in=[]), Q(pk__in=[])
        for branch in provider_branches:
            source_filter = branch.source_filter()
            # Q() is neutral for OR in Django. A branch with no source
            # dimensions must explicitly contribute all warehouse/site pairs.
            envelope |= source_filter or Q(pk__isnull=False)
            mapped |= (source_filter & branch.product_filter(inventory=True)) or Q(pk__isnull=False)
        if not any(not branch.source_filter() for branch in provider_branches):
            source = source.filter(envelope)
        raw = latest_country_inventory(source)
        facts = raw.order_by().values('warehouse_id', 'site_code').annotate(
            unmapped_count=Count('pk', filter=Q(internal_sku__isnull=True)))
        for fact in facts:
            pair = fact['warehouse_id'], provider, fact['site_code']
            if any(not branch.product_restricted and branch.allows_source(*pair) for branch in provider_branches):
                coverage.add(pair)
                if fact['unmapped_count']:
                    unmapped.add(pair)

        # A bound job can explain a missing observation. BEST jobs query a
        # configured SKU list, so a job or completed run never supplies zero
        # stock or completeness for a SKU without its own fact.
        jobs = _connected_inventory_jobs(actor, (provider,)).filter(
            warehouse_authorization__warehouse__in=country_warehouses).order_by().values_list(
            'warehouse_authorization__warehouse_id', 'warehouse_authorization__warehouse__country_code').distinct()
        for warehouse_id, site_code in jobs:
            pair = warehouse_id, provider, site_code.upper()
            if any(branch.allows_source(*pair) for branch in provider_branches):
                coverage.add(pair)

        stock = raw.filter(mapped, warehouse__status='active', internal_sku_id__isnull=False)
        if sku_ids is not None:
            stock = stock.filter(internal_sku_id__in=sku_ids)
        stock = stock.annotate(inventory_provider=Value(provider)).select_related('source_run').only(
            'id', 'internal_sku_id', 'warehouse_id', 'site_code', 'source_sku', 'available_qty', 'on_hand_qty',
            'in_transit_qty', 'provided_quantity_fields', 'snapshot_at_utc', 'source_run_id',
            'source_run__status', 'source_run__failed_count', 'source_run__finished_at')
        for record in stock.order_by().iterator(chunk_size=1000):
            if any(branch.allows_source(record.warehouse_id, provider, record.site_code) for branch in provider_branches):
                by_sku[record.internal_sku_id].append(record)
    warehouse_ids = {pair[0] for pair in coverage}
    warehouse_ids.update(record.warehouse_id for records in by_sku.values() for record in records)
    warehouses = country_warehouses.in_bulk(warehouse_ids)
    return {'identity': _inventory_identity(actor, country), 'branches': branches, 'now': now,
            'by_sku': by_sku, 'warehouses': warehouses, 'coverage': coverage, 'unmapped': unmapped}


def _sku_inventory_sources(context, sku):
    branches = [branch for branch in context['branches'] if branch.allows_product(sku)]
    pairs = context['coverage'] | {(row.warehouse_id, row.inventory_provider, row.site_code)
                                   for row in context['by_sku'].get(sku.pk, ())}
    return {pair for pair in pairs if pair[0] in context['warehouses']
            and any(branch.allows_source(*pair) for branch in branches)}


def _inventory_run_complete(row, now):
    run = row.source_run
    return (run.status == 'success' and not run.failed_count and
            (row.inventory_provider != BEST or (run.finished_at is not None and run.finished_at <= now)))


def _sku_inventory_rows(context, sku, sources):
    by_warehouse = defaultdict(list)
    for record in context['by_sku'].get(sku.pk, ()):
        pair = record.warehouse_id, record.inventory_provider, record.site_code
        if pair in sources:
            by_warehouse[record.warehouse_id].append(record)
    warehouse_rows = {}
    for warehouse_id, candidates in by_warehouse.items():
        row = max(candidates, key=lambda record: (record.snapshot_at_utc, record.pk))
        problems = []
        if 'available_qty' not in row.provided_quantity_fields:
            problems.append('available_quantity_unverified')
        if not _inventory_run_complete(row, context['now']):
            problems.append('inventory_source_incomplete')
        if row.snapshot_at_utc < context['now'] - timedelta(hours=24):
            problems.append('stale_inventory_snapshot')
        if len({r.source_sku for r in candidates if r.inventory_provider == row.inventory_provider}) > 1:
            problems.append('ambiguous_inventory_aliases')
        warehouse_rows[warehouse_id] = row, problems
    return warehouse_rows


def mapped_inventory_facts(context, skus):
    """Use the same selected warehouse rows for the mapped workbench summary."""
    for sku in skus.iterator(chunk_size=1000):
        sources = _sku_inventory_sources(context, sku)
        for row, problems in _sku_inventory_rows(context, sku, sources).values():
            yield {'internal_sku_id': sku.pk, 'available_qty': row.available_qty if not problems else None}


def _supply_warehouse_ids(sku, country_branches):
    branches = [branch for branch in country_branches if branch.allows_product(sku)]
    if any(not branch.warehouse_ids and
           (not branch.provider_restricted or branch.site_codes is not None or branch.product_restricted)
           for branch in branches):
        return None
    return {warehouse_id for branch in branches for warehouse_id in branch.warehouse_ids}


def decision_rows(actor, country, skus, *, target_days=60, window_days=30, mapped_only=False,
                  end_date=None, ratio=None, include_in_transit=True, windows=(7, 15, 30), exclude_order_id=None,
                  demand_horizon_start=None, demand_horizon_end=None, platform_type=None, sales_observations=None, pipeline_observations=None, inventory_context=None, compact_product_details=False, include_best=False):
    # A fresh cache per calculation, never stored on the user or reused by a
    # later request/batch. Revocations remain visible on the very next call.
    permission_cache = {}
    require_metrics(actor, permission_cache)
    skus = list(skus)
    if not skus:
        return []
    ids, now = [sku.pk for sku in skus], timezone.now()
    from .inventory_listing import linked_sku_ids, apply_listing_observation
    linked_ids = linked_sku_ids(actor.tenant_id, country.country_code, ids)
    window_sizes = tuple(sorted(set(windows) | {window_days}))
    sales = sales_observations if sales_observations is not None else sales_windows(actor, country, ids, window_sizes, end_date=end_date, permission_cache=permission_cache, platform_type=platform_type)
    if inventory_context is None:
        inventory_context = inventory_context_for(actor, country, include_best=include_best,
            permission_cache=permission_cache, sku_ids=ids, now=now)
    elif (inventory_context['identity'] != _inventory_identity(actor, country) or
            inventory_context['branches'] != _inventory_branches(actor, permission_cache, include_best=include_best)):
        raise PermissionDenied('库存上下文不匹配。')
    branches = inventory_context['branches']
    sku_sources = {sku.pk: _sku_inventory_sources(inventory_context, sku) for sku in skus}
    # The supply summary has its own permission check. Inventory coverage
    # cannot narrow local supply facts assigned to authorized warehouses.
    country_branches = []
    for branch in branches:
        codes = _config_countries(actor, branch)
        if codes is None or country.country_code.upper() in codes:
            country_branches.append(branch)
    groups = defaultdict(list)
    for sku in skus:
        scope = _supply_warehouse_ids(sku, country_branches)
        groups[None if scope is None else tuple(sorted(scope))].append(sku.pk)
    pipelines = {}
    for scope, group_ids in groups.items():
        if scope is None and pipeline_observations is not None:
            pipelines.update({sku_id: pipeline_observations[sku_id] for sku_id in group_ids
                              if sku_id in pipeline_observations})
            group_ids = [sku_id for sku_id in group_ids if sku_id not in pipelines]
            if not group_ids:
                continue
        pipelines.update(pipeline_for(actor, country, group_ids, today=business_date(), target_days=target_days,
                                      warehouse_ids=None if scope is None else set(scope), exclude_order_id=exclude_order_id,
                                      horizon_start=demand_horizon_start, horizon_end=demand_horizon_end,
                                      permission_cache=permission_cache))
    result = []
    can_view_cost_ledger = check_user_permission(actor, 'supply.v2.view', cache=permission_cache) if skus else False
    for sku in skus:
        issues, warehouse_rows, selected = [], [], []
        sources = sku_sources[sku.pk]
        observations = _sku_inventory_rows(inventory_context, sku, sources)
        pipe = pipelines[sku.pk]
        issues.extend(pipe['issues'])
        if not pipe['authorized']:
            issues.append('supply_summary_not_authorized')
        warehouse_ids = observations.keys() if mapped_only else {pair[0] for pair in sources}
        for warehouse_id in sorted(warehouse_ids):
            warehouse = inventory_context['warehouses'][warehouse_id]
            row, problems = observations.get(warehouse_id, (None, ['missing_inventory_snapshot']))
            if row:
                selected.append(row)
            issues.extend(problems)
            warehouse_rows.append({'id': warehouse.pk, 'name': warehouse.name,
                'available_qty': str(row.available_qty) if row and not problems else None,
                'last_synced_qty': str(row.available_qty) if row and not (set(problems) - {'stale_inventory_snapshot'}) else None,
                'snapshot_at': row.snapshot_at_utc.isoformat() if row else None, 'issues': problems})
        if not warehouse_rows:
            issues.append('missing_inventory_snapshot')
        relevant_unmapped = any(
            not branch.product_restricted and any(branch.allows_source(*pair)
                for pair in sources & inventory_context['unmapped']) for branch in branches)
        if relevant_unmapped:
            issues.append('unmapped_inventory')
        complete = bool(warehouse_rows) and all(not r['issues'] for r in warehouse_rows)
        available = sum((r.available_qty for r in selected), Decimal(0)) if complete else None
        transit = (sum((r.in_transit_qty for r in selected), Decimal(0)) if selected and
                   all('in_transit_qty' in r.provided_quantity_fields
                       and _inventory_run_complete(r, inventory_context['now']) for r in selected) else None)
        windows_output = []
        for days in window_sizes:
            observed = sales[days]
            units = observed['units_by_sku'][sku.pk]
            direct_units = observed['direct_sales_by_sku'][sku.pk]
            bundle_units = observed['bundle_sales_by_sku'][sku.pk] if sku.product_type != 'bundle' else 0
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
                'recognized_units': units,
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
        bundle_units = observed['bundle_sales_by_sku'][sku.pk] if sku.product_type != 'bundle' else 0
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
        if not mapped_only and complete and not invalid_sales and pipe['authorized'] and not incomplete_supply:
            quantity = suggestion_quantity(units, ratio, available,
                pipe['effective_incoming'] if include_in_transit else 0, pipe['open_operating_demand'],
                target_days=target_days if ratio is None else None, window_days=window_days)
        if compact_product_details:
            from apps.supply_chain.supplier_products import safe_image_url
            details={'image_url':safe_image_url(sku.image_url,sku.tenant_id)}
        else:
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
            'on_hand_stock': str(sum((r.on_hand_qty for r in selected), Decimal(0))) if complete and selected and all('on_hand_qty' in r.provided_quantity_fields and r.source_run.status == 'success' and not r.source_run.failed_count for r in selected) else None,
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
        if mapped_only:
            # The mapped observation is deliberately separate from complete
            # procurement demand. Unmapped stock/orders do not erase known facts.
            row = result[-1]
            row.update(mapped_only=True, inventory_scope='mapped_latest', inventory_type=sku.inventory_type,
                       mapped_sales_units=units, mapped_direct_sales_units=direct_units,
                       mapped_bundle_sales_units=bundle_units,
                       mapped_daily_sales=f'{Decimal(units) / window_days:.4f}',
                       mapped_sales_complete=not invalid_sales,
                       unmapped_inventory_excluded=relevant_unmapped,
                       unmapped_sales_excluded=bool(observed['unmapped']),
                       unknown_bundle_demand_excluded=bool(observed['bundle_composition_unverified']))
        result[-1]['operations'] = operating_assessment(result[-1], window_days=window_days, target_days=target_days)
        apply_listing_observation(result[-1], sku.pk in linked_ids, window_days=window_days, target_days=target_days)
    return result
