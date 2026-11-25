"""Bounded, country-scoped ABC snapshot calculation.

Facts are aggregated by the database; only grouped SKU/currency/day rows are
materialized in Python. A partial run is explicitly a reference snapshot and
never advances the official ABC grade stability state.
"""

from collections import defaultdict
from heapq import merge as merge_sorted
from itertools import groupby
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from django.db.models import Min, Sum, F, Q, Value, DecimalField, DateField, DateTimeField, ExpressionWrapper, Case, When
from django.db.models.functions import Cast, Coalesce
from django.utils import timezone

from apps.commerce.models import RefundReturn, RefundReturnItem, SalesOrder, SalesOrderItem, SalesOrderBundleSnapshot
from apps.integrations.models import HistorySyncSegment
from apps.masterdata.models import DailyExchangeRateSnapshot, StoreMaster
from apps.masterdata.models import InventoryABCEntry, InventoryABCRun, InventoryObservationSettings
from apps.products.models import ProductSPU, ProductSKU
from apps.sales_management.abc_ranking import rank_entities, transition_grade
from apps.sales_management.composite_rules import evaluate_comprehensive_abc
from apps.sales_management.inventory_queries import eligible_inventory_orders, prefer_sales_order_time
from apps.sales_management.scopes import filter_sales_queryset


ZERO = Decimal("0")
ABC_POLICY_VERSION = "composite_revenue_units_v1_20261120"
VALID_ORDER_STATES = ("confirmed", "fulfilled", "completed")


def _decimal(value):
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("invalid monetary amount") from exc
    if not result.is_finite():
        raise ValueError("non-finite monetary amount")
    return result


def _rate(rates, currency):
    """Return a positive currency-per-CNY quote, or None when absent/invalid."""
    try:
        value = _decimal(rates.get(currency))
    except (AttributeError, ValueError):
        return None
    return value if value > 0 else None


def _to_target(amount, source_currency, target_currency, rates):
    amount = _decimal(amount)
    source_currency = (source_currency or "").strip().upper()
    target_currency = (target_currency or "").strip().upper()
    if not source_currency or not target_currency:
        return None
    if source_currency == target_currency:
        return amount
    source_rate = _rate(rates, source_currency)
    target_rate = _rate(rates, target_currency)
    if source_rate is None or target_rate is None:
        return None
    return amount / source_rate * target_rate


def _valid_order_source():
    return Q(source_run__status="success", source_run__failed_count=0) | Q(internal_sync_batch__status__in=["success", "completed"])


def _eligible_orders(actor, store_ids, start=None, end=None, include_unverified=False):
    rows = SalesOrder.objects.filter(
        tenant_id=actor.tenant_id,
        store_id__in=store_ids,
        paid_at_utc__isnull=False,
        normalized_status__in=VALID_ORDER_STATES,
    )
    if not include_unverified:
        rows = rows.filter(_valid_order_source())
    if start is not None:
        rows = rows.filter(created_at_utc__gte=start)
    if end is not None:
        rows = rows.filter(created_at_utc__lt=end, paid_at_utc__lt=end)
    return prefer_sales_order_time(rows)

def _history_spans(tenant_id, store_ids, resource_type="sales_order"):
    spans = defaultdict(list)
    segments = HistorySyncSegment.objects.filter(
        batch__tenant_id=tenant_id,
        sync_job__resource_type=resource_type,
        sync_job__store_authorization__store_id__in=store_ids,
        status="success",
        runs__status="success",
        runs__failed_count=0,
    ).values_list("sync_job__store_authorization__store_id", "scope").distinct()
    for store_id, scope in segments:
        if not isinstance(scope, dict) or scope.get("time_basis") != "created":
            continue
        try:
            lower, upper = int(scope["time_from"]), int(scope["time_to"]) + 1
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if lower < upper:
            spans[store_id].append((lower, upper))
    for values in spans.values():
        values.sort()
    return spans


def _complete_history(start, end, spans):
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


def _refund_history_spans(tenant_id, store_platforms):
    store_ids = list(store_platforms)
    spans = defaultdict(list)
    segments = HistorySyncSegment.objects.filter(
        batch__tenant_id=tenant_id,
        sync_job__resource_type="refund_return",
        sync_job__store_authorization__store_id__in=store_ids,
        status="success",
        runs__status="success",
        runs__failed_count=0,
    ).values_list("sync_job__store_authorization__store_id", "scope").distinct()
    for store_id, scope in segments:
        platform = store_platforms.get(store_id, "")
        if not isinstance(scope, dict) or scope.get("time_basis") != "created":
            continue
        if platform == "shopee" and scope.get("_refund_history_policy") != "page20_day1_v1":
            continue
        if platform == "tiktok" and scope.get("_tiktok_refund_history_policy") != "page20_day1_v1":
            continue
        try:
            lower, upper = int(scope["time_from"]), int(scope["time_to"]) + 1
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if lower < upper:
            spans[store_id].append((lower, upper))
    for values in spans.values():
        values.sort()
    return spans


def _store_windows(store, cutoff_date, window_days):
    try:
        zone = ZoneInfo(store.timezone)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValueError(f"invalid timezone for store {store.pk}") from exc
    lower_day = cutoff_date - timedelta(days=window_days - 1)
    lower = datetime.combine(lower_day, time.min, tzinfo=zone)
    upper = datetime.combine(cutoff_date + timedelta(days=1), time.min, tzinfo=zone)
    return zone, lower, upper


