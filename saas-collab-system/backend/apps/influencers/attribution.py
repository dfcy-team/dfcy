"""Safe, tenant-scoped affiliate facts and BD attribution helpers."""

from collections import defaultdict
from bisect import bisect_right
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import hashlib
import json

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q
from django.db.models.functions import Lower, Trim
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework.exceptions import ValidationError
from apps.configcenter.models import TenantConfigVersion
from apps.tenants.models import Tenant

from .bd_exchange_rates import (
    BD_EXCHANGE_RATES_CONFIG_KEY, validate_bd_exchange_rate_definition, validate_bd_exchange_rates,
)
from .settlement import NO_REFUND_MARKERS, REFUND_MARKERS, SETTLED, SETTLEMENT_CHOICES, refund_marker

from .models import (
    AffiliateImportState,
    AffiliateOrderRevision,
    AffiliateOrderSnapshot,
    BdOrderAttributionSnapshot,
    BdSampleAttributionSnapshot,
    ExchangeRate,
    SampleFulfillment,
    SUPPORTED_CURRENCY_CHOICES,
    normalize_tiktok_username,
)


BD_ATTRIBUTION_RULE_VERSION = "bd-attribution-v2-settlement"
BD_COST_BASIS = "sample_plus_actual_commissions"
COST_COMPONENTS = ("sample_cost", "actual_standard_commission", "actual_ads_commission")
ACTUAL_COMMISSION_FIELDS = (
    ("actual_standard_commission", "actual_paid_commission"),
    ("actual_ads_commission", "actual_paid_shop_ads_commission"),
)
RATE_SELECTION_VERSION = "tenant-exchange-rate-effective-from-desc-id-desc-v1"
CONFIG_RATE_SELECTION_VERSION = "tenant-config-business-date-with-legacy-fallback-v1"
RATE_SOURCE_DESCRIPTION = (
    "Tenant ExchangeRate; CNY uses identity rate 1; other currencies use the latest "
    "active base_currency->CNY rate effective on the business date."
)
PERFORMANCE_CURRENCIES = frozenset(currency for currency, _ in SUPPORTED_CURRENCY_CHOICES)
SHIPPED_SAMPLE_STATUSES = frozenset(
    {
        SampleFulfillment.Status.SHIPPED,
        SampleFulfillment.Status.DELIVERED,
        SampleFulfillment.Status.COMPLETED,
        SampleFulfillment.Status.PUBLISHED,
        SampleFulfillment.Status.LIVE_CREATOR,
    }
)
_MAX_DATA_TIME_UNSET = object()
COUNTRY_CURRENCY_BREAKDOWN = (
    ("PH", "菲律宾", "PHP"),
    ("MY", "马来西亚", "MYR"),
    ("TH", "泰国", "THB"),
)
COUNTRY_BY_CODE = {code: (name, currency) for code, name, currency in COUNTRY_CURRENCY_BREAKDOWN}
COUNTRY_BY_CURRENCY = {currency: code for code, _, currency in COUNTRY_CURRENCY_BREAKDOWN}


def normalize_account(value):
    return " ".join(str(value or "").strip().split()).casefold()


def _country_code(value):
    normalized = str(value or "").strip().upper()
    if normalized in COUNTRY_BY_CODE:
        return normalized
    return COUNTRY_BY_CURRENCY.get(normalized)


def normalize_creator_handle(value):
    return normalize_tiktok_username(value)


def influencer_account(influencer):
    """Return only the normalized TikTok handle used as the attribution identity."""
    return normalize_creator_handle(getattr(influencer, "handle", ""))


def rule_version_for(attribution):
    if attribution not in {"strict", "fallback"}:
        raise ValidationError({"attribution": "Attribution must be strict or fallback."})
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
        "estimated_commission_base": _decimal_string(order.estimated_commission_base),
        "currency": order.currency,
        "quantity": order.quantity,
        "fully_returned": order.fully_returned,
        "settlement_status": order.settlement_status,
        "order_status": order.order_status,
        "creator_username": order.creator_username,
        "creator_username_normalized": order.creator_username_normalized,
        "actual_paid_commission": _decimal_string(order.actual_paid_commission),
        "actual_paid_shop_ads_commission": _decimal_string(order.actual_paid_shop_ads_commission),
        "estimated_paid_commission": _decimal_string(order.estimated_paid_commission),
        "source_updated_at": (
            _canonical_datetime(order.source_updated_at) if order.source_updated_at else None
        ),
    }


def affiliate_order_row_hash(values):
    # Keep legacy hashes stable until new nullable facts are actually known.
    values = dict(values)
    for field in ("estimated_commission_base", "settlement_status", "actual_paid_shop_ads_commission"):
        if values.get(field) is None:
            values.pop(field, None)
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
    amount = Decimal(value or 0)
    with localcontext() as context:
        # Large allowed FX products need room for their integer part plus four
        # report decimals and a carry; the rounding policy remains unchanged.
        context.prec = max(context.prec, amount.adjusted() + 6)
        return amount.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _format_money(value):
    return format(_quantized(value), "f")


