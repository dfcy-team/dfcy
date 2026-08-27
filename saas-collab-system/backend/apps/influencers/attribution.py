"""Safe, tenant-scoped affiliate facts and BD attribution helpers."""

from collections import defaultdict
from bisect import bisect_right
from datetime import datetime, time, timedelta, timezone as dt_timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework.exceptions import ValidationError

from .models import (
    AffiliateImportState,
    AffiliateOrderRevision,
    AffiliateOrderSnapshot,
    BdOrderAttributionSnapshot,
    BdSampleAttributionSnapshot,
    ExchangeRate,
    OutreachTask,
    SampleFulfillment,
    SUPPORTED_CURRENCY_CHOICES,
    normalize_tiktok_username,
)


BD_ATTRIBUTION_RULE_VERSION = "bd-attribution-v1"
RATE_SELECTION_VERSION = "tenant-exchange-rate-effective-from-desc-id-desc-v1"
RATE_SOURCE_DESCRIPTION = (
    "Tenant ExchangeRate; CNY uses identity rate 1; other currencies use the latest "
    "active base_currency->CNY rate effective on the business date."
)
PERFORMANCE_CURRENCIES = frozenset(currency for currency, _ in SUPPORTED_CURRENCY_CHOICES)
MISSING_CREATOR_HANDLE_SENTINEL_PREFIX = "__dfcy_missing_creator_handle__:"
COMPLETED_ORDER_STATUSES = frozenset({"completed", "已完成"})
REFUND_MARKERS = frozenset({"是", "yes", "true", "1", "y"})
SHIPPED_SAMPLE_STATUSES = frozenset(
    {
        SampleFulfillment.Status.SHIPPED,
        SampleFulfillment.Status.DELIVERED,
        SampleFulfillment.Status.COMPLETED,
        SampleFulfillment.Status.PUBLISHED,
        SampleFulfillment.Status.LIVE_CREATOR,
    }
)


def normalize_account(value):
    return normalize_tiktok_username(value)


def influencer_account(influencer):
    """Use only the TikTok handle; display names are not account identifiers."""
    return str(getattr(influencer, "handle", "") or "").strip()


def missing_creator_handle_sentinel(*, tenant, influencer):
    """Return a stable, reserved value for samples without a real handle."""
    return (
        f"{MISSING_CREATOR_HANDLE_SENTINEL_PREFIX}"
        f"{getattr(tenant, 'pk', tenant)}:{getattr(influencer, 'pk', influencer)}"
    )


def _real_creator_account(value):
    normalized = normalize_account(value)
    if not normalized or normalized.startswith(MISSING_CREATOR_HANDLE_SENTINEL_PREFIX):
        return ""
    return normalized


def rule_version_for(attribution):
    return f"{BD_ATTRIBUTION_RULE_VERSION}-{attribution}"


def _canonical_datetime(value):
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_current_timezone())
    return value.astimezone(dt_timezone.utc).isoformat()


def affiliate_order_source_row_key(*, data_time, shop_abbr, site, order_id, sku_id):
    natural_key = "\x1f".join(
        (
            _canonical_datetime(data_time),
            str(shop_abbr or "").strip().casefold(),
            str(site or "").strip().casefold(),
            str(order_id or "").strip().casefold(),
            str(sku_id or "").strip().casefold(),
        )
    )
    return hashlib.sha256(natural_key.encode("utf-8")).hexdigest()


compute_affiliate_order_source_row_key = affiliate_order_source_row_key


def _decimal_string(value):
    if value is None:
        return None
    normalized = Decimal(value).normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _order_values(order):
    """Return only the non-sensitive columns retained by the order snapshot."""
    return {
        "data_time": _canonical_datetime(order.data_time),
        "shop_name": order.shop_name,
        "shop_abbr": order.shop_abbr,
        "site": order.site,
        "order_id": order.order_id,
        "product_id": order.product_id,
        "product_name": order.product_name,
        "sku_id": order.sku_id,
        "product_price": _decimal_string(order.product_price),
        "payment_amount": _decimal_string(order.payment_amount),
        "currency": order.currency,
        "quantity": order.quantity,
        "fully_returned": order.fully_returned,
        "order_status": order.order_status,
        "creator_username": order.creator_username,
        "creator_username_normalized": order.creator_username_normalized,
        "actual_paid_commission": _decimal_string(order.actual_paid_commission),
        "estimated_paid_commission": _decimal_string(order.estimated_paid_commission),
        "source_updated_at": (
            _canonical_datetime(order.source_updated_at) if order.source_updated_at else None
        ),
    }


