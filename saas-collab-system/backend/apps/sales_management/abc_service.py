"""Bounded, country-scoped ABC snapshot calculation.

Facts are aggregated by the database; only grouped SKU/currency/day rows are
materialized in Python. A partial run is explicitly a reference snapshot and
never advances the official ABC grade stability state.
"""

from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from django.db.models import Min, Sum, F, Q, Value, DecimalField, DateField, DateTimeField, ExpressionWrapper, Case, When
from django.db.models.functions import Cast, Coalesce
from django.utils import timezone

from apps.commerce.models import RefundReturn, RefundReturnItem, SalesOrder, SalesOrderItem
from apps.integrations.models import HistorySyncSegment
from apps.masterdata.models import DailyExchangeRateSnapshot, StoreMaster
from apps.masterdata.models import InventoryABCEntry, InventoryABCRun, InventoryObservationSettings
from apps.products.models import ProductSPU
from apps.sales_management.abc_ranking import rank_entities, transition_grade
from apps.sales_management.inventory_queries import eligible_inventory_orders, prefer_sales_order_time
from apps.sales_management.scopes import filter_sales_queryset


ZERO = Decimal("0")
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
            is_new = age_days is not None and 0 <= age_days < observation_days
            if amount > 0 and not is_new:
                sku_candidates.append({"id": sku_id, "amount": amount})
        sku_ranks = rank_entities(sku_candidates, a_percent, b_percent)

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
            if not (age_days is not None and 0 <= age_days < observation_days):
                established_spus.append(spu_id)
        spu_ranks = rank_entities(
            [{"id": spu_id, "amount": max(spu_revenue[spu_id], ZERO)} for spu_id in established_spus],
            a_percent,
            b_percent,
        )

        all_issues = list(dict.fromkeys(issues))
        is_complete = not all_issues
        previous = _previous_entries(actor.tenant_id, country.pk, cutoff, run.config) if is_complete else {}
        entries = []
        for sku_id in sku_ids:
            amount = max(sku_revenue[sku_id], ZERO)
            first_sale = first_sale_dates.get(sku_id)
            age_days = (cutoff - first_sale).days if first_sale else None
            is_new = age_days is not None and 0 <= age_days < observation_days
            rank = sku_ranks.get(sku_id, {"grade": "new" if is_new else "no_sales", "share": ZERO, "cumulative_share": ZERO})
            if is_complete:
                entry = _ready_entry(
                    "sku", sku_id, amount, rank, previous, cutoff, stable_days,
                    first_sale_date=first_sale,
                    new_observation_days=observation_days,
                )
            else:
                entry = InventoryABCEntry(
                    entity_type="sku", entity_id=sku_id, grade="unavailable",
                    candidate_grade=rank["grade"] if rank["grade"] in {"A", "B", "C", "new"} else "",
                    candidate_streak=0, revenue=amount, share=rank["share"],
                    cumulative_share=rank["cumulative_share"], first_sale_date=first_sale,
                )
            entries.append(entry)
        for spu_id in active_spus:
            amount = max(spu_revenue[spu_id], ZERO)
            first_sale = spu_first_sale.get(spu_id)
            rank = spu_ranks.get(spu_id, {"grade": "new", "share": ZERO, "cumulative_share": ZERO})
            if is_complete:
                entry = _ready_entry("spu", spu_id, amount, rank, previous, cutoff, stable_days,
                                     first_sale_date=first_sale, new_observation_days=observation_days)
            else:
                entry = InventoryABCEntry(
                    entity_type="spu", entity_id=spu_id, grade="unavailable",
                    candidate_grade=rank["grade"] if rank["grade"] in {"A", "B", "C", "new"} else "",
                    candidate_streak=0, revenue=amount, share=rank["share"],
                    cumulative_share=rank["cumulative_share"],
                    first_sale_date=first_sale,
                )
            entries.append(entry)

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