class _RateResolver:
    """Pin one effective tenant schedule and legacy facts for the whole report."""

    def __init__(self, tenant):
        self.tenant = tenant
        self._cache = {}
        self.used = {}
        self.missing = {}
        self._config_version = (
            TenantConfigVersion.objects.filter(
                tenant_id=tenant.pk,
                scope_key=f"tenant:{tenant.pk}",
                config_key=BD_EXCHANGE_RATES_CONFIG_KEY,
                status=TenantConfigVersion.Status.EFFECTIVE,
                effective_at__lte=timezone.now(),
            )
            .select_related("definition")
            .only(
                "id", "version", "value", "definition_id", "approved_by_id", "created_by_id",
                "definition__config_key", "definition__scope_type", "definition__value_type",
                "definition__is_sensitive", "definition__requires_approval",
            )
            .order_by("-version", "-id")
            .first()
        )
        configured = defaultdict(list)
        if self._config_version is not None:
            try:
                validate_bd_exchange_rate_definition(self._config_version.definition)
                schedule = validate_bd_exchange_rates(self._config_version.value)
            except DjangoValidationError as exc:
                raise ValidationError({
                    BD_EXCHANGE_RATES_CONFIG_KEY: (
                        "Active BD exchange-rate configuration is invalid. "
                        "Save a corrected configuration before requesting reports."
                    ),
                }) from exc
            for row in schedule["rates"]:
                configured[row["currency"]].append(row)
        self._configured_rates = {}
        for currency, rows in configured.items():
            rows.sort(key=lambda row: row["effective_from"])
            self._configured_rates[currency] = (
                [date.fromisoformat(row["effective_from"]) for row in rows], rows,
            )
        self._rates_by_pair = defaultdict(list)
        for row in ExchangeRate.objects.filter(
            tenant=tenant,
            is_active=True,
        ).only(
            "id", "base_currency", "quote_currency", "rate", "effective_from", "source"
        ).order_by("base_currency", "quote_currency", "effective_from", "id"):
            pair = (row.base_currency.strip().upper(), row.quote_currency.strip().upper())
            self._rates_by_pair[pair].append(row)

    def _fallback_reason(self, currency):
        if self._config_version is None:
            return "no_effective_config"
        if not self._configured_rates:
            return "empty_schedule"
        if currency not in self._configured_rates:
            return "currency_not_configured"
        return "before_configured_schedule"

    def metadata(self):
        sources = {detail["source"] for detail in self.used.values()}
        has_config = "tenant_config" in sources
        has_legacy = "tenant_exchange_rate" in sources
        source = "tenant_exchange_rate"
        if has_config:
            source = "mixed" if has_legacy else "tenant_config"
        return {
            "rate_source": source,
            "rate_version": CONFIG_RATE_SELECTION_VERSION if has_config else RATE_SELECTION_VERSION,
            "rate_config_key": BD_EXCHANGE_RATES_CONFIG_KEY,
            "rate_config_version": self._config_version.version if self._config_version else None,
            "rate_config_version_id": self._config_version.pk if self._config_version else None,
            "rate_source_description": (
                "Approved tenant BD configuration takes precedence for each currency and business date; "
                "uncovered dates/currencies use tenant ExchangeRate facts; CNY uses identity 1."
                if has_config else RATE_SOURCE_DESCRIPTION
            ),
        }

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
            configured_dates, configured_rows = self._configured_rates.get(base, ((), ()))
            position = bisect_right(configured_dates, on_date) if quote == "CNY" else 0
            candidates = self._rates_by_pair.get((base, quote), ())
            row = next(
                (candidate for candidate in reversed(candidates) if candidate.effective_from <= on_date),
                None,
            )
            if position:
                configured_row = configured_rows[position - 1]
                effective_from = configured_row["effective_from"]
                result = (Decimal(configured_row["rate"]), {
                    "source": "tenant_config",
                    "base_currency": base,
                    "quote_currency": quote,
                    "rate": configured_row["rate"],
                    "effective_from": effective_from,
                    "source_name": BD_EXCHANGE_RATES_CONFIG_KEY,
                    "version": f"TenantConfigVersion:{self._config_version.pk}:{self._config_version.version}:{effective_from}",
                })
            elif row is not None:
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
        rate, detail = result
        detail.update({
            "config_key": BD_EXCHANGE_RATES_CONFIG_KEY,
            "config_version_id": self._config_version.pk if self._config_version else None,
            "config_version": self._config_version.version if self._config_version else None,
            "business_date": on_date.isoformat(),
            "rate_effective_date": detail.get("effective_from") if rate is not None else None,
        })
        if detail["source"] in {"tenant_exchange_rate", "missing"}:
            detail["fallback_reason"] = self._fallback_reason(base)
        self._cache[cache_key] = result
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
        if any(detail["source"] == "tenant_config" for detail in details):
            with localcontext() as context:
                context.prec = max(
                    context.prec,
                    len(amount.as_tuple().digits) + len(base_rate.as_tuple().digits)
                    + len(quote_rate.as_tuple().digits) + 8,
                    amount.adjusted() + base_rate.adjusted() - quote_rate.adjusted() + 8,
                )
                return amount * base_rate / quote_rate, details
        return amount * base_rate / quote_rate, details

    def add_converted(self, total, amount):
        if self._configured_rates:
            with localcontext() as context:
                context.prec = max(
                    context.prec,
                    max(total.adjusted(), amount.adjusted())
                    - min(total.as_tuple().exponent, amount.as_tuple().exponent) + 2,
                )
                return total + amount
        return total + amount


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
        "site_code", "requested_sku"
    ).first()
    currency = "CNY"
    sampled_site = str(site or (first_item or {}).get("site_code") or store.country_code or "").strip()
    account = influencer_account(influencer)
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
        # ProductSKU.purchase_price is maintained in RMB for creator operations.
        cost_amount=fulfillment.calculated_cost,
        currency=currency,
        pricing_status="pending",
        source=source,
        legacy_inferred=legacy_inferred,
    )
    snapshot.full_clean()
    snapshot.save()
    return snapshot