def affiliate_order_row_hash(values):
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def parse_decimal(value, *, field, required=True):
    raw = str(value or "").strip()
    if not raw:
        if required:
            raise ValueError(f"{field}: required")
        return Decimal("0")
    try:
        parsed = Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field}: invalid_decimal") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field}: invalid_decimal")
    sign, digits, exponent = parsed.as_tuple()
    decimal_places = max(-exponent, 0)
    total_digits = len(digits) + max(exponent, 0)
    integer_digits = max(total_digits - decimal_places, 0)
    if decimal_places > 4:
        raise ValueError(f"{field}: too_many_decimal_places")
    if integer_digits > 16 or total_digits > 20:
        raise ValueError(f"{field}: too_many_digits")
    return parsed


def parse_order_datetime(value, *, field):
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"{field}: required")
    parsed = parse_datetime(raw)
    if parsed is None:
        parsed_date = parse_date(raw)
        if parsed_date is None:
            raise ValueError(f"{field}: invalid_date")
        parsed = datetime.combine(parsed_date, time.min)
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _performance_bounds(start_date, end_date):
    start = timezone.make_aware(datetime.combine(start_date, time.min), timezone.get_current_timezone())
    end = timezone.make_aware(
        datetime.combine(end_date + timedelta(days=1), time.min), timezone.get_current_timezone()
    )
    return start, end


def _local_date(value):
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_current_timezone())
    return timezone.localtime(value).date()


def _money(value):
    return Decimal(value or 0)


def _quantized(value):
    return Decimal(value or 0).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _format_money(value):
    return format(_quantized(value), "f")


class _RateResolver:
    """Resolve tenant exchange rates without a static or external fallback."""

    def __init__(self, tenant):
        self.tenant = tenant
        self._cache = {}
        self.used = {}
        self.missing = {}

    def _resolve(self, base_currency, quote_currency, on_date):
        base = str(base_currency or "").strip().upper()
        quote = str(quote_currency or "").strip().upper()
        cache_key = (base, quote, on_date)
        if cache_key in self._cache:
            return self._cache[cache_key]
        if not base or not quote:
            result = (None, {"source": "missing", "base_currency": base, "quote_currency": quote})
        elif base == quote:
            result = (Decimal("1"), {
                "source": "identity",
                "base_currency": base,
                "quote_currency": quote,
                "rate": "1.0000",
                "effective_from": on_date.isoformat(),
                "version": "identity-cny-v1",
            })
        else:
            row = ExchangeRate.objects.filter(
                tenant=self.tenant,
                base_currency=base,
                quote_currency=quote,
                effective_from__lte=on_date,
                is_active=True,
            ).order_by("-effective_from", "-id").first()
            if row is not None:
                result = (Decimal(row.rate), {
                    "source": "tenant_exchange_rate",
                    "base_currency": base,
                    "quote_currency": quote,
                    "rate": str(Decimal(row.rate)),
                    "effective_from": row.effective_from.isoformat(),
                    "source_name": row.source,
                    "id": row.pk,
                    "version": f"ExchangeRate:{row.pk}:{row.effective_from.isoformat()}",
                })
            else:
                result = (None, {
                    "source": "missing",
                    "base_currency": base,
                    "quote_currency": quote,
                    "effective_from": on_date.isoformat(),
                    "version": "missing",
                })
        self._cache[cache_key] = result
        rate, detail = result
        self.used[cache_key] = detail
        if rate is None:
            self.missing[cache_key] = detail
        return result

    def to_cny(self, currency, on_date):
        return self._resolve(currency, "CNY", on_date)

    def convert(self, value, base_currency, quote_currency, on_date):
        """Convert a value through tenant currency->CNY rates for one business date."""
        amount = Decimal(value or 0)
        base = str(base_currency or "").strip().upper()
        quote = str(quote_currency or "").strip().upper()
        base_rate, base_detail = self.to_cny(base, on_date)
        details = [base_detail]
        if base_rate is None:
            return None, details
        if base == quote:
            return amount, details
        quote_rate, quote_detail = self.to_cny(quote, on_date)
        details.append(quote_detail)
        if quote_rate is None:
            return None, details
        return amount * base_rate / quote_rate, details


