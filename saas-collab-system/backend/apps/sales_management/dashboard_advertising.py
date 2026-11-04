"""Conservative daily advertising spend for the sales dashboard."""
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.db import DatabaseError, transaction
from django.db.models import Count, Sum
from rest_framework.exceptions import ValidationError

from apps.integrations.gmv_max_read import GMVMaxSnapshotOverflow
from apps.integrations.models import (
    ShopeeAdvertisingRecord,
    TikTokAdsAdvertiserMapping,
)
from apps.masterdata.models import StoreMaster
from apps.permissions.services import check_user_permission, get_stored_business_read_scopes
from apps.permissions.ui_p6_scopes import (
    INTEGRATION_SCOPE_KEYS,
    _regions_fit_scope,
    _validate_integration_configs,
    permission_scope_configs,
)
from apps.reports.advertising_dataset import advertising_queryset, filter_advertising_stores
from apps.sales_management.observed_roi import _valid_expense
from apps.sales_management.tiktok_source import preferred_tiktok_days
from apps.masterdata.exchange_rates import tenant_cny_rates


def _timezone_days_match(left, right, start, end):
    """Treat timezone aliases as equal when their local day boundaries agree."""
    try:
        left_zone, right_zone = ZoneInfo(left), ZoneInfo(right)
        day = start
        while day <= end + timedelta(days=1):
            if datetime.combine(day, datetime.min.time(), left_zone).utcoffset() != datetime.combine(
                    day, datetime.min.time(), right_zone).utcoffset():
                return False
            day += timedelta(days=1)
        return True
    except (TypeError, ValueError, KeyError):
        return False


def _saved_rate(rates, currency):
    code = (currency or "").upper()
    if code == "CNY":
        return Decimal("1")
    try:
        rate = Decimal(rates[code]["rate"])
        return rate if rate.is_finite() and rate > 0 else None
    except (KeyError, TypeError, InvalidOperation):
        return None


def _integration_scope_matches(configs, mapping):
    """Apply the same integration dimensions as mapping_allowed, once-resolved."""
    if configs is None:
        return True
    config = mapping.integration_config
    regions = [*(config.regions or []), mapping.store.country_code or "__UNKNOWN__"]
    for scope in configs:
        if "platforms" in scope and config.platform not in scope["platforms"]:
            continue
        if "environments" in scope and config.environment not in scope["environments"]:
            continue
        if "regions" in scope and not _regions_fit_scope(regions, scope["regions"]):
            continue
        if "integration_config_ids" in scope and config.pk not in scope["integration_config_ids"]:
            continue
        if "resource_types" in scope and "advertising_report" not in scope["resource_types"]:
            continue
        if "store_ids" in scope and mapping.store_id not in scope["store_ids"]:
            continue
        if "warehouse_ids" in scope and None not in scope["warehouse_ids"]:
            continue
        return True
    return False


