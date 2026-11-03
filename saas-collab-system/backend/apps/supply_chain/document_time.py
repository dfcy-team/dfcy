"""Business date/time projection for supply-chain document lists."""

import json
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone


_PURCHASE_REFERENCE = re.compile(r"^PHCG(\d{6})(\d{2,4})$")
_INBOUND_NUMBER = re.compile(r"^PO(\d{14})$")
_HISTORY_KEYS = ("PHHIST20261103:", "PHSUP20261103:")


def _is_history(obj):
    return (getattr(obj, "creation_key", "") or "").startswith(_HISTORY_KEYS)


def _purchase_source_date(reference_number):
    match = _PURCHASE_REFERENCE.fullmatch(reference_number or "")
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%y%m%d").date()
    except ValueError:
        return None


def _history_inbound_datetime(obj):
    if not _is_history(obj):
        return None
    lines = (getattr(obj, "notes", "") or "").splitlines()
    if len(lines) < 2:
        return None
    try:
        payload, _ = json.JSONDecoder().raw_decode(lines[1].lstrip())
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    match = _INBOUND_NUMBER.fullmatch(str(payload.get("入库单号", "")))
    if not match:
        return None
    try:
        business_tz = ZoneInfo(getattr(settings, "SUPPLY_CHAIN_TIME_ZONE", "Asia/Shanghai"))
        return datetime.strptime(match.group(1), "%Y%m%d%H%M%S").replace(tzinfo=business_tz)
    except ValueError:
        return None


def _display(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        business_tz = ZoneInfo(getattr(settings, "SUPPLY_CHAIN_TIME_ZONE", "Asia/Shanghai"))
        if timezone.is_aware(value):
            value = timezone.localtime(value, business_tz)
        else:
            value = value.replace(tzinfo=business_tz)
        return value.isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    return None


def document_time(kind, obj):
    """Return a display-safe business date/time; never fall back to created_at."""
    if kind == "purchase":
        source_date = _purchase_source_date(getattr(obj, "reference_number", "")) if _is_history(obj) else None
        value = source_date or getattr(obj, "order_date", None)
    elif kind in ("shipment", "domestic_freight"):
        value = getattr(obj, "shipment_date", None)
    elif kind == "batch":
        value = _history_inbound_datetime(obj) or getattr(obj, "departed_at", None)
    elif kind in ("inbound", "clearance"):
        batch = getattr(obj, "batch", None)
        # Inbounds have no creation_key; their source identity is on the batch.
        value = (_history_inbound_datetime(batch) or getattr(obj, "confirmed_at", None)
                 or getattr(batch, "arrived_warehouse_at", None))
    else:
        value = None
    return _display(value)