def create_sample_attribution_snapshot(
    *,
    tenant,
    fulfillment,
    owner,
    influencer,
    store,
    site="",
    sku_id="",
    source="fulfillment",
    legacy_inferred=False,
):
    """Create the immutable-at-creation owner/sample fact in the caller's transaction."""
    first_item = fulfillment.items.order_by("id").values(
        "site_code", "requested_sku", "currency"
    ).first()
    currency = str((first_item or {}).get("currency") or store.currency or "CNY").strip().upper()
    sampled_site = str(site or (first_item or {}).get("site_code") or store.country_code or "").strip()
    account = _real_creator_account(influencer_account(influencer))
    if not account:
        account = missing_creator_handle_sentinel(tenant=tenant, influencer=influencer)
    snapshot = BdSampleAttributionSnapshot(
        tenant=tenant,
        fulfillment=fulfillment,
        owner=owner,
        influencer=influencer,
        store=store,
        creator_username=account,
        shop_abbr=store.code,
        site=sampled_site,
        product_id=fulfillment.external_product_id or "",
        product_name=fulfillment.product_name_snapshot or "",
        sku_id=str(sku_id or (first_item or {}).get("requested_sku") or "").strip(),
        sampled_at=fulfillment.sample_sent_at,
        shipped_at=fulfillment.shipped_at,
        sample_status=fulfillment.status,
        cost_amount=fulfillment.calculated_cost,
        currency=currency,
        pricing_status=fulfillment.pricing_status,
        source=source,
        legacy_inferred=legacy_inferred,
    )
    snapshot.full_clean()
    snapshot.save()
    return snapshot


def _candidate_sort_key(snapshot):
    sampled_at = _aware_datetime(snapshot.sampled_at)
    fulfillment_id = getattr(snapshot, "fulfillment_id", None) or snapshot.pk
    return sampled_at, fulfillment_id, snapshot.pk


def _aware_datetime(value):
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_current_timezone())
    return value.astimezone(dt_timezone.utc)


def _business_key_part(value):
    return str(value or "").strip().casefold()


def _sample_duplicate_key(sample):
    return (
        _real_creator_account(sample.creator_username),
        _business_key_part(sample.shop_abbr),
        _business_key_part(sample.product_id),
        _business_key_part(sample.sku_id),
    )


def _sample_group_key(sample, *, product_required):
    key = (
        _real_creator_account(sample.creator_username),
        _business_key_part(sample.shop_abbr),
    )
    if product_required:
        key += (_business_key_part(sample.product_id),)
    return key


def _group_sample_candidates(samples, *, product_required):
    grouped = defaultdict(list)
    for sample in samples:
        if not _real_creator_account(sample.creator_username):
            continue
        grouped[_sample_group_key(sample, product_required=product_required)].append(sample)
    for key, candidates in grouped.items():
        # Ascending time enables O(log n) lookup. Duplicate samples are
        # resolved after the order-time cutoff so the earliest eligible fact wins.
        candidates.sort(key=_candidate_sort_key)
        grouped[key] = ([_aware_datetime(sample.sampled_at) for sample in candidates], candidates)
    return grouped


def _order_account(order):
    account = _real_creator_account(order.creator_username)
    return account or _real_creator_account(order.creator_username_normalized)


def _candidate_for_order_sku(candidates, order):
    earliest_by_sample_key = {}
    for sample in candidates:
        duplicate_key = _sample_duplicate_key(sample)
        current = earliest_by_sample_key.get(duplicate_key)
        if current is None or _candidate_sort_key(sample) < _candidate_sort_key(current):
            earliest_by_sample_key[duplicate_key] = sample
    candidates = list(earliest_by_sample_key.values())
    if not candidates:
        return None

    order_sku = _business_key_part(order.sku_id)
    exact_sku = [
        sample
        for sample in candidates
        if order_sku and _business_key_part(sample.sku_id) == order_sku
    ]
    if exact_sku:
        return min(exact_sku, key=_candidate_sort_key)

    # Empty sample SKU is the legacy product-level fact and remains eligible.
    legacy_product_samples = [sample for sample in candidates if not _business_key_part(sample.sku_id)]
    if legacy_product_samples:
        return min(legacy_product_samples, key=_candidate_sort_key)
    if order_sku:
        return None
    return min(candidates, key=_candidate_sort_key)