def _local_day_expression(field, zone, lower, upper):
    """Group local business dates without MySQL named-timezone tables."""
    days = []
    day = lower.astimezone(zone).date()
    stop = upper.astimezone(zone).date()
    offsets = set()
    while day < stop:
        start = datetime.combine(day, time.min, tzinfo=zone)
        end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)
        days.append((day, start, end))
        for hour in (0, 6, 12, 18, 23):
            offsets.add(datetime.combine(day, time(hour), tzinfo=zone).utcoffset())
        day += timedelta(days=1)
    if len(offsets) == 1:
        shifted = ExpressionWrapper(F(field) + next(iter(offsets)), output_field=DateTimeField())
        return Cast(shifted, output_field=DateField())
    return Case(*[
        When(**{field + "__gte": start, field + "__lt": end}, then=Value(day))
        for day, start, end in days
    ], output_field=DateField())


def _group_sales(actor, store_ids, sku_ids, zone, lower, upper, first_sale=False, spu_ids=None):
    orders = _eligible_orders(actor, store_ids, lower, upper)
    source_unverified = _eligible_orders(actor, store_ids, lower, upper, include_unverified=True).exclude(_valid_order_source()).exists()
    with eligible_inventory_orders(orders) as eligible:
        items = SalesOrderItem.objects.filter(sales_order_id__in=eligible)
        unmapped = items.filter(internal_sku_id__isnull=True).exists()
        grouped = items.order_by().values("internal_sku_id", "currency").annotate(
            local_day=_local_day_expression("sales_order__created_at_utc", zone, lower, upper),
            amount=Sum("line_total_amount"),
        )
        grouped = grouped.filter(internal_sku_id__in=sku_ids).values_list(
            "internal_sku_id", "currency", "local_day", "amount"
        ).iterator(chunk_size=1000)
        rows = list(grouped)

    first, first_spus = {}, {}
    if first_sale:
        all_orders = _eligible_orders(actor, store_ids, end=upper)
        with eligible_inventory_orders(all_orders) as eligible_all:
            first_rows = SalesOrderItem.objects.filter(
                sales_order_id__in=eligible_all,
                internal_sku__spu_id__in=spu_ids or [],
            ).order_by().values("internal_sku_id", "internal_sku__spu_id").annotate(
                first_instant=Min("sales_order__paid_at_utc")
            ).values_list("internal_sku_id", "internal_sku__spu_id", "first_instant").iterator(chunk_size=1000)
            allowed_skus = set(sku_ids)
            for sku_id, spu_id, instant in first_rows:
                if instant is None:
                    continue
                day = instant.astimezone(zone).date()
                if sku_id in allowed_skus:
                    first[sku_id] = day
                first_spus[spu_id] = min(first_spus.get(spu_id, day), day)
            direct_spus = SalesOrderItem.objects.filter(
                sales_order_id__in=eligible_all, internal_sku__isnull=True,
                internal_spu_id__in=spu_ids or [],
            ).order_by().values("internal_spu_id").annotate(first_instant=Min("sales_order__paid_at_utc")).values_list("internal_spu_id", "first_instant")
            for spu_id, instant in direct_spus:
                if instant is not None:
                    day = instant.astimezone(zone).date()
                    first_spus[spu_id] = min(first_spus.get(spu_id, day), day)
    return rows, unmapped, first, first_spus, source_unverified


def _group_refunds(actor, store_ids, sku_ids, zone, lower, upper):
    parents = RefundReturn.objects.filter(
        tenant_id=actor.tenant_id,
        store_id__in=store_ids,
        requested_at_utc__gte=lower,
        requested_at_utc__lt=upper,
        normalized_status="completed",
        source_run__status="success",
        source_run__failed_count=0,
    )
    allocated = parents.annotate(allocated_total=Coalesce(Sum("items__refund_amount"), Value(ZERO), output_field=DecimalField(max_digits=24, decimal_places=4)))
    tolerance = Decimal("0.0001")
    unallocated = allocated.filter(
        Q(refund_subtotal__gt=F("allocated_total") + tolerance)
        | Q(refund_amount__gt=F("allocated_total") + F("refund_shipping_fee") + F("refund_tax") + tolerance)
        | Q(allocated_total__gt=F("refund_amount") + tolerance)
    ).exists()
    refund_items = RefundReturnItem.objects.filter(refund_return_id__in=parents)
    unmapped = refund_items.filter(internal_sku_id__isnull=True, refund_amount__gt=0).exists()
    grouped = refund_items.filter(internal_sku_id__in=sku_ids).order_by().values(
        "internal_sku_id", "currency"
    ).annotate(
        local_day=_local_day_expression("refund_return__requested_at_utc", zone, lower, upper),
        amount=Sum("refund_amount"),
    ).values_list("internal_sku_id", "currency", "local_day", "amount")
    return list(grouped.iterator(chunk_size=1000)), unallocated, unmapped


def _load_rates(tenant_id, dates):
    return dict(DailyExchangeRateSnapshot.objects.filter(
        tenant_id=tenant_id, rate_date__in=dates
    ).values_list("rate_date", "rates"))


