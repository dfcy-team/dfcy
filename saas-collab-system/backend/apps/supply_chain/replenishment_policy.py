"""Validation helpers for saved per-SKU replenishment overrides."""
from datetime import date
from decimal import Decimal, InvalidOperation

from rest_framework.exceptions import ValidationError


SKU_POLICY_MODES = {"weighted", "ordinary", "low_frequency", "manual"}
_ALLOWED_FIELDS = {
    "mode", "manual_daily_sales", "safety_days", "lead_days",
    "purchase_multiple", "carton_quantity", "minimum_order",
    "sales_window_days", "activity_start", "activity_end", "activity_factor",
}


def _decimal(value, field, *, minimum=Decimal("0"), maximum=Decimal("1000000000")):
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} must be numeric") from None
    if not result.is_finite() or not minimum <= result <= maximum:
        raise ValueError(f"{field} is outside the allowed range")
    return result


def _integer(value, field, *, minimum, maximum):
    decimal_value = _decimal(value, field, minimum=Decimal(minimum), maximum=Decimal(maximum))
    if decimal_value != decimal_value.to_integral_value():
        raise ValueError(f"{field} must be an integer")
    return int(decimal_value)


def _iso_date(value, field):
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO date")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError(f"{field} must be an ISO date") from None


def validate_sku_policies(value, actor=None, country=None):
    """Validate and normalize `{sku_id: policy}` JSON.

    When actor is supplied, every SKU and optional country must belong to the
    actor's tenant. Returns a normalized dict with string SKU IDs; low frequency
    policies default to a 90-day sales window.
    """
    if not isinstance(value, dict):
        raise ValidationError({"sku_policies": "Must be an object keyed by SKU ID."})
    errors = {}
    normalized = {}
    sku_ids = []
    for raw_id, raw_policy in value.items():
        key = str(raw_id)
        try:
            sku_id = _integer(raw_id, "sku_id", minimum=1, maximum=2**63 - 1)
        except ValueError as exc:
            errors[key] = str(exc)
            continue
        if str(sku_id) != key or not isinstance(raw_policy, dict):
            errors[key] = "SKU IDs must be canonical positive integers and policy must be an object."
            continue
        unknown = set(raw_policy) - _ALLOWED_FIELDS
        if unknown:
            errors[key] = f"Unsupported policy fields: {', '.join(sorted(unknown))}."
            continue
        try:
            mode = raw_policy.get("mode", "weighted")
            if mode not in SKU_POLICY_MODES:
                raise ValueError("mode must be weighted, ordinary, low_frequency, or manual")
            item = {"mode": mode}
            if mode == "manual" and raw_policy.get("manual_daily_sales") in (None, ""):
                raise ValueError("manual mode requires manual_daily_sales")
            if raw_policy.get("manual_daily_sales") not in (None, ""):
                item["manual_daily_sales"] = str(_decimal(raw_policy["manual_daily_sales"], "manual_daily_sales"))
            for field, hi in (("safety_days", 365), ("lead_days", 365)):
                if raw_policy.get(field) not in (None, ""):
                    item[field] = _integer(raw_policy[field], field, minimum=0 if field == "safety_days" else 1, maximum=hi)
            for field in ("purchase_multiple", "carton_quantity"):
                if raw_policy.get(field) not in (None, ""):
                    item[field] = _integer(raw_policy[field], field, minimum=1, maximum=1_000_000_000)
            if raw_policy.get("minimum_order") not in (None, ""):
                item["minimum_order"] = _integer(raw_policy["minimum_order"], "minimum_order", minimum=0, maximum=1_000_000_000)
            if mode == "low_frequency":
                window_days = _integer(raw_policy.get("sales_window_days", 90), "sales_window_days", minimum=90, maximum=90)
                item["sales_window_days"] = window_days
            elif raw_policy.get("sales_window_days") not in (None, ""):
                raise ValueError("sales_window_days is only supported for low_frequency mode")
            start, end = raw_policy.get("activity_start"), raw_policy.get("activity_end")
            factor = raw_policy.get("activity_factor")
            if any(v not in (None, "") for v in (start, end, factor)):
                if not start or not end or factor in (None, ""):
                    raise ValueError("activity_start, activity_end and activity_factor must be supplied together")
                item["activity_start"] = _iso_date(start, "activity_start")
                item["activity_end"] = _iso_date(end, "activity_end")
                if item["activity_end"] < item["activity_start"]:
                    raise ValueError("activity_end must not precede activity_start")
                item["activity_factor"] = str(_decimal(factor, "activity_factor", minimum=Decimal("0.01"), maximum=Decimal("10")))
            normalized[str(sku_id)] = item
            sku_ids.append(sku_id)
        except ValueError as exc:
            errors[key] = str(exc)
    if actor is not None and sku_ids:
        from apps.products.models import ProductSKU
        tenant_id = getattr(actor, "tenant_id", None)
        if not tenant_id:
            errors["sku_policies"] = "Actor must belong to a tenant."
        else:
            existing = set(ProductSKU.objects.filter(tenant_id=tenant_id, pk__in=sku_ids).values_list("pk", flat=True))
            for sku_id in sku_ids:
                if sku_id not in existing:
                    errors[str(sku_id)] = "SKU does not belong to the actor's tenant."
    if actor is not None and country is not None:
        if getattr(country, "tenant_id", None) != getattr(actor, "tenant_id", None):
            errors["country"] = "Country does not belong to the actor's tenant."
    if errors:
        raise ValidationError({"sku_policies": errors})
    return normalized