def _snapshot_has_current_handle(sample):
    current_handle = _real_creator_account(influencer_account(sample.influencer))
    snapshot_handle = _real_creator_account(sample.creator_username)
    return bool(current_handle) and snapshot_handle == current_handle


def _eligible_candidate(candidates, order, *, product_required):
    key = (
        _order_account(order),
        _business_key_part(order.shop_abbr),
    )
    if product_required:
        key += (_business_key_part(order.product_id),)
    if isinstance(candidates, dict):
        candidate_times, grouped_candidates = candidates.get(key, ((), ()))
        position = bisect_right(candidate_times, _aware_datetime(order.data_time))
        return _candidate_for_order_sku(grouped_candidates[:position], order)
    else:
        candidates = [
            sample for sample in candidates
            if _sample_group_key(sample, product_required=product_required) == key
        ]
        candidates = [
            sample
            for sample in candidates
            if _aware_datetime(sample.sampled_at) <= _aware_datetime(order.data_time)
        ]
        return _candidate_for_order_sku(sorted(candidates, key=_candidate_sort_key), order)


def _valid_order(order):
    return (
        order.order_status.strip().casefold() in {item.casefold() for item in COMPLETED_ORDER_STATUSES}
        and order.fully_returned.strip().casefold() not in REFUND_MARKERS
    )


def _order_attribution_key(order):
    # ``source_row_key`` is an ingestion identity, not the business identity
    # of an order line. Exports may produce a new row key when the same
    # order/SKU is re-exported at a different timestamp, and two approved
    # sources may carry the same business line. Attribution therefore chooses
    # one deterministic line while the source row remains separately stored
    # and auditable. Shop/site keep reused order numbers isolated.
    return (
        _business_key_part(order.shop_abbr),
        _business_key_part(order.site),
        _business_key_part(order.order_id),
        _business_key_part(order.sku_id),
    )


def _order_fact_sort_key(order):
    """Choose the latest exported fact before applying status/refund rules."""
    source_time = order.source_updated_at or order.data_time
    return _aware_datetime(source_time), _aware_datetime(order.data_time), order.pk


def _latest_order_snapshots(*, tenant):
    """Select one current export per tenant-scoped order SKU business key."""
    latest = {}
    queryset = AffiliateOrderSnapshot.objects.filter(tenant=tenant).order_by("id")
    for order in queryset.iterator(chunk_size=1000):
        key = _order_attribution_key(order)
        current = latest.get(key)
        if current is None or _order_fact_sort_key(order) > _order_fact_sort_key(current):
            latest[key] = order
    return latest