def _previous_entries(tenant_id, country_id, cutoff_date, config):
    previous_run = InventoryABCRun.objects.filter(
        tenant_id=tenant_id,
        country_id=country_id,
        status="ready",
        cutoff_date__lte=cutoff_date,
        config__classification_basis=config["classification_basis"],
        config__policy_version=config["policy_version"],
    ).order_by("-cutoff_date", "-pk").first()
    if not previous_run:
        return {}
    comparable = (
        "window_days",
        "a_percent",
        "b_percent",
        "stability_days",
        "new_product_observation_days",
        "first_sale_basis",
        "revenue_source",
        "refund_source",
        "currency_conversion",
    )
    same_basis = all(previous_run.config.get(key) == config.get(key) for key in comparable)
    if not same_basis:
        return {}
    return {
        (entry.entity_type, entry.entity_id): {
            "grade": entry.grade,
            "candidate_grade": entry.candidate_grade if same_basis else "",
            "candidate_streak": entry.candidate_streak if same_basis else 0,
            "cutoff_date": previous_run.cutoff_date,
            "changed_at": entry.changed_at,
        }
        for entry in previous_run.entries.all()
    }


def _bundle_component_order_facts(actor, bundle_items, requested_skus, zone):
    """Yield exact immutable bundle component quantities grouped by order and SKU."""
    if not bundle_items:
        return [], True
    order_item_ids = [row["id"] for row in bundle_items]
    snapshots = {
        row.order_item_id: row for row in SalesOrderBundleSnapshot.objects.filter(
            tenant_id=actor.tenant_id, order_item_id__in=order_item_ids
        ).select_related("order_item__sales_order", "bundle_version", "bundle_version__bundle_sku").only(
            "tenant_id", "order_item_id", "bundle_version_id", "components_payload",
            "order_item__sales_order__tenant_id", "bundle_version__tenant_id",
            "bundle_version__bundle_sku_id", "bundle_version__effective_at",
            "bundle_version__bundle_sku__tenant_id", "bundle_version__bundle_sku__product_type",
        )
    }
    component_payloads = []
    component_ids = set()
    complete = True
    for item in bundle_items:
        snapshot = snapshots.get(item["id"])
        if not snapshot:
            # Never use today's mutable bundle recipe to reconstruct old demand.
            complete = False
            continue
        order_tenant = item["sales_order__tenant_id"]
        bundle_id = item["internal_sku_id"]
        if (
            snapshot.tenant_id != order_tenant
            or snapshot.order_item.sales_order.tenant_id != order_tenant
            or snapshot.bundle_version.tenant_id != order_tenant
            or snapshot.bundle_version.bundle_sku_id != bundle_id
            or snapshot.bundle_version.effective_at > item["sales_order__created_at_utc"]
            or snapshot.bundle_version.bundle_sku.tenant_id != order_tenant
            or snapshot.bundle_version.bundle_sku.product_type != "bundle"
        ):
            complete = False
            continue
        payload = snapshot.components_payload
        if not isinstance(payload, list) or not payload:
            complete = False
            continue
        seen = set()
        parsed = []
        valid = True
        for component in payload:
            if not isinstance(component, dict):
                valid = False
                break
            component_id, quantity = component.get("component_sku_id"), component.get("quantity")
            if (
                type(component_id) is not int or component_id <= 0
                or type(quantity) is not int or quantity <= 0
                or component_id in seen or component_id == bundle_id
            ):
                valid = False
                break
            seen.add(component_id)
            parsed.append((component_id, quantity))
        if not valid:
            complete = False
            continue
        component_payloads.append((item, parsed))
        component_ids.update(component_id for component_id, _ in parsed)

    valid_components = set(ProductSKU.objects.filter(
        tenant_id=actor.tenant_id, pk__in=component_ids, product_type="standard"
    ).values_list("pk", flat=True))
    facts = defaultdict(int)
    for item, components in component_payloads:
        if any(component_id not in valid_components for component_id, _ in components):
            complete = False
            continue
        day = item["sales_order__created_at_utc"].astimezone(zone).date()
        order_id = item["sales_order_id"]
        bundle_units = int(item["quantity"] or 0)
        for component_id, per_bundle in components:
            if component_id in requested_skus:
                facts[(order_id, component_id, day)] += bundle_units * per_bundle
    return [(*key, units) for key, units in sorted(facts.items())], complete


def _order_spu_totals(order_sku_units, spu_by_sku):
    """Sum sibling SKU units inside one order for exact SPU concentration."""
    totals = defaultdict(int)
    for sku_id, units in order_sku_units.items():
        spu_id = spu_by_sku.get(sku_id)
        if spu_id:
            totals[spu_id] += units
    return totals