def _candidate_sort_key(snapshot):
    sampled_at = snapshot.sampled_at
    if timezone.is_naive(sampled_at):
        sampled_at = timezone.make_aware(sampled_at, timezone.get_current_timezone())
    fulfillment_id = getattr(snapshot, "fulfillment_id", None) or snapshot.pk
    return (-sampled_at.timestamp(), -fulfillment_id)


def _sample_group_key(sample, *, product_required):
    key = (
        normalize_creator_handle(sample.creator_username),
        normalize_account(sample.shop_abbr),
    )
    if product_required:
        key += (normalize_account(sample.product_id),)
    return key


def _group_sample_candidates(samples, *, product_required):
    grouped = defaultdict(list)
    for sample in samples:
        key = _sample_group_key(sample, product_required=product_required)
        if not key[0]:
            continue
        grouped[key].append(sample)
    for key, candidates in grouped.items():
        # Ascending time enables O(log n) lookup; the last equal-time row is
        # the highest fulfillment id, matching sampled_at DESC, fulfillment_id DESC.
        candidates.sort(key=lambda sample: (sample.sampled_at, getattr(sample, "fulfillment_id", None) or sample.pk))
        grouped[key] = ([sample.sampled_at for sample in candidates], candidates)
    return grouped


def _eligible_candidate(candidates, order, *, product_required):
    creator_handle = normalize_creator_handle(
        order.creator_username_normalized or order.creator_username
    )
    if not creator_handle:
        return None
    key = (
        creator_handle,
        normalize_account(order.shop_abbr),
    )
    if product_required:
        key += (normalize_account(order.product_id),)
    if isinstance(candidates, dict):
        candidate_times, grouped_candidates = candidates.get(key, ((), ()))
        position = bisect_right(candidate_times, order.data_time)
        return grouped_candidates[position - 1] if position else None
    else:
        candidates = [
            sample for sample in candidates
            if _sample_group_key(sample, product_required=product_required) == key
        ]
        candidates = sorted(candidates, key=_candidate_sort_key)
    for sample in candidates:
        if sample.sampled_at > order.data_time:
            continue
        return sample
    return None


def _valid_order(order):
    return (
        str(order.settlement_status or "").strip() == SETTLED
        and refund_marker(order.fully_returned) in NO_REFUND_MARKERS
    )


def _order_attribution_key(order):
    # ``source_row_key`` is an ingestion identity, not the business identity
    # of an order line. Exports may produce a new row key when the same
    # order/SKU is re-exported at a different timestamp, and two approved
    # sources may carry the same business line. Attribution therefore chooses
    # one deterministic line while the source row remains separately stored
    # and auditable. Shop/site keep reused order numbers isolated.
    return (
        str(order.shop_abbr or "").strip().casefold(),
        str(order.site or "").strip().casefold(),
        str(order.order_id or "").strip().casefold(),
        str(order.sku_id or "").strip().casefold(),
    )