def dashboard_advertising(request, stores, start, end, *, comparison=False):
    """Return (available|forbidden, {(currency, ISO day): Decimal | None}).

    All selected stores are represented for each calendar day.  A daily total is
    present only if every selected store in that currency has one complete,
    currency-matched observation for that day. Optional comparison data compares
    adjacent days over their shared complete store set.
    """
    result = {}
    user = request.user
    if not check_user_permission(
        user, "analytics.view", cache=getattr(request, "_permission_resolution_cache", None),
    ):
        return ("forbidden", result, {}) if comparison else ("forbidden", result)

    store_rows = stores.values() if isinstance(stores, dict) else stores
    shops = [store for store in store_rows if store.get("currency")]
    currencies = defaultdict(list)
    for store in shops:
        currencies[store["currency"]].append(store)
    days = []
    cursor = start
    while cursor <= end:
        days.append(cursor)
        cursor += timedelta(days=1)
    for currency in currencies:
        for day in days:
            result[(currency, day.isoformat())] = None

    if not shops or not days:
        return ("available", result, {}) if comparison else ("available", result)

    selected_by_id = {store["id"]: store for store in shops}
    shopee = [s for s in shops if s.get("platform__platform_type") == "shopee"]
    tiktok = [s for s in shops if s.get("platform__platform_type") == "tiktok"]
    spend_by_store_day = {}

    try:
        if shopee:
            qs = advertising_queryset(request, {"date_from": start, "date_to": end}, "analytics.view")
            with transaction.atomic():
                rows = list(qs.filter(store_id__in=[s["id"] for s in shopee])
                            .values("store_id", "report_date", "currency", "report_timezone")
                            .annotate(records=Count("pk"), spend=Sum(_valid_expense())))
            observed = defaultdict(list)
            for row in rows:
                observed[(row["store_id"], row["report_date"])].append(row)
            for store in shopee:
                for day in days:
                    key = (store["id"], day)
                    entries = observed.get(key, [])
                    if len(entries) != 1:
                        continue
                    item = entries[0]
                    if (item["records"] == 1 and item["spend"] is not None
                            and item["currency"] == store["currency"]
                            and item["report_timezone"] == store.get("timezone")):
                        spend_by_store_day[key] = item["spend"]

        if tiktok:
            user_is_internal = bool(user.is_active and user.user_type == "internal")
            with transaction.atomic():
                visible_tiktok_store_ids = set(filter_advertising_stores(
                    user, StoreMaster.objects.filter(pk__in=[store["id"] for store in tiktok]),
                ).values_list("pk", flat=True))
                if user_is_internal:
                    try:
                        integration_scopes = permission_scope_configs(
                            user, "integrations.store.view", INTEGRATION_SCOPE_KEYS,
                            scope_resolver=get_stored_business_read_scopes,
                        )
                        if integration_scopes is not None:
                            _validate_integration_configs(integration_scopes)
                    except Exception as exc:
                        from apps.common.exceptions import DataScopeDenied
                        if not isinstance(exc, DataScopeDenied):
                            raise
                        integration_scopes = []
                else:
                    integration_scopes = []
            with transaction.atomic():
                maps = list(TikTokAdsAdvertiserMapping.objects.filter(
                    tenant_id=user.tenant_id,
                    store_id__in=[s["id"] for s in tiktok],
                ).select_related("store__platform", "integration_config"))
            maps_by_store = defaultdict(list)
            invisible_stores = set()
            for mapping in maps:
                valid_identity = (user_is_internal and mapping.tenant_id == user.tenant_id
                                  and mapping.store.tenant_id == user.tenant_id
                                  and mapping.store.platform.tenant_id == user.tenant_id
                                  and mapping.store.platform.platform_type == "tiktok"
                                  and mapping.integration_config.tenant_id == user.tenant_id
                                  and mapping.integration_config.platform == "tiktok")
                integration_visible = valid_identity and _integration_scope_matches(integration_scopes, mapping)
                analytics_visible = mapping.store_id in visible_tiktok_store_ids
                if integration_visible and analytics_visible:
                    maps_by_store[mapping.store_id].append(mapping)
                else:
                    # Hidden mappings cannot be silently omitted from a store total.
                    invisible_stores.add(mapping.store_id)

            rates = tenant_cny_rates(user.tenant)
            expected = {}
            for store in tiktok:
                mapped = maps_by_store.get(store["id"], [])
                for day in days:
                    if not mapped or store["id"] in invisible_stores:
                        continue
                    if any((m.currency != store["currency"] and
                            (not _saved_rate(rates, m.currency) or not _saved_rate(rates, store["currency"])))
                           or not _timezone_days_match(
                            m.timezone, store.get("timezone"), start, end) for m in mapped):
                        continue
                    expected[(store["id"], day)] = mapped
            expected_mappings = [mapping for mappings in expected.values() for mapping in mappings]
            # The shared selector applies the verified GMV Max preference per mapping for
            # the entire window, then falls back to stored auction days where appropriate.
            selected_rows = preferred_tiktok_days(user, expected_mappings, start, end)
            selected_by_mapping_day = defaultdict(list)
            for row in selected_rows:
                selected_by_mapping_day[(row["mapping_id"], date.fromisoformat(row["date"]))].append(row)
            for (store_id, day), mapped in expected.items():
                spend = 0
                complete = True
                for mapping in mapped:
                    selected = selected_by_mapping_day.get((mapping.pk, day), [])
                    if len(selected) != 1:
                        complete = False
                        break
                    row = selected[0]
                    if (row.get("cost") is None or row.get("currency") != mapping.currency
                            or not _timezone_days_match(row.get("timezone"), mapping.timezone, day, day)):
                        complete = False
                        break
                    source_rate = _saved_rate(rates, mapping.currency)
                    target_rate = _saved_rate(rates, selected_by_id[store_id]["currency"])
                    try:
                        cost = Decimal(str(row["cost"]))
                        if not cost.is_finite() or cost < 0:
                            complete = False
                            break
                        if mapping.currency == selected_by_id[store_id]['currency']:
                            spend += cost
                        elif source_rate is not None and target_rate is not None:
                            spend += cost / source_rate * target_rate
                        else:
                            complete = False
                            break
                    except (InvalidOperation, TypeError, ValueError):
                        complete = False
                        break
                if complete:
                    spend_by_store_day[(store_id, day)] = spend
    except Exception as exc:
        # Invalid or unavailable scope/source fails closed as missing data.
        from apps.common.exceptions import DataScopeDenied
        if isinstance(exc, DataScopeDenied):
            return ("forbidden", result, {}) if comparison else ("forbidden", result)
        if not isinstance(exc, (DatabaseError, ValidationError, GMVMaxSnapshotOverflow)):
            raise
        return ("available", result, {}) if comparison else ("available", result)

    for currency, currency_stores in currencies.items():
        for day in days:
            values = [spend_by_store_day.get((store["id"], day)) for store in currency_stores]
            if values and all(value is not None for value in values):
                result[(currency, day.isoformat())] = sum(values)
    if not comparison:
        return "available", result

    ad_comparison = {}
    for currency, currency_stores in currencies.items():
        total = len(currency_stores)
        for index in range(1, len(days)):
            previous, current = days[index - 1], days[index]
            shared = [store for store in currency_stores
                      if spend_by_store_day.get((store["id"], previous)) is not None
                      and spend_by_store_day.get((store["id"], current)) is not None]
            covered = len(shared)
            ad_comparison[(currency, current.isoformat())] = ({
                "current": str(sum(spend_by_store_day[(store["id"], current)] for store in shared)) if covered else None,
                "previous": str(sum(spend_by_store_day[(store["id"], previous)] for store in shared)) if covered else None,
                "covered_stores": covered,
                "total_stores": total,
            } if covered else None)
    return "available", result, ad_comparison