def _quantity_facts(actor, store_ids, sku_ids, spu_by_sku, zone, cutoff_date, window_days):
    """Aggregate demand by local day and exact order with bounded streaming.

    SQL groups direct SKU quantity by order/SKU. Immutable bundle snapshots are
    read in 500-item chunks and merged into the ordered stream. Memory use is
    bounded by one chunk plus the SKU lines in one order, never all orders.
    """
    scan_days = max(window_days, 84)
    start = cutoff_date - timedelta(days=scan_days - 1)
    ranking_start = cutoff_date - timedelta(days=window_days - 1)
    lower = datetime.combine(start, time.min, tzinfo=zone)
    upper = datetime.combine(cutoff_date + timedelta(days=1), time.min, tzinfo=zone)
    orders = _eligible_orders(actor, store_ids, lower, upper)
    source_unverified = _eligible_orders(
        actor, store_ids, lower, upper, include_unverified=True
    ).exclude(_valid_order_source()).exists()
    requested = set(sku_ids)
    day_units = defaultdict(int)
    max_order_by_sku = defaultdict(int)
    max_order_by_spu = defaultdict(int)
    complete = not source_unverified

    with eligible_inventory_orders(orders) as eligible:
        source = SalesOrderItem.objects.filter(sales_order_id__in=eligible)
        # Preserve bundle SKU own sales; exclude only immutable component rows.
        direct = source.filter(internal_sku_id__in=sku_ids).exclude(
            (Q(bundle_snapshot__isnull=False) & ~Q(internal_sku__product_type="bundle"))
        ).order_by().values("sales_order_id", "internal_sku_id").annotate(
            local_day=_local_day_expression("sales_order__created_at_utc", zone, lower, upper),
            units=Sum("quantity"),
        ).order_by("sales_order_id", "internal_sku_id").values_list(
            "sales_order_id", "internal_sku_id", "local_day", "units"
        ).iterator(chunk_size=1000)

        bundle_source = source.filter(
            Q(internal_sku__product_type="bundle") | Q(bundle_snapshot__isnull=False)
        ).order_by("sales_order_id", "id").values(
            "id", "sales_order_id", "sales_order__tenant_id", "sales_order__created_at_utc",
            "internal_sku_id", "quantity",
        ).iterator(chunk_size=1000)

        def component_stream():
            nonlocal complete
            pending = []
            for item in bundle_source:
                pending.append(item)
                if len(pending) >= 500:
                    facts, verified = _bundle_component_order_facts(actor, pending, requested, zone)
                    complete = complete and verified
                    yield from facts
                    pending = []
            if pending:
                facts, verified = _bundle_component_order_facts(actor, pending, requested, zone)
                complete = complete and verified
                yield from facts

        direct_facts = (
            (order_id, sku_id, day, int(units or 0))
            for order_id, sku_id, day, units in direct
        )
        merged = merge_sorted(
            direct_facts, component_stream(), key=lambda row: row[0]
        )
        for order_id, facts in groupby(merged, key=lambda row: row[0]):
            order_skus = defaultdict(int)
            order_day = None
            for _, sku_id, day, units in facts:
                if day is None:
                    complete = False
                    continue
                order_day = day
                order_skus[sku_id] += int(units or 0)
            if order_day is None:
                continue
            for sku_id, units in order_skus.items():
                day_units[(sku_id, order_day)] += units
                if order_day >= ranking_start:
                    max_order_by_sku[sku_id] = max(max_order_by_sku[sku_id], units)
            order_spus = _order_spu_totals(order_skus, spu_by_sku)
            if order_day >= ranking_start:
                for spu_id, units in order_spus.items():
                    max_order_by_spu[spu_id] = max(max_order_by_spu[spu_id], units)

    return {
        "day_units": dict(day_units),
        "max_order_by_sku": dict(max_order_by_sku),
        "max_order_by_spu": dict(max_order_by_spu),
        "source_unverified": source_unverified,
        "history_complete": complete,
    }