@transaction.atomic
def refresh_order_attributions(
    *, tenant, attribution="strict", rule_version=None, start_date=None, end_date=None,
    changed_since=None, order_ids=None, deletion_limit=10000,
):
    if attribution not in {"strict", "fallback"}:
        raise ValidationError({"attribution": "Attribution must be strict or fallback."})
    effective_rule_version = rule_version or rule_version_for(attribution)
    if effective_rule_version != rule_version_for(attribution):
        raise ValidationError({"rule_version": "Only the current settlement rule version may be refreshed."})
    if (start_date is None) != (end_date is None):
        raise ValidationError({"date": "Both start_date and end_date are required."})
    if start_date is not None and (start_date > end_date or (end_date - start_date).days > 30):
        raise ValidationError({"date": "Refresh requires an ordered range of at most 31 days."})
    if start_date is None and changed_since is None and order_ids is None:
        raise ValidationError({"scope": "A date range, changed_since or explicit order_ids is required."})
    if order_ids is not None and (
        not isinstance(order_ids, (list, tuple)) or len(order_ids) > 5000
        or any(type(pk) is not int or pk <= 0 for pk in order_ids)
    ):
        raise ValidationError({"order_ids": "Provide at most 5000 positive integer snapshot IDs."})
    if changed_since is not None and (not isinstance(changed_since, datetime) or timezone.is_naive(changed_since)):
        raise ValidationError({"changed_since": "Provide an aware datetime."})
    if type(deletion_limit) is not int or not 0 <= deletion_limit <= 10000:
        raise ValidationError({"deletion_limit": "Deletion limit must be between 0 and 10000; larger cleanup requires approval."})
    # Same tenant-first lock order as imports/tasks, including direct command calls.
    Tenant.objects.select_for_update().get(pk=tenant.pk)
    if AffiliateImportState.objects.filter(
        tenant=tenant, status=AffiliateImportState.Status.RUNNING, lease_expires_at__gt=timezone.now(),
    ).exclude(lease_token="").exists():
        raise ValidationError({"import": "An affiliate import is active; retry after its lease is released."})
    scoped_orders = AffiliateOrderSnapshot.objects.filter(tenant=tenant)
    if start_date is not None:
        start_dt, end_dt = _performance_bounds(start_date, end_date)
        scoped_orders = scoped_orders.filter(data_time__gte=start_dt, data_time__lt=end_dt)
    if changed_since is not None or order_ids is not None:
        changed = Q(pk__in=order_ids or [])
        if changed_since is not None:
            changed |= Q(updated_at__gte=changed_since)
        scoped_orders = scoped_orders.filter(changed)
    if not scoped_orders.exists():
        return {"created": 0, "updated": 0, "noop": 0, "rejected": 0, "deleted": 0,
                "deferred_out_of_scope_duplicates": 0, "rule_version": effective_rule_version}
    samples = list(
        BdSampleAttributionSnapshot.objects.filter(
            tenant=tenant,
            fulfillment__tenant=tenant,
            fulfillment__is_deleted=False,
        ).select_related("owner", "influencer", "store").order_by("sampled_at", "fulfillment_id", "id")
    )
    sample_groups = _group_sample_candidates(
        samples,
        product_required=attribution == "strict",
    )
    orders_by_key = {}
    rejected = deferred = 0
    # An incremental batch cannot move/delete a different snapshot outside its
    # scope just to reconcile a duplicate business line. Defer that key until a
    # scoped range reconciliation, rather than create a second attribution.
    outside = BdOrderAttributionSnapshot.objects.filter(
        tenant=tenant, rule_version=effective_rule_version, order_snapshot__tenant=tenant,
    ).exclude(order_snapshot__in=scoped_orders)
    keys = ("shop_abbr", "site", "order_id", "sku_id")
    outside_keys = set()
    candidate_keys = {
        tuple(str(value or "").strip().casefold() for value in values)
        for values in scoped_orders.values_list(*keys).iterator(chunk_size=1000)
    }
    # Stream once and retain only collisions with this batch. An unrelated
    # tenant history must not impose a quota on legitimate new order lines.
    for values in outside.order_by().values_list(*[
        f"order_snapshot__{key}" for key in keys
    ]).iterator(chunk_size=1000):
        key = tuple(str(value or "").strip().casefold() for value in values)
        if key in candidate_keys:
            outside_keys.add(key)
    for order in scoped_orders.order_by("data_time", "id").iterator(chunk_size=1000):
        if _valid_order(order):
            if _order_attribution_key(order) in outside_keys:
                deferred += 1
                continue
            orders_by_key.setdefault(_order_attribution_key(order), order)
        else:
            rejected += 1
    existing = {}
    duplicate_existing_ids = []
    for item in BdOrderAttributionSnapshot.objects.filter(
        tenant=tenant, rule_version=effective_rule_version,
        order_snapshot__tenant=tenant, order_snapshot__in=scoped_orders,
    ).select_related("order_snapshot").order_by("id"):
        key = _order_attribution_key(item.order_snapshot)
        if key in existing:
            duplicate_existing_ids.append(item.pk)
        else:
            existing[key] = item
    created = updated = noop = deleted = 0
    desired_keys = set()
    for key, order in sorted(orders_by_key.items(), key=lambda item: (item[1].data_time, item[1].id)):
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
    if len(stale_ids) > deletion_limit:
        raise ValidationError({"cleanup": "Scoped deletion limit exceeded; explicit operator approval/reconciliation required."})
    if stale_ids:
        deleted, _ = BdOrderAttributionSnapshot.objects.filter(
            tenant=tenant,
            rule_version=effective_rule_version,
            pk__in=stale_ids,
            order_snapshot__in=scoped_orders,
        ).delete()
    return {
        "created": created,
        "updated": updated,
        "noop": noop,
        "rejected": rejected,
        "deleted": deleted,
        "deferred_out_of_scope_duplicates": deferred,
        "rule_version": effective_rule_version,
    }