@transaction.atomic
def refresh_order_attributions(*, tenant, attribution="strict", rule_version=None):
    if attribution not in {"strict", "fallback"}:
        raise ValidationError({"attribution": "Attribution must be strict or fallback."})
    effective_rule_version = rule_version or rule_version_for(attribution)
    sample_queryset = (
        BdSampleAttributionSnapshot.objects.filter(
            tenant=tenant,
            fulfillment__tenant=tenant,
            fulfillment__is_deleted=False,
        ).filter(
            Q(fulfillment__outreach_task__isnull=True)
            | Q(fulfillment__outreach_task__is_deleted=False)
        )
        .select_related("influencer")
        .order_by("sampled_at", "fulfillment_id", "id")
    )
    samples = [
        sample
        for sample in sample_queryset
        if _snapshot_has_current_handle(sample)
    ]
    sample_groups = _group_sample_candidates(
        samples,
        product_required=attribution == "strict",
    )
    latest_orders_by_key = _latest_order_snapshots(tenant=tenant)
    orders_by_key = {
        key: order for key, order in latest_orders_by_key.items() if _valid_order(order)
    }
    existing = {}
    duplicate_existing_ids = []
    for item in BdOrderAttributionSnapshot.objects.filter(
        tenant=tenant, rule_version=effective_rule_version
    ).select_related("order_snapshot").order_by("id"):
        key = _order_attribution_key(item.order_snapshot)
        if key in existing:
            duplicate_existing_ids.append(item.pk)
        else:
            existing[key] = item
    created = updated = noop = rejected = deleted = 0
    desired_keys = set()
    for key, order in sorted(
        orders_by_key.items(),
        key=lambda item: (_aware_datetime(item[1].data_time), item[1].id),
    ):
        sample = _eligible_candidate(
            sample_groups,
            order,
            product_required=attribution == "strict",
        )
        if sample is None:
            continue
        desired_keys.add(key)
        values = {
            "tenant": tenant,
            "order_snapshot": order,
            "sample_attribution": sample,
            "owner": sample.owner,
            "influencer": sample.influencer,
            "store": sample.store,
            "order_id": order.order_id,
            "sku_id": order.sku_id,
            "product_id": order.product_id,
            "rule": attribution,
            "rule_version": effective_rule_version,
        }
        current = existing.get(key)
        if current is None:
            try:
                with transaction.atomic():
                    current = BdOrderAttributionSnapshot.objects.create(**values)
            except IntegrityError:
                current = BdOrderAttributionSnapshot.objects.filter(
                    tenant=tenant,
                    order_snapshot=order,
                    rule_version=effective_rule_version,
                ).order_by("id").first()
                if current is None:
                    raise
                updated += 1
            else:
                created += 1
            existing[key] = current
            continue
        comparable = {
            "sample_attribution_id": values["sample_attribution"].pk,
            "order_snapshot_id": order.pk,
            "owner_id": values["owner"].pk,
            "influencer_id": values["influencer"].pk,
            "store_id": values["store"].pk if values["store"] else None,
            "order_id": values["order_id"],
            "sku_id": values["sku_id"],
            "product_id": values["product_id"],
            "rule": values["rule"],
        }
        if all(getattr(current, key) == value for key, value in comparable.items()):
            noop += 1
            continue
        current.sample_attribution = values["sample_attribution"]
        current.order_snapshot = values["order_snapshot"]
        current.owner = values["owner"]
        current.influencer = values["influencer"]
        current.store = values["store"]
        current.order_id = values["order_id"]
        current.sku_id = values["sku_id"]
        current.product_id = values["product_id"]
        current.rule = values["rule"]
        current.full_clean()
        current.save(
            update_fields=[
                "sample_attribution",
                "order_snapshot",
                "owner",
                "influencer",
                "store",
                "order_id",
                "sku_id",
                "product_id",
                "rule",
                "updated_at",
            ]
        )
        updated += 1
    stale_keys = set(existing).difference(desired_keys)
    stale_ids = duplicate_existing_ids + [existing[key].pk for key in stale_keys]
    if stale_ids:
        deleted, _ = BdOrderAttributionSnapshot.objects.filter(
            tenant=tenant,
            rule_version=effective_rule_version,
            pk__in=stale_ids,
        ).delete()
    return {
        "created": created,
        "updated": updated,
        "noop": noop,
        "rejected": rejected,
        "deleted": deleted,
        "rule_version": effective_rule_version,
    }


def _owner_bucket():
    return {
        "task_count": 0,
        "linked_count": 0,
        "sample_count": 0,
        "shipped_count": 0,
        "investment_cny": Decimal("0"),
        "valid_order_count": 0,
        "item_quantity": 0,
        "gmv_cny": Decimal("0"),
        "commission_cny": Decimal("0"),
        "order_ids": set(),
        "missing_exchange_rates": set(),
    }


def _serialize_metrics(bucket, currency):
    # Monetary buckets are already converted to the requested display currency.
    investment = bucket["investment_cny"]
    gmv = bucket["gmv_cny"]
    commission = bucket["commission_cny"]
    roi = None if investment == 0 else gmv / investment
    return {
        "task_count": bucket["task_count"],
        "outreach_tasks": bucket["task_count"],
        "linked_count": bucket["linked_count"],
        "sample_count": bucket["sample_count"],
        "samples": bucket["sample_count"],
        "shipped_count": bucket["shipped_count"],
        "shipped_samples": bucket["shipped_count"],
        "investment": _format_money(investment),
        "valid_order_count": len(bucket["order_ids"]),
        "valid_orders": len(bucket["order_ids"]),
        "item_quantity": bucket["item_quantity"],
        "quantity": bucket["item_quantity"],
        "gmv": _format_money(gmv),
        "commission": _format_money(commission),
        "roi": format(roi.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP), "f") if roi is not None else None,
    }