def _aggregate_quantity_profile(day_units, spu_by_sku, cutoff_date, ranking_window_days):
    """Roll up country-wide daily demand; separate ranking from continuity dates."""
    sku_units = defaultdict(int)
    sku_active_weeks = defaultdict(set)
    sku_max_day = defaultdict(int)
    spu_day_units = defaultdict(lambda: defaultdict(int))
    window_start = cutoff_date - timedelta(days=ranking_window_days - 1)
    continuity_start = cutoff_date - timedelta(days=83)
    for (sku_id, day), units in day_units.items():
        if units <= 0:
            continue
        spu_id = spu_by_sku.get(sku_id)
        if day >= window_start:
            sku_units[sku_id] += units
            sku_max_day[sku_id] = max(sku_max_day[sku_id], units)
            if spu_id:
                spu_day_units[spu_id][day] += units
        if continuity_start <= day <= cutoff_date:
            sku_active_weeks[sku_id].add((cutoff_date - day).days // 7)
    spu_units = defaultdict(int)
    spu_active_weeks = defaultdict(set)
    spu_max_day = defaultdict(int)
    for sku_id, spu_id in spu_by_sku.items():
        spu_units[spu_id] += sku_units[sku_id]
        spu_active_weeks[spu_id].update(sku_active_weeks[sku_id])
    for spu_id, daily in spu_day_units.items():
        spu_max_day[spu_id] = max(daily.values(), default=0)
    return {
        "sku_units": sku_units,
        "sku_active_weeks": sku_active_weeks,
        "sku_max_day": sku_max_day,
        "spu_units": spu_units,
        "spu_active_weeks": spu_active_weeks,
        "spu_max_day": spu_max_day,
    }


def _ready_entry(entity_type, entity_id, revenue, rank, previous, cutoff_date, stable_days,
                 first_sale_date=None, new_observation_days=30):
    age_days = (cutoff_date - first_sale_date).days if first_sale_date else None
    if age_days is not None and 0 <= age_days < new_observation_days:
        old = previous.get((entity_type, entity_id)) or {}
        state = {
            "grade": "new",
            "candidate_grade": None,
            "candidate_streak": 0,
            "changed": old.get("grade") != "new",
        }
    else:
        old = previous.get((entity_type, entity_id))
        state = transition_grade(rank["grade"], old, cutoff_date, stable_days)
    return InventoryABCEntry(
        entity_type=entity_type,
        entity_id=entity_id,
        grade=state["grade"],
        candidate_grade=state.get("candidate_grade") or "",
        candidate_streak=state.get("candidate_streak", 0),
        revenue=revenue,
        share=rank["share"],
        cumulative_share=rank["cumulative_share"],
        first_sale_date=first_sale_date,
        changed_at=cutoff_date if state.get("changed") else (old.get("changed_at") if old else None),
    )


def calculate_country(actor, country, run=None):
    """Build one country ABC run and return the persisted run instance."""
    from apps.commerce import country_decisions as domain
    from apps.permissions.role_catalog import effective_administrator_bindings

    if not actor or not getattr(actor, "is_active", False) or getattr(actor, "user_type", None) != "internal":
        raise PermissionError("active internal user required")
    if not actor.is_superuser and not effective_administrator_bindings(actor.tenant).filter(user_id=actor.pk).exists():
        raise PermissionError("tenant administrator required")
    if getattr(country, "tenant_id", None) != actor.tenant_id:
        raise PermissionError("country tenant mismatch")
    from apps.permissions.ui_p2_scopes import require_all_scope
    require_all_scope(actor, domain.SALES)
    require_all_scope(actor, domain.INVENTORY)
    country = domain.country_for(actor, country.pk)
    settings_obj = InventoryObservationSettings.objects.filter(tenant_id=actor.tenant_id).first()
    if settings_obj and not settings_obj.abc_enabled:
        raise ValueError("ABC calculation is disabled")
    window_days = settings_obj.abc_window_days if settings_obj else 90
    a_percent = settings_obj.abc_a_percent if settings_obj else Decimal("80")
    b_percent = settings_obj.abc_b_percent if settings_obj else Decimal("95")
    stable_days = settings_obj.abc_stability_days if settings_obj else 3
    observation_days = settings_obj.new_product_observation_days if settings_obj else 30

    now = timezone.now()
    try:
        country_zone = ZoneInfo(country.timezone or "UTC")
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValueError("invalid country timezone") from exc
    cutoff = run.cutoff_date if run else now.astimezone(country_zone).date() - timedelta(days=1)
    if run is None:
        run = InventoryABCRun.objects.create(
            tenant_id=actor.tenant_id,
            country=country,
            cutoff_date=cutoff,
            window_days=window_days,
            currency=(country.currency or "").strip().upper(),
            status="queued",
        )
    if run.tenant_id != actor.tenant_id or run.country_id != country.pk:
        raise PermissionError("run scope mismatch")
    if run.status not in {"queued", "building"}:
        raise ValueError("only queued or interrupted building runs can be calculated")

    run.status = "building"
    run.window_days = window_days
    run.currency = (country.currency or "").strip().upper()
    run.config = {
        **(run.config if isinstance(run.config, dict) else {}),
        "window_days": window_days,
        "classification_basis": "composite",
        "policy_version": ABC_POLICY_VERSION,
        "a_percent": str(_decimal(a_percent).quantize(Decimal("0.01"))),
        "b_percent": str(_decimal(b_percent).quantize(Decimal("0.01"))),
        "stability_days": stable_days,
        "new_product_observation_days": observation_days,
        "cutoff_date": str(cutoff),
        "revenue_source": "sales_order_item.line_total_amount",
        "first_sale_basis": "first_valid_paid_at_store_local",
        "refund_source": "completed_refund_return_item.refund_amount",
        "currency_conversion": "daily_snapshot_currency_per_cny",
        "computed_by": actor.pk,
    }
    run.issues = []
    run.save(update_fields=["status", "window_days", "currency", "config", "issues"])

    try:
        skus = list(domain.skus_for(actor, country).values("id", "spu_id"))
        sku_ids = [row["id"] for row in skus]
        spu_by_sku = {row["id"]: row["spu_id"] for row in skus if row["spu_id"]}
        sales_store_qs = filter_sales_queryset(
            actor,
            domain.SALES,
            StoreMaster.objects.filter(
                tenant_id=actor.tenant_id,
                country_code__iexact=country.country_code,
                status="active",
            ).select_related("platform"),
            {"store_ids": "id", "platforms": "platform__platform_type", "regions": "country_code"},
        )
        stores = list(sales_store_qs)
        if not stores:
            raise ValueError("no_authorized_active_sales_store")

        history = _history_spans(actor.tenant_id, [store.pk for store in stores])
        refund_history = _refund_history_spans(
            actor.tenant_id, {store.pk: store.platform.platform_type for store in stores}
        )
        issues = []
        sales_amounts = defaultdict(Decimal)
        refund_amounts = defaultdict(Decimal)
        first_sale_dates = {}
        country_spu_first_sales = {}
        fx_required = set()

        grouped_stores = defaultdict(list)
        store_windows = {}
        for store in stores:
            zone, lower, upper = _store_windows(store, cutoff, window_days)
            if cutoff >= timezone.now().astimezone(zone).date():
                issues.append(f"unfinished_store_day:{store.pk}")
            if not _complete_history(lower, upper, history[store.pk]):
                issues.append(f"sales_history_incomplete:{store.pk}")
            if not _complete_history(lower, upper, refund_history[store.pk]):
                issues.append(f"refund_history_incomplete:{store.pk}")
            grouped_stores[(store.timezone, cutoff)].append(store.pk)
            store_windows[store.pk] = (zone, lower, upper)

        for store_ids in grouped_stores.values():
            zone, lower, upper = store_windows[store_ids[0]]
            sales_rows, unmapped, first_sales, first_spus, source_unverified = _group_sales(
                actor, store_ids, sku_ids, zone, lower, upper, first_sale=True, spu_ids=set(spu_by_sku.values())
            )
            if source_unverified:
                issues.append(f"sales_source_unverified:{store_ids[0]}")
            if unmapped:
                issues.append(f"unmapped_sales:{','.join(map(str, store_ids[:20]))}")
            for spu_id, first_day in first_spus.items():
                country_spu_first_sales[spu_id] = min(country_spu_first_sales.get(spu_id, first_day), first_day)
            for sku_id, first_day in first_sales.items():
                if first_day and (sku_id not in first_sale_dates or first_day < first_sale_dates[sku_id]):
                    first_sale_dates[sku_id] = first_day
            for sku_id, currency, day, amount in sales_rows:
                if day is None:
                    issues.append(f"sales_day_missing:{','.join(map(str, store_ids[:20]))}")
                    continue
                key = (sku_id, str(currency or "").upper(), day)
                sales_amounts[key] += _decimal(amount or ZERO)
                if key[1] and key[1] != run.currency:
                    fx_required.add(day)

            refund_rows, unallocated, unmapped_refund = _group_refunds(
                actor, store_ids, sku_ids, zone, lower, upper
            )
            if unallocated:
                issues.append(f"unallocated_refund:{','.join(map(str, store_ids[:20]))}")
            if unmapped_refund:
                issues.append(f"unmapped_refund:{','.join(map(str, store_ids[:20]))}")
            for sku_id, currency, day, amount in refund_rows:
                if day is None:
                    issues.append(f"refund_day_missing:{','.join(map(str, store_ids[:20]))}")
                    continue
                key = (sku_id, str(currency or "").upper(), day)
                refund_amounts[key] += _decimal(amount or ZERO)
                if key[1] and key[1] != run.currency:
                    fx_required.add(day)

        rates_by_day = _load_rates(actor.tenant_id, fx_required)
        sku_revenue = {sku_id: ZERO for sku_id in sku_ids}
        missing_fx = set()
        for key in set(sales_amounts) | set(refund_amounts):
            sku_id, currency, day = key
            amount = sales_amounts[key] - refund_amounts[key]
            if amount == ZERO:
                continue
            if amount == 0:
                continue
            if currency == run.currency:
                converted = amount
            else:
                converted = _to_target(amount, currency, run.currency, rates_by_day.get(day, {}))
                if converted is None:
                    missing_fx.add((currency, day))
                    continue
            sku_revenue[sku_id] += converted
        if missing_fx:
            issues.append(f"missing_fx_pairs:{len(missing_fx)}")

        # Persist only the country's actual sales, stock or listing population.
        # An unrelated catalog SKU does not become a zero-sales SKU here.
        from apps.sales_management.category_inventory import stock_facts
        from apps.commerce.inventory_listing import linked_sku_ids
        stock_ids = {fact["internal_sku_id"] for fact in stock_facts(actor, country, {}) if fact["internal_sku_id"] is not None}
        listed_ids = linked_sku_ids(actor.tenant_id, country.country_code, sku_ids)
        # Verified immutable bundle history is also country sales evidence.
        # Discover it before narrowing the catalog, including components with no
        # direct order, current stock or listing. Never consult today's recipe.
        bundle_first_sales = {}
        requested_components = set(sku_ids)
        for store_ids in grouped_stores.values():
            zone, _, _ = store_windows[store_ids[0]]
            upper = datetime.combine(cutoff + timedelta(days=1), time.min, tzinfo=zone)
            orders = _eligible_orders(actor, store_ids, None, upper)
            with eligible_inventory_orders(orders) as eligible:
                source = SalesOrderItem.objects.filter(
                    sales_order_id__in=eligible, bundle_snapshot__isnull=False,
                ).order_by("id")
                last_id = 0
                while True:
                    # LIMIT bounds MySQL's buffered result, unlike iterator alone.
                    items = list(source.filter(id__gt=last_id).values(
                        "id", "sales_order_id", "sales_order__tenant_id", "sales_order__created_at_utc",
                        "sales_order__paid_at_utc", "internal_sku_id", "quantity",
                    )[:500])
                    if not items:
                        break
                    last_id = items[-1]["id"]
                    paid_days = {item["sales_order_id"]: item["sales_order__paid_at_utc"].astimezone(zone).date() for item in items}
                    facts, _ = _bundle_component_order_facts(actor, items, requested_components, zone)
                    for order_id, component_id, _, units in facts:
                        day = paid_days[order_id]
                        if units > 0 and (component_id not in bundle_first_sales or day < bundle_first_sales[component_id]):
                            bundle_first_sales[component_id] = day
        for sku_id, day in bundle_first_sales.items():
            if sku_id not in first_sale_dates or day < first_sale_dates[sku_id]:
                first_sale_dates[sku_id] = day
        relevant_ids = set(first_sale_dates) | stock_ids | set(listed_ids)
        relevant_ids.update(key[0] for key in sales_amounts)
        relevant_ids.update(key[0] for key in refund_amounts)
        sku_ids = [sku_id for sku_id in sku_ids if sku_id in relevant_ids]
        spu_by_sku = {sku_id: spu_id for sku_id, spu_id in spu_by_sku.items() if sku_id in relevant_ids}
        sku_revenue = {sku_id: amount for sku_id, amount in sku_revenue.items() if sku_id in relevant_ids}

        sku_candidates = []
        for sku_id in sku_ids:
            amount = max(sku_revenue[sku_id], ZERO)
            first_sale = first_sale_dates.get(sku_id)
            age_days = (cutoff - first_sale).days if first_sale else None
            is_mature = age_days is not None and age_days >= observation_days
            if amount > 0 and is_mature:
                sku_candidates.append({"id": sku_id, "amount": amount})
        sku_ranks = rank_entities(sku_candidates, a_percent, b_percent)

        country_day_units = defaultdict(int)
        country_max_order_sku = defaultdict(int)
        country_max_order_spu = defaultdict(int)
        quantity_complete = True
        quantity_source_unverified = False
        continuity_days = max(window_days, 84)
        continuity_lower = cutoff - timedelta(days=continuity_days - 1)
        for store_ids in grouped_stores.values():
            zone, _, _ = store_windows[store_ids[0]]
            for store_id in store_ids:
                if not _complete_history(
                    datetime.combine(continuity_lower, time.min, tzinfo=zone),
                    datetime.combine(cutoff + timedelta(days=1), time.min, tzinfo=zone),
                    history[store_id],
                ):
                    quantity_complete = False
                    issues.append(f"continuity_history_incomplete:{store_id}")
            day_facts = _quantity_facts(actor, store_ids, sku_ids, spu_by_sku, zone, cutoff, window_days)
            quantity_complete = quantity_complete and day_facts["history_complete"]
            quantity_source_unverified = quantity_source_unverified or day_facts["source_unverified"]
            for key, units in day_facts["day_units"].items():
                country_day_units[key] += units
            for sku_id, units in day_facts["max_order_by_sku"].items():
                country_max_order_sku[sku_id] = max(country_max_order_sku[sku_id], units)
            for spu_id, units in day_facts["max_order_by_spu"].items():
                country_max_order_spu[spu_id] = max(country_max_order_spu[spu_id], units)
        if quantity_source_unverified:
            issues.append("continuity_source_unverified")
        quantity_profile = _aggregate_quantity_profile(country_day_units, spu_by_sku, cutoff, window_days)
        sku_units = quantity_profile["sku_units"]
        sku_active_weeks = quantity_profile["sku_active_weeks"]
        sku_max_day = quantity_profile["sku_max_day"]
        spu_units = quantity_profile["spu_units"]
        spu_active_weeks = quantity_profile["spu_active_weeks"]
        spu_max_day = quantity_profile["spu_max_day"]
        if not quantity_complete:
            issues.append("bundle_quantity_or_sales_day_unverified")
        mature_sku_ids = {
            sku_id for sku_id in sku_ids
            if (first_sale_dates.get(sku_id) is not None
                and (cutoff - first_sale_dates[sku_id]).days >= observation_days)
        }
        sku_unit_ranks = rank_entities(
            [{"id": sku_id, "amount": sku_units[sku_id]} for sku_id in mature_sku_ids if sku_units[sku_id] > 0],
            a_percent, b_percent,
        )

        spu_revenue = defaultdict(Decimal)
        for sku_id, spu_id in spu_by_sku.items():
            spu_revenue[spu_id] += sku_revenue[sku_id]
        active_spus = list(ProductSPU.objects.filter(
            tenant_id=actor.tenant_id,
            pk__in=set(spu_by_sku.values()),
        ).values_list("id", flat=True))
        spu_first_sale = dict(country_spu_first_sales)
        for sku_id, spu_id in spu_by_sku.items():
            first_sale = first_sale_dates.get(sku_id)
            if first_sale and (spu_id not in spu_first_sale or first_sale < spu_first_sale[spu_id]):
                spu_first_sale[spu_id] = first_sale
        established_spus = []
        for spu_id in active_spus:
            first_sale = spu_first_sale.get(spu_id)
            age_days = (cutoff - first_sale).days if first_sale else None
            if age_days is not None and age_days >= observation_days:
                established_spus.append(spu_id)
        spu_ranks = rank_entities(
            [{"id": spu_id, "amount": max(spu_revenue[spu_id], ZERO)} for spu_id in established_spus],
            a_percent,
            b_percent,
        )

        all_issues = list(dict.fromkeys(issues))
        is_complete = not all_issues and quantity_complete
        previous = _previous_entries(actor.tenant_id, country.pk, cutoff, run.config) if is_complete else {}
        entries = []
        spu_unit_ranks = rank_entities(
            [{"id": spu_id, "amount": spu_units[spu_id]} for spu_id in established_spus if spu_units[spu_id] > 0],
            a_percent, b_percent,
        )

        def build_entry(entity_type, entity_id, amount, revenue_rank, units_rank, units,
                        active_weeks, max_day, max_order, first_sale):
            age_days = (cutoff - first_sale).days if first_sale else None
            maturity = "new" if age_days is not None and 0 <= age_days < observation_days else (
                "mature" if age_days is not None and age_days >= observation_days else "unknown"
            )
            if maturity != "mature":
                revenue_rank = {"grade": "unavailable", "share": ZERO, "cumulative_share": ZERO}
                units_rank = {"grade": "unavailable", "share": ZERO, "cumulative_share": ZERO}
            rev_grade = revenue_rank.get("grade", "no_sales")
            unit_grade = units_rank.get("grade", "no_sales")
            weeks = sorted(active_weeks)
            weeks12 = len(weeks)
            weeks4 = sum(1 for week in weeks if week < 4)
            observation_complete = is_complete and quantity_complete
            result = evaluate_comprehensive_abc(
                revenue_grade=rev_grade,
                units_grade=unit_grade,
                active_weeks_last12=weeks12,
                active_weeks_last4=weeks4,
                history_complete=observation_complete,
                maturity=maturity,
                total_units=units,
                max_single_order_units=max_order,
                max_single_day_units=max_day,
            )
            official_candidate = result["grade"] if is_complete else "unavailable"
            reference_grade = result.get("reference_grade", "unavailable")
            rank_for_stability = {**revenue_rank, "grade": official_candidate}
            if is_complete:
                entry = _ready_entry(
                    entity_type, entity_id, amount, rank_for_stability, previous, cutoff, stable_days,
                    first_sale_date=first_sale, new_observation_days=observation_days,
                )
                # Composite labels are stabilized across the existing consecutive
                # cutoff days. Preserve composite facts independently of revenue shares.
                if official_candidate == "unavailable":
                    entry.grade = "unavailable"
                    entry.candidate_grade = reference_grade if reference_grade != "unavailable" else ""
                    entry.candidate_streak = 0
                elif official_candidate == "no_sales":
                    entry.grade = "no_sales"
                    entry.candidate_grade = ""
                    entry.candidate_streak = 0
            else:
                entry = InventoryABCEntry(
                    entity_type=entity_type, entity_id=entity_id, grade="unavailable",
                    candidate_grade=reference_grade if reference_grade not in {"unavailable", "no_sales"} else "",
                    candidate_streak=0, revenue=amount, share=revenue_rank.get("share", ZERO),
                    cumulative_share=revenue_rank.get("cumulative_share", ZERO), first_sale_date=first_sale,
                )
            entry.revenue = amount
            entry.share = revenue_rank.get("share", ZERO)
            entry.cumulative_share = revenue_rank.get("cumulative_share", ZERO)
            entry.evidence = {
                **result.get("basis", {}),
                "classification_basis": "composite",
                "policy_version": ABC_POLICY_VERSION,
                "revenue_grade": rev_grade,
                "units_grade": unit_grade,
                "units_total": int(units),
                "units_share": str(units_rank.get("share", ZERO)),
                "units_cumulative_share": str(units_rank.get("cumulative_share", ZERO)),
                "continuity_label": (
                    "suspected_concentration"
                    if result.get("basis", {}).get("single_order_share_anomaly")
                    or result.get("basis", {}).get("single_day_share_anomaly")
                    else "sustained"
                    if result.get("basis", {}).get("sustained")
                    else "intermittent_or_unproven"
                ),
                "reasons": result.get("reason_codes", []),
                "reference_grade": reference_grade,
                "max_order_method": "exact_order_aggregate",
                "continuity_window_days": continuity_days,
                "continuity_lower_date": str(continuity_lower),
            }
            return entry

        for sku_id in sku_ids:
            amount = max(sku_revenue[sku_id], ZERO)
            revenue_rank = sku_ranks.get(sku_id, {"grade": "no_sales", "share": ZERO, "cumulative_share": ZERO})
            units_rank = sku_unit_ranks.get(sku_id, {"grade": "no_sales", "share": ZERO, "cumulative_share": ZERO})
            entries.append(build_entry("sku", sku_id, amount, revenue_rank, units_rank,
                                       sku_units[sku_id], sku_active_weeks[sku_id], sku_max_day[sku_id],
                                       country_max_order_sku[sku_id], first_sale_dates.get(sku_id)))
        for spu_id in active_spus:
            amount = max(spu_revenue[spu_id], ZERO)
            revenue_rank = spu_ranks.get(spu_id, {"grade": "no_sales", "share": ZERO, "cumulative_share": ZERO})
            units_rank = spu_unit_ranks.get(spu_id, {"grade": "no_sales", "share": ZERO, "cumulative_share": ZERO})
            entries.append(build_entry("spu", spu_id, amount, revenue_rank, units_rank,
                                       spu_units[spu_id], spu_active_weeks[spu_id], spu_max_day[spu_id],
                                       country_max_order_spu[spu_id], spu_first_sale.get(spu_id)))

        net_total = sum((max(value, ZERO) for value in sku_revenue.values()), ZERO)
        with transaction.atomic():
            InventoryABCEntry.objects.filter(run=run).delete()
            for entry in entries:
                entry.run_id = run.pk
            InventoryABCEntry.objects.bulk_create(entries, batch_size=1000)
            run.status = "ready" if is_complete else "partial"
            run.issues = all_issues
            run.net_total = net_total
            run.completed_at = timezone.now()
            run.save(update_fields=["status", "issues", "net_total", "completed_at"])
        return run
    except Exception as exc:
        run.status = "failed"
        run.issues = [f"calculation_error:{type(exc).__name__}"]
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "issues", "completed_at"])
        raise