def _owner_bucket():
    return {
        "eligibility_complete": True,
        "sample_count": 0,
        "shipped_count": 0,
        "valid_order_count": 0,
        "item_quantity": 0,
        "gmv_cny": Decimal("0"),
        **{component: Decimal("0") for component in COST_COMPONENTS},
        **{f"missing_{component}_count": 0 for component in COST_COMPONENTS},
        **{f"missing_{component}_exchange_rate_count": 0 for component in COST_COMPONENTS},
        **{f"missing_{component}_exchange_rates": set() for component in COST_COMPONENTS},
        # Keep source-currency GMV separate. Cross-country values must never
        # be added together merely because the dashboard is viewed as a table.
        "native_gmv": {currency: Decimal("0") for currency in ("PHP", "MYR", "THB")},
        "country_breakdown": {
            code: {
                "country_code": code,
                "country": name,
                "currency": country_currency,
                "sample_count": 0,
                "shipped_count": 0,
                "order_ids": set(),
                "gmv": Decimal("0"),
                "missing_base_count": 0,
            }
            for code, name, country_currency in COUNTRY_CURRENCY_BREAKDOWN
        },
        "missing_estimated_commission_base_count": 0,
        "missing_base_currencies": set(),
        "missing_amount_exchange_rate_count": 0,
        "missing_amount_exchange_rates": set(),
        "order_ids": set(),
        "missing_exchange_rates": set(),
    }


def _serialize_metrics(bucket, currency):
    # Monetary buckets are already converted to the requested display currency.
    gmv = bucket["gmv_cny"]
    costs = {}
    completeness = {}
    for component in COST_COMPONENTS:
        complete = (
            not bucket[f"missing_{component}_count"]
            and not bucket[f"missing_{component}_exchange_rate_count"]
            and (component == "sample_cost" or bucket["eligibility_complete"])
        )
        completeness[component] = complete
        costs[component] = _format_money(bucket[component]) if complete else None
        costs[f"known_{component}"] = _format_money(bucket[component])
        costs[f"{component}_complete"] = complete
        costs[f"missing_{component}_count"] = bucket[f"missing_{component}_count"]
        costs[f"missing_{component}_exchange_rate_count"] = bucket[f"missing_{component}_exchange_rate_count"]
    with localcontext() as context:
        context.prec = max(
            context.prec,
            max(bucket[component].adjusted() for component in COST_COMPONENTS)
            - min(bucket[component].as_tuple().exponent for component in COST_COMPONENTS) + 3,
        )
        # Partial components contribute independently, not just fully known rows.
        total_cost = sum((bucket[component] for component in COST_COMPONENTS), Decimal("0"))
    cost_complete = all(completeness.values())
    costs.update(
        total_cost=_format_money(total_cost) if cost_complete else None,
        known_total_cost=_format_money(total_cost),
        cost_complete=cost_complete,
    )
    amount_complete = (
        bucket["missing_estimated_commission_base_count"] == 0
        and not bucket["missing_amount_exchange_rate_count"]
        and bucket["eligibility_complete"]
    )
    roi = None
    if total_cost > 0 and amount_complete and cost_complete:
        with localcontext() as context:
            context.prec = max(context.prec, gmv.adjusted() - total_cost.adjusted() + 8)
            roi = gmv / total_cost
    native_gmv = {
        native_currency: (
            None if not bucket["eligibility_complete"] or native_currency in bucket["missing_base_currencies"]
            else _format_money(bucket["native_gmv"].get(native_currency, Decimal("0")))
        )
        for native_currency in ("PHP", "MYR", "THB")
    }
    country_breakdown = []
    for code, _, _ in COUNTRY_CURRENCY_BREAKDOWN:
        country = bucket["country_breakdown"][code]
        country_breakdown.append(
            {
                "country_code": country["country_code"],
                "country": country["country"],
                "currency": country["currency"],
                "sample_count": country["sample_count"],
                "shipped_count": country["shipped_count"],
                "valid_order_count": len(country["order_ids"]),
                "gmv": None if not bucket["eligibility_complete"] or country["missing_base_count"] else _format_money(country["gmv"]),
            }
        )
    return {
        "sample_count": bucket["sample_count"],
        "samples": bucket["sample_count"],
        "shipped_count": bucket["shipped_count"],
        "shipped_samples": bucket["shipped_count"],
        "currency": currency,
        "cost_basis": BD_COST_BASIS,
        **costs,
        "investment": costs["total_cost"],
        "valid_order_count": len(bucket["order_ids"]),
        "valid_orders": len(bucket["order_ids"]),
        "item_quantity": bucket["item_quantity"],
        "quantity": bucket["item_quantity"],
        "gmv": _format_money(gmv) if amount_complete else None,
        "estimated_commission_base": _format_money(gmv) if amount_complete else None,
        "known_estimated_commission_base": _format_money(gmv),
        "known_native_gmv": {
            native_currency: _format_money(bucket["native_gmv"][native_currency])
            for native_currency in ("PHP", "MYR", "THB")
        },
        "amount_basis": "estimated_commission_base",
        "amount_complete": amount_complete,
        "eligibility_complete": bucket["eligibility_complete"],
        "metric_scope": "verified_eligible_attributed_subset",
        "commission": costs["actual_standard_commission"],
        "native_gmv": native_gmv,
        "gmv_php": native_gmv["PHP"],
        "gmv_myr": native_gmv["MYR"],
        "gmv_thb": native_gmv["THB"],
        "country_breakdown": country_breakdown,
        "missing_commission_count": bucket["missing_actual_standard_commission_count"],
        "missing_estimated_commission_base_count": bucket["missing_estimated_commission_base_count"],
        "missing_amount_exchange_rate_count": bucket["missing_amount_exchange_rate_count"],
        "missing_cost_count": bucket["missing_sample_cost_count"],
        "roi": _format_money(roi) if roi is not None else None,
    }


