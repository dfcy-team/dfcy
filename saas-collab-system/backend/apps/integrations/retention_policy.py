"""API fact retention floor and date interpretation helpers."""
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError


RETENTION_START = date(2025, 1, 1)
RETENTION_START_UTC = datetime(2025, 1, 1, tzinfo=UTC)


def fact_timezone(resource_type, store=None):
    if resource_type == "settlement_bill":
        return ZoneInfo(str(getattr(store, "timezone", None) or "UTC"))
    # Orders use their normalized UTC business_date; refund request time is UTC.
    return UTC


def retention_start_timestamp(resource_type, store=None):
    return int(datetime.combine(RETENTION_START, datetime.min.time(), fact_timezone(resource_type, store)).timestamp())


def bounded_range(start, end, resource_type, store=None):
    """Clamp a query to the retention floor, rejecting ranges wholly before it."""
    if resource_type not in {"sales_order", "refund_return", "settlement_bill", "advertising_report"}:
        return int(start), int(end)
    floor = retention_start_timestamp(resource_type, store)
    if int(end) < floor:
        raise ValidationError({"start_at": "历史查询不能早于 2025-01-01。"})
    return max(int(start), floor), int(end)


def _as_date(value, zone):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(zone).date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            if value > 10_000_000_000:
                value /= 1000
            return datetime.fromtimestamp(value, UTC).astimezone(zone).date()
        except (ValueError, OSError, OverflowError):
            return None
    text = str(value).strip()
    try:
        return datetime.strptime(text, "%d %b %Y").date()
    except ValueError:
        pass
    if text.isdigit():
        try:
            stamp = int(text)
            if stamp > 10_000_000_000:
                stamp /= 1000
            return datetime.fromtimestamp(stamp, UTC).astimezone(zone).date()
        except (ValueError, OSError, OverflowError):
            return None
    if len(text) == 10:
        try:
            return date.fromisoformat(text)
        except ValueError:
            pass
    parsed = parse_datetime(text)
    if parsed is None:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(zone).date()


def is_legacy_fact(resource_type, record, store=None):
    """Return whether a dated API fact predates retention; catalogues are timeless."""
    if not isinstance(record, dict) or resource_type == "platform_product":
        return False
    zone = fact_timezone(resource_type, store)
    if resource_type == "sales_order":
        value = record.get("business_date") or record.get("created_at") or record.get("create_time")
    elif resource_type == "refund_return":
        value = record.get("requested_at_utc") or record.get("create_time")
        if value in (None, "") and isinstance(record.get("reverse_order_lines"), list):
            values = [line.get("return_order_line_gmt_create") for line in record["reverse_order_lines"]
                      if isinstance(line, dict) and line.get("return_order_line_gmt_create")]
            value = min(values, key=lambda item: int(item)) if values else None
    elif resource_type == "settlement_bill":
        value = (record.get("transaction_date") or record.get("created_at") or record.get("occurred_at")
                 or record.get("transaction_time"))
    elif resource_type == "inventory_snapshot":
        value = (record.get("_snapshot_at_utc") or record.get("snapshot_at_utc")
                 or record.get("snapshot_date"))
    elif resource_type == "advertising_report":
        value = record.get("business_date") or record.get("date") or record.get("report_date")
    else:
        return False
    day = _as_date(value, zone)
    return day is not None and day < RETENTION_START


def skipped_fact_marker():
    return {"_retention_skipped": True}


def is_skipped_fact(record):
    return isinstance(record, dict) and record.get("_retention_skipped") is True


def skipped_result(sync_job):
    return {"action": "skipped", "idempotency_key": f"{sync_job.id}:retention-floor"}