def build_bd_performance(*, tenant, start_date, end_date, attribution="strict", currency="CNY"):
    if currency not in PERFORMANCE_CURRENCIES:
        raise ValidationError({"currency": "Currency must be CNY, PHP, MYR, THB or USD."})
    if attribution not in {"strict", "fallback"}:
        raise ValidationError({"attribution": "Attribution must be strict or fallback."})
    if start_date > end_date:
        raise ValidationError({"date": "start_date must not be after end_date."})
    if (end_date - start_date).days > 30:
        raise ValidationError({"date": "The date range must not exceed 31 days."})

    start_dt, end_dt = _performance_bounds(start_date, end_date)
    buckets = defaultdict(_owner_bucket)
    owner_ids = set()
    rate_resolver = _RateResolver(tenant)

    def _record_rate_details(bucket, details):
        for detail in details:
            if detail.get("source") == "missing":
                base_currency = str(detail.get("base_currency") or "").upper()
                if base_currency:
                    bucket["missing_exchange_rates"].add(base_currency)

    task_rows = (
        OutreachTask.objects.filter(
            tenant=tenant,
            is_deleted=False,
            created_at__gte=start_dt,
            created_at__lt=end_dt,
        )
        .annotate(
            active_linked_count=Count(
                "targets",
                filter=Q(targets__tenant=tenant, targets__is_deleted=False),
                distinct=True,
            )
        )
        .values("owner_id", "active_linked_count")
    )
    for row in task_rows:
        bucket = buckets[row["owner_id"]]
        bucket["task_count"] += 1
        bucket["linked_count"] += row["active_linked_count"] or 0
        owner_ids.add(row["owner_id"])

    sample_rows = BdSampleAttributionSnapshot.objects.filter(
        tenant=tenant,
        fulfillment__tenant=tenant,
        fulfillment__is_deleted=False,
    ).filter(
        Q(fulfillment__outreach_task__isnull=True)
        | Q(fulfillment__outreach_task__is_deleted=False)
    ).filter(
        sampled_at__gte=start_dt,
        sampled_at__lt=end_dt,
    ).values(
        "owner_id", "cost_amount", "currency",
        "sampled_at", "fulfillment__status", "fulfillment__shipped_at", "fulfillment__sample_order_no",
    ).order_by("id")
    for row in sample_rows.iterator(chunk_size=1000):
        bucket = buckets[row["owner_id"]]
        bucket["sample_count"] += 1
        if (
            row["fulfillment__status"] in SHIPPED_SAMPLE_STATUSES
            or row["fulfillment__shipped_at"] is not None
            or str(row["fulfillment__sample_order_no"] or "").strip()
        ):
            bucket["shipped_count"] += 1
        if row["cost_amount"] is not None:
            source_currency = str(row["currency"] or "").upper()
            converted, details = rate_resolver.convert(
                row["cost_amount"],
                source_currency,
                currency,
                _local_date(row["sampled_at"]),
            )
            _record_rate_details(bucket, details)
            if converted is not None:
                bucket["investment_cny"] += converted
        owner_ids.add(row["owner_id"])

    order_rows = (
        BdOrderAttributionSnapshot.objects.filter(
            tenant=tenant,
            rule=attribution,
            rule_version=rule_version_for(attribution),
            order_snapshot__tenant=tenant,
            sample_attribution__fulfillment__tenant=tenant,
            sample_attribution__fulfillment__is_deleted=False,
            order_snapshot__data_time__gte=start_dt,
            order_snapshot__data_time__lt=end_dt,
        ).filter(
            Q(sample_attribution__fulfillment__outreach_task__isnull=True)
            | Q(sample_attribution__fulfillment__outreach_task__is_deleted=False),
            Q(order_snapshot__order_status__iexact="completed")
            | Q(order_snapshot__order_status="已完成")
        )
        .select_related("order_snapshot")
        .values(
            "owner_id",
            "order_snapshot_id",
            "order_snapshot__source",
            "order_snapshot__source_row_key",
            "order_snapshot__shop_abbr",
            "order_snapshot__site",
            "order_snapshot__order_id",
            "order_snapshot__sku_id",
            "order_snapshot__data_time",
            "order_snapshot__quantity",
            "order_snapshot__payment_amount",
            "order_snapshot__currency",
            "order_snapshot__actual_paid_commission",
            "order_snapshot__estimated_paid_commission",
            "order_snapshot__fully_returned",
        )
        .order_by(
            "order_snapshot__source",
            "order_snapshot__shop_abbr",
            "order_snapshot__site",
            "order_snapshot__order_id",
            "order_snapshot__sku_id",
            "order_snapshot_id",
        )
    )
    seen_lines = set()
    for row in order_rows.iterator(chunk_size=1000):
        if str(row["order_snapshot__fully_returned"] or "").strip().casefold() in REFUND_MARKERS:
            continue
        # Keep this guard aligned with the business identity so legacy
        # duplicate attribution rows cannot inflate GMV/quantity.
        line_key = (
            _business_key_part(row["order_snapshot__shop_abbr"]),
            _business_key_part(row["order_snapshot__site"]),
            _business_key_part(row["order_snapshot__order_id"]),
            _business_key_part(row["order_snapshot__sku_id"]),
        )
        if line_key in seen_lines:
            continue
        seen_lines.add(line_key)
        bucket = buckets[row["owner_id"]]
        bucket["order_ids"].add(str(row["order_snapshot__order_id"] or "").strip())
        bucket["item_quantity"] += row["order_snapshot__quantity"] or 0
        source_currency = str(row["order_snapshot__currency"] or "").upper()
        converted, details = rate_resolver.convert(
            row["order_snapshot__payment_amount"],
            source_currency,
            currency,
            _local_date(row["order_snapshot__data_time"]),
        )
        _record_rate_details(bucket, details)
        if converted is None:
            owner_ids.add(row["owner_id"])
            continue
        bucket["gmv_cny"] += converted
        actual = _money(row["order_snapshot__actual_paid_commission"])
        commission = actual if actual != 0 else _money(row["order_snapshot__estimated_paid_commission"])
        commission_converted, commission_details = rate_resolver.convert(
            commission,
            source_currency,
            currency,
            _local_date(row["order_snapshot__data_time"]),
        )
        _record_rate_details(bucket, commission_details)
        if commission_converted is not None:
            bucket["commission_cny"] += commission_converted
        owner_ids.add(row["owner_id"])

    users = {
        row["id"]: row
        for row in get_user_model().objects.filter(tenant=tenant, pk__in=owner_ids).values(
            "id", "username", "full_name"
        )
    }
    rows = []
    for owner_id in sorted(owner_ids):
        owner = users.get(owner_id, {"id": owner_id, "username": "", "full_name": ""})
        row = _serialize_metrics(buckets[owner_id], currency)
        row.update(
            {
                "owner_id": owner_id,
                "owner": owner["full_name"] or owner["username"],
                "username": owner["username"],
            }
        )
        rows.append(row)

    total_bucket = _owner_bucket()
    for bucket in buckets.values():
        total_bucket["task_count"] += bucket["task_count"]
        total_bucket["linked_count"] += bucket["linked_count"]
        total_bucket["sample_count"] += bucket["sample_count"]
        total_bucket["shipped_count"] += bucket["shipped_count"]
        total_bucket["investment_cny"] += bucket["investment_cny"]
        total_bucket["item_quantity"] += bucket["item_quantity"]
        total_bucket["gmv_cny"] += bucket["gmv_cny"]
        total_bucket["commission_cny"] += bucket["commission_cny"]
        total_bucket["order_ids"].update(bucket["order_ids"])
        total_bucket["missing_exchange_rates"].update(bucket["missing_exchange_rates"])

    has_orders = AffiliateOrderSnapshot.objects.filter(tenant=tenant).exists()
    has_samples = BdSampleAttributionSnapshot.objects.filter(
        tenant=tenant,
        fulfillment__tenant=tenant,
        fulfillment__is_deleted=False,
    ).filter(
        Q(fulfillment__outreach_task__isnull=True)
        | Q(fulfillment__outreach_task__is_deleted=False)
    ).exists()
    has_attributions = bool(seen_lines)
    if not has_orders:
        source_status = "not_imported"
    elif not has_samples:
        source_status = "awaiting_fulfillment_data"
    elif not has_attributions:
        source_status = "empty"
    else:
        source_status = "ready"

    max_data_time = AffiliateOrderSnapshot.objects.filter(tenant=tenant).aggregate(
        max_data_time=Max("data_time")
    )["max_data_time"]
    data_as_of = timezone.localtime(max_data_time).date().isoformat() if max_data_time else None
    diagnostic_reasons = []
    if not has_orders:
        diagnostic_reasons.append("orders_not_imported")
    elif not has_samples:
        diagnostic_reasons.append("no_active_samples")
    elif not has_attributions:
        diagnostic_reasons.append("no_sample_match")
    if total_bucket["missing_exchange_rates"]:
        diagnostic_reasons.append("missing_exchange_rate")
    if not diagnostic_reasons and total_bucket["gmv_cny"] == 0:
        diagnostic_reasons.append("zero_payment_amount")
    zero_gmv_diagnostic = {
        "is_zero_gmv": total_bucket["gmv_cny"] == 0,
        "reason_codes": diagnostic_reasons,
        "missing_exchange_rates": sorted(total_bucket["missing_exchange_rates"]),
    }
    rate_details = sorted(
        rate_resolver.used.values(),
        key=lambda detail: (
            detail.get("base_currency", ""),
            detail.get("quote_currency", ""),
            detail.get("effective_from", ""),
            detail.get("id", 0),
        ),
    )
    rates = {}
    for detail in rate_details:
        if detail.get("rate") is None:
            continue
        key = f"{detail.get('base_currency', '')}->{detail.get('quote_currency', '')}@{detail.get('effective_from', '')}"
        rates[key] = detail["rate"]
    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "currency": currency,
        "attribution": attribution,
        "rates": rates,
        "rate_details": rate_details,
        "rate_source": "tenant_exchange_rate",
        "rate_version": RATE_SELECTION_VERSION,
        "rate_config_version": RATE_SELECTION_VERSION,
        "rate_source_description": RATE_SOURCE_DESCRIPTION,
        "rate_missing": bool(total_bucket["missing_exchange_rates"]),
        "missing_exchange_rates": sorted(total_bucket["missing_exchange_rates"]),
        "missing_exchange_rate_details": sorted(
            rate_resolver.missing.values(),
            key=lambda detail: (
                detail.get("base_currency", ""),
                detail.get("quote_currency", ""),
                detail.get("effective_from", ""),
            ),
        ),
        "zero_gmv_diagnostic": zero_gmv_diagnostic,
        "data_as_of": data_as_of,
        "rule_version": rule_version_for(attribution),
        "source_status": source_status,
        "rows": rows,
        "results": rows,
        "totals": _serialize_metrics(total_bucket, currency),
    }