def build_bd_performance(
    *, tenant, start_date, end_date, attribution="strict", currency="CNY",
    max_data_time=_MAX_DATA_TIME_UNSET,
):
    if currency not in PERFORMANCE_CURRENCIES:
        raise ValidationError({"currency": "Currency must be CNY, PHP, MYR, THB or USD."})
    if attribution not in {"strict", "fallback"}:
        raise ValidationError({"attribution": "Attribution must be strict or fallback."})
    if start_date > end_date:
        raise ValidationError({"date": "start_date must not be after end_date."})
    if (end_date - start_date).days > 30:
        raise ValidationError({"date": "The date range must not exceed 31 days."})

    start_dt, end_dt = _performance_bounds(start_date, end_date)
    scoped_facts = AffiliateOrderSnapshot.objects.filter(
        tenant=tenant, data_time__gte=start_dt, data_time__lt=end_dt,
    ).annotate(_refund=Lower(Trim("fully_returned")), _settlement=Trim("settlement_status"))
    known_settlements = [value for value, _ in SETTLEMENT_CHOICES]
    coverage = scoped_facts.aggregate(
        order_row_count=Count("pk"),
        settlement_known_count=Count("pk", filter=Q(_settlement__in=known_settlements)),
        settlement_missing_count=Count("pk", filter=Q(_settlement__isnull=True) | Q(_settlement="")),
        refund_known_count=Count("pk", filter=Q(_refund__in=NO_REFUND_MARKERS | REFUND_MARKERS)),
        refund_missing_count=Count("pk", filter=Q(_refund__isnull=True) | Q(_refund="")),
    )
    fact_count = coverage["order_row_count"]
    for field in ("settlement", "refund"):
        coverage[f"{field}_unknown_count"] = (
            fact_count - coverage[f"{field}_known_count"] - coverage[f"{field}_missing_count"]
        )
        coverage[f"{field}_coverage"] = (
            coverage[f"{field}_known_count"] / fact_count if fact_count else None
        )
    eligibility_complete = bool(fact_count) and all(
        coverage[f"{field}_known_count"] == fact_count for field in ("settlement", "refund")
    )
    eligible_keys = {
        tuple(str(value or "").strip().casefold() for value in values)
        for values in scoped_facts.filter(_settlement=SETTLED, _refund__in=NO_REFUND_MARKERS)
        .order_by().values_list("shop_abbr", "site", "order_id", "sku_id").iterator(chunk_size=1000)
    }
    eligible_line_count = len(eligible_keys)
    buckets = defaultdict(_owner_bucket)
    owner_ids = set()
    rate_resolver = _RateResolver(tenant)

    def _record_rate_details(bucket, details, *, metric=None):
        missing = False
        for detail in details:
            if detail.get("source") == "missing":
                missing = True
                base_currency = str(detail.get("base_currency") or "").upper()
                if base_currency:
                    bucket["missing_exchange_rates"].add(base_currency)
                    if metric:
                        bucket[f"missing_{metric}_exchange_rates"].add(base_currency)
        return missing

    def _accumulate_cost(bucket, component, amount, source_currency, on_date):
        if amount is None:
            bucket[f"missing_{component}_count"] += 1
            return
        converted, details = rate_resolver.convert(amount, source_currency, currency, on_date)
        _record_rate_details(bucket, details, metric=component)
        if converted is None:
            bucket[f"missing_{component}_exchange_rate_count"] += 1
        else:
            bucket[component] = rate_resolver.add_converted(bucket[component], converted)

    # Sample facts, not outreach-task ownership or lifecycle, define BD performance.
    sample_rows = BdSampleAttributionSnapshot.objects.filter(
        tenant=tenant,
        fulfillment__tenant=tenant,
        fulfillment__is_deleted=False,
        sampled_at__gte=start_dt,
        sampled_at__lt=end_dt,
    ).values(
        "owner_id", "site", "store__country_code", "cost_amount", "currency",
        "sampled_at", "sample_status", "shipped_at",
    ).order_by("id")
    for row in sample_rows.iterator(chunk_size=1000):
        bucket = buckets[row["owner_id"]]
        bucket["sample_count"] += 1
        country = bucket["country_breakdown"].get(
            _country_code(row["site"]) or _country_code(row["store__country_code"])
        )
        if country:
            country["sample_count"] += 1
        if (
            row["sample_status"] in SHIPPED_SAMPLE_STATUSES
            or row["shipped_at"] is not None
        ):
            bucket["shipped_count"] += 1
            if country:
                country["shipped_count"] += 1
        _accumulate_cost(
            bucket, "sample_cost", row["cost_amount"], row["currency"], _local_date(row["sampled_at"]),
        )
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
        ).annotate(
            _refund=Lower(Trim("order_snapshot__fully_returned")),
            _settlement=Trim("order_snapshot__settlement_status"),
        ).filter(
            _settlement=SETTLED, _refund__in=NO_REFUND_MARKERS,
        )
        .values(
            "sample_attribution__owner_id",
            "order_snapshot_id",
            "order_snapshot__source",
            "order_snapshot__source_row_key",
            "order_snapshot__shop_abbr",
            "order_snapshot__site",
            "order_snapshot__order_id",
            "order_snapshot__sku_id",
            "order_snapshot__data_time",
            "order_snapshot__quantity",
            "order_snapshot__estimated_commission_base",
            "order_snapshot__currency",
            "sample_attribution__site",
            "order_snapshot__actual_paid_commission",
            "order_snapshot__actual_paid_shop_ads_commission",
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
        # Keep this guard aligned with the business identity so legacy
        # duplicate attribution rows cannot inflate GMV/quantity.
        line_key = (
            str(row["order_snapshot__shop_abbr"] or "").strip().casefold(),
            str(row["order_snapshot__site"] or "").strip().casefold(),
            str(row["order_snapshot__order_id"] or "").strip().casefold(),
            str(row["order_snapshot__sku_id"] or "").strip().casefold(),
        )
        if line_key in seen_lines:
            continue
        seen_lines.add(line_key)
        # The linked sample attribution is the authoritative frozen owner
        # fact.  The denormalized order owner can temporarily lag after a
        # controlled historical-owner correction, so reporting must not use
        # that stale copy.
        owner_id = row["sample_attribution__owner_id"]
        bucket = buckets[owner_id]
        bucket["order_ids"].add(str(row["order_snapshot__order_id"] or "").strip())
        bucket["item_quantity"] += row["order_snapshot__quantity"] or 0
        source_currency = str(row["order_snapshot__currency"] or "").upper()
        base_amount = row["order_snapshot__estimated_commission_base"]
        # Missing source facts stay missing; never substitute payment or commission.
        if base_amount is None:
            bucket["missing_estimated_commission_base_count"] += 1
            bucket["missing_base_currencies"].add(source_currency)
        if source_currency in bucket["native_gmv"]:
            bucket["native_gmv"][source_currency] += _money(
                base_amount
            )
        country = bucket["country_breakdown"].get(
            _country_code(source_currency) or _country_code(row["sample_attribution__site"])
        )
        if country:
            country["order_ids"].add(str(row["order_snapshot__order_id"] or "").strip())
            country["gmv"] += _money(base_amount)
            country["missing_base_count"] += base_amount is None
        if base_amount is None or base_amount == 0:
            converted, details = Decimal("0"), []
        else:
            converted, details = rate_resolver.convert(
                base_amount,
                source_currency,
                currency,
                _local_date(row["order_snapshot__data_time"]),
            )
        if _record_rate_details(bucket, details, metric="amount"):
            bucket["missing_amount_exchange_rate_count"] += 1
        if converted is not None:
            bucket["gmv_cny"] = rate_resolver.add_converted(bucket["gmv_cny"], converted)
        # GMV absence/FX failure must not hide independently known commissions.
        for component, field in ACTUAL_COMMISSION_FIELDS:
            _accumulate_cost(
                bucket, component, row[f"order_snapshot__{field}"], source_currency,
                _local_date(row["order_snapshot__data_time"]),
            )
        owner_ids.add(owner_id)

    users = {
        row["id"]: row
        for row in get_user_model().objects.filter(tenant=tenant, pk__in=owner_ids).values(
            "id", "username", "full_name"
        )
    }
    rows = []
    for owner_id in sorted(owner_ids):
        buckets[owner_id]["eligibility_complete"] = eligibility_complete
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
    total_bucket["eligibility_complete"] = eligibility_complete
    for bucket in buckets.values():
        total_bucket["sample_count"] += bucket["sample_count"]
        total_bucket["shipped_count"] += bucket["shipped_count"]
        total_bucket["item_quantity"] += bucket["item_quantity"]
        total_bucket["gmv_cny"] = rate_resolver.add_converted(total_bucket["gmv_cny"], bucket["gmv_cny"])
        for component in COST_COMPONENTS:
            total_bucket[component] = rate_resolver.add_converted(total_bucket[component], bucket[component])
            total_bucket[f"missing_{component}_count"] += bucket[f"missing_{component}_count"]
            total_bucket[f"missing_{component}_exchange_rate_count"] += bucket[f"missing_{component}_exchange_rate_count"]
            total_bucket[f"missing_{component}_exchange_rates"].update(bucket[f"missing_{component}_exchange_rates"])
        for native_currency, amount in bucket["native_gmv"].items():
            total_bucket["native_gmv"][native_currency] += amount
        for code, country in bucket["country_breakdown"].items():
            total_country = total_bucket["country_breakdown"][code]
            total_country["sample_count"] += country["sample_count"]
            total_country["shipped_count"] += country["shipped_count"]
            total_country["order_ids"].update(country["order_ids"])
            total_country["gmv"] += country["gmv"]
            total_country["missing_base_count"] += country["missing_base_count"]
        total_bucket["missing_estimated_commission_base_count"] += bucket["missing_estimated_commission_base_count"]
        total_bucket["missing_base_currencies"].update(bucket["missing_base_currencies"])
        total_bucket["missing_amount_exchange_rate_count"] += bucket["missing_amount_exchange_rate_count"]
        total_bucket["missing_amount_exchange_rates"].update(bucket["missing_amount_exchange_rates"])
        total_bucket["order_ids"].update(bucket["order_ids"])
        total_bucket["missing_exchange_rates"].update(bucket["missing_exchange_rates"])

    if max_data_time is _MAX_DATA_TIME_UNSET:
        max_data_time = AffiliateOrderSnapshot.objects.filter(tenant=tenant).aggregate(
            max_data_time=Max("data_time")
        )["max_data_time"]
    has_orders = max_data_time is not None
    has_samples = BdSampleAttributionSnapshot.objects.filter(
        tenant=tenant,
        fulfillment__tenant=tenant,
        fulfillment__is_deleted=False,
    ).exists()
    has_attributions = bool(seen_lines)
    if not has_orders:
        source_status = "not_imported"
    elif not eligibility_complete:
        source_status = "incomplete"
    elif not has_samples:
        source_status = "awaiting_fulfillment_data"
    elif not has_attributions:
        source_status = "empty"
    else:
        source_status = "ready"

    data_as_of = timezone.localtime(max_data_time).date().isoformat() if max_data_time else None
    diagnostic_reasons = []
    if not fact_count:
        diagnostic_reasons.append("no_orders_in_range")
    for field in ("settlement", "refund"):
        if coverage[f"{field}_missing_count"]:
            diagnostic_reasons.append(f"missing_{field}_status")
        if coverage[f"{field}_unknown_count"]:
            diagnostic_reasons.append(f"unknown_{field}_status")
    if not has_orders:
        diagnostic_reasons.append("orders_not_imported")
    elif not has_samples:
        diagnostic_reasons.append("no_active_samples")
    elif not has_attributions:
        diagnostic_reasons.append("no_sample_match")
    if total_bucket["missing_exchange_rates"]:
        diagnostic_reasons.append("missing_exchange_rate")
    if total_bucket["missing_estimated_commission_base_count"]:
        diagnostic_reasons.append("missing_estimated_commission_base")
    if total_bucket["missing_sample_cost_count"]:
        diagnostic_reasons.append("missing_sample_cost")
    for component, _ in ACTUAL_COMMISSION_FIELDS:
        if total_bucket[f"missing_{component}_count"]:
            diagnostic_reasons.append(f"missing_{component}")
    if not diagnostic_reasons and total_bucket["gmv_cny"] == 0:
        diagnostic_reasons.append("zero_estimated_commission_base")
    zero_gmv_diagnostic = {
        "is_zero_gmv": (
            total_bucket["gmv_cny"] == 0
            and eligibility_complete
            and not total_bucket["missing_estimated_commission_base_count"]
            and not total_bucket["missing_amount_exchange_rate_count"]
        ),
        "reason_codes": diagnostic_reasons,
        "missing_estimated_commission_base_count": total_bucket["missing_estimated_commission_base_count"],
        "missing_cost_count": total_bucket["missing_sample_cost_count"],
        "missing_sample_cost_count": total_bucket["missing_sample_cost_count"],
        "missing_actual_standard_commission_count": total_bucket["missing_actual_standard_commission_count"],
        "missing_actual_ads_commission_count": total_bucket["missing_actual_ads_commission_count"],
        **{
            f"missing_{component}_exchange_rate_count": total_bucket[f"missing_{component}_exchange_rate_count"]
            for component in COST_COMPONENTS
        },
        "missing_exchange_rates": sorted(total_bucket["missing_exchange_rates"]),
        "eligibility_complete": eligibility_complete,
        "settlement_missing_count": coverage["settlement_missing_count"],
        "settlement_unknown_count": coverage["settlement_unknown_count"],
        "settlement_coverage": coverage["settlement_coverage"],
        "refund_missing_count": coverage["refund_missing_count"],
        "refund_unknown_count": coverage["refund_unknown_count"],
        "refund_coverage": coverage["refund_coverage"],
        "metric_scope": "verified_eligible_attributed_subset",
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
        "amount_basis": "estimated_commission_base",
        "cost_basis": BD_COST_BASIS,
        "amount_label": "预估计佣金额",
        "rates": rates,
        "rate_details": rate_details,
        **rate_resolver.metadata(),
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
        "eligibility_diagnostic": {
            **coverage,
            "eligibility_complete": eligibility_complete,
            "verified_eligible_line_count": eligible_line_count,
            "verified_attributed_line_count": len(seen_lines),
            "valid_unmatched_line_count": max(0, eligible_line_count - len(seen_lines)),
            "rule": "settled_and_explicitly_not_fully_returned",
            "metric_scope": "verified_eligible_attributed_subset",
        },
        "data_as_of": data_as_of,
        "rule_version": rule_version_for(attribution),
        "source_status": source_status,
        "rows": rows,
        "results": rows,
        "totals": _serialize_metrics(total_bucket, currency),
    }


def default_performance_dates(*, tenant, max_data_time=_MAX_DATA_TIME_UNSET):
    today = timezone.localdate()
    yesterday = today - timedelta(days=1)
    if max_data_time is _MAX_DATA_TIME_UNSET:
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
    ).filter(is_deleted=False)
    if tenant is not None:
        queryset = queryset.filter(tenant=tenant)
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
