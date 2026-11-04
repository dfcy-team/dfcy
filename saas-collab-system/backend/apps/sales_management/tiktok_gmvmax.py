"""Permission-scoped stored GMVMax spend shared by sales views."""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from apps.integrations.models import TikTokAdsAdvertiserMapping
from apps.integrations.gmv_max_read import GMVMaxSnapshotOverflow
from .tiktok_source import preferred_tiktok_days
from apps.masterdata.exchange_rates import tenant_cny_rates
from apps.reports.advertising_dataset import filter_advertising_stores
from apps.permissions.ui_p6_scopes import (
    INTEGRATION_SCOPE_KEYS, _regions_fit_scope, _validate_integration_configs,
    permission_scope_configs,
)
from apps.permissions.services import get_stored_business_read_scopes
from apps.masterdata.models import StoreMaster


def _mapping_allowed(user, mapping, scopes):
    # None means the caller has unrestricted integration visibility. An empty
    # list is a resolved deny-all scope.
    if scopes is None:
        return True
    config = mapping.integration_config
    for scope in scopes:
        if scope.get('platforms') and config.platform not in scope['platforms']:
            continue
        if scope.get('environments') and config.environment not in scope['environments']:
            continue
        if scope.get('regions') and not _regions_fit_scope([*(config.regions or []), mapping.store.country_code or '__UNKNOWN__'], scope['regions']):
            continue
        if scope.get('integration_config_ids') and config.pk not in scope['integration_config_ids']:
            continue
        if scope.get('resource_types') and 'advertising_report' not in scope['resource_types']:
            continue
        if scope.get('store_ids') and mapping.store_id not in scope['store_ids']:
            continue
        if scope.get('warehouse_ids') and None not in scope['warehouse_ids']:
            continue
        return True
    return False


def gmvmax_spend(user, stores, start, end, *, target_currencies=None):
    """Return {(store_id, ISO day, currency): spend}, and stores with incomplete evidence."""
    if not user.is_active or user.user_type != 'internal' or not user.tenant_id:
        return {}, set(), False
    ids = [s.get('id', s.get('store_id')) if isinstance(s, dict) else s.pk for s in stores]
    ids = [sid for sid in ids if sid is not None]
    visible = set(filter_advertising_stores(user, StoreMaster.objects.filter(pk__in=ids, tenant_id=user.tenant_id)).values_list('pk', flat=True))
    try:
        scopes = permission_scope_configs(user, 'integrations.store.view', INTEGRATION_SCOPE_KEYS,
            scope_resolver=get_stored_business_read_scopes)
        if scopes is not None:
            _validate_integration_configs(scopes)
    except Exception:
        return {}, set(ids), False
    mappings = list(TikTokAdsAdvertiserMapping.objects.filter(tenant_id=user.tenant_id,
        store_id__in=visible, store__tenant_id=user.tenant_id,
        store__platform__tenant_id=user.tenant_id, store__platform__platform_type='tiktok',
        integration_config__tenant_id=user.tenant_id, integration_config__platform='tiktok'
    ).select_related('store__platform', 'integration_config'))
    allowed = [m for m in mappings if _mapping_allowed(user, m, scopes)]
    hidden = {m.store_id for m in mappings if m not in allowed}
    names = {}
    try:
        rows = preferred_tiktok_days(user, allowed, start, end)
    except GMVMaxSnapshotOverflow:
        return {}, set(visible), True
    allowed_by_store = defaultdict(list)
    for m in allowed:
        allowed_by_store[m.store_id].append(m)
    rates = tenant_cny_rates(user.tenant)
    output = defaultdict(Decimal)
    failed = set(hidden) | (visible - set(allowed_by_store))
    target_currencies = target_currencies or {}
    dates = set()
    day = start
    while day <= end:
        dates.add(day.isoformat())
        day += timedelta(days=1)
    # Track coverage for each allowed advertiser and exclude days whose
    # snapshots disagree about the actual platform store or timezone.
    coverage = defaultdict(set)
    identities = defaultdict(set)
    for row in rows:
        for mapping in allowed:
            if mapping.advertiser_id != row['advertiser_id'] or row['currency'] != mapping.currency:
                continue
            mapping_key = getattr(mapping, 'pk', id(mapping))
            key = (mapping.store_id, row['date'])
            coverage[key].add(mapping_key)
            identities[(mapping_key, row['date'])].add((row.get('platform_store_id'), row.get('timezone'), row['currency']))
    for store_id, maps in allowed_by_store.items():
        for date_text in dates:
            if any(getattr(m, 'pk', id(m)) not in coverage[(store_id, date_text)] for m in maps):
                failed.add(store_id)
        for row in rows:
            mapping = next((m for m in maps if m.advertiser_id == row['advertiser_id']), None)
            if not mapping or row['currency'] != mapping.currency:
                continue
            if len(identities[(getattr(mapping, 'pk', id(mapping)), row['date'])]) > 1:
                failed.add(store_id)
                continue
            source = row['currency'].upper()
            if store_id in target_currencies and not target_currencies[store_id]:
                failed.add(store_id)
                continue
            target = (target_currencies.get(store_id) or mapping.store.currency).upper()
            ratio = Decimal(1) if source == target else None
            if source in rates and target in rates:
                # Rates are units of each currency per CNY: target/source
                # converts an amount in source currency into target currency.
                ratio = rates[target]['rate'] / rates[source]['rate']
            if ratio is None:
                failed.add(store_id)
                continue
            try:
                cost = Decimal(str(row['cost']))
                if not cost.is_finite() or cost < 0 or not ratio.is_finite() or ratio <= 0:
                    failed.add(store_id)
                    continue
            except (InvalidOperation, TypeError, ValueError):
                failed.add(store_id)
                continue
            output[(store_id, row['date'], target)] += cost * ratio
    return dict(output), failed, True