def default_performance_dates(*, tenant):
    today = timezone.localdate()
    yesterday = today - timedelta(days=1)
    max_data_time = AffiliateOrderSnapshot.objects.filter(tenant=tenant).aggregate(
        max_data_time=Max("data_time")
    )["max_data_time"]
    max_date = timezone.localtime(max_data_time).date() if max_data_time else None
    end_date = min(yesterday, max_date) if max_date else yesterday
    return end_date - timedelta(days=6), end_date


def parse_performance_date(value, *, field):
    parsed = parse_date(str(value or "").strip())
    if parsed is None:
        raise ValidationError({field: "Date must use YYYY-MM-DD."})
    return parsed


def backfill_sample_attributions(*, tenant=None):
    queryset = SampleFulfillment.objects.select_related(
        "owner", "influencer", "store"
    ).filter(
        tenant=tenant,
        is_deleted=False,
    ).filter(
        Q(outreach_task__isnull=True) | Q(outreach_task__is_deleted=False)
    ) if tenant is not None else SampleFulfillment.objects.select_related(
        "owner", "influencer", "store"
    ).filter(is_deleted=False).filter(
        Q(outreach_task__isnull=True) | Q(outreach_task__is_deleted=False)
    )
    created = existing = 0
    for fulfillment in queryset.iterator(chunk_size=500):
        if BdSampleAttributionSnapshot.objects.filter(
            tenant=fulfillment.tenant, fulfillment=fulfillment
        ).exists():
            existing += 1
            continue
        create_sample_attribution_snapshot(
            tenant=fulfillment.tenant,
            fulfillment=fulfillment,
            owner=fulfillment.owner,
            influencer=fulfillment.influencer,
            store=fulfillment.store,
            source="legacy_inferred",
            legacy_inferred=True,
        )
        created += 1
    return {"created": created, "existing": existing}
