from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.utils.dateparse import parse_datetime


FINANCE_TRANSACTION_CONTRACT_VERSION = "finance_transaction.v1"
FORBIDDEN_CREDENTIAL_KEYS = {
    "access_token",
    "refresh_token",
    "app_secret",
    "client_secret",
    "password",
    "secret_key",
}


def _reject_credentials(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).lower() in FORBIDDEN_CREDENTIAL_KEYS:
                raise ValidationError("Credential material is not accepted by the finance transaction contract.")
            _reject_credentials(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_credentials(nested)


def _required(payload, key):
    value = payload.get(key)
    if value in (None, ""):
        raise ValidationError(f"Missing required finance transaction field: {key}")
    return value


def _decimal(value, key):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(f"Finance transaction field {key} must be a decimal amount.") from exc


def _utc(value):
    parsed = value if isinstance(value, datetime) else parse_datetime(str(value or ""))
    if parsed is None or parsed.tzinfo is None:
        raise ValidationError("Finance transaction occurred_at_utc must include a timezone.")
    return parsed.astimezone(UTC)


def normalize_finance_transaction_record(record):
    _reject_credentials(record)
    payload = deepcopy(record)
    if payload.get("contract_version") != FINANCE_TRANSACTION_CONTRACT_VERSION:
        raise ValidationError("Unsupported or missing finance transaction contract version.")
    source_key = str(_required(payload, "source_key")).strip()
    currency = str(_required(payload, "currency")).strip().upper()
    if len(currency) < 3 or len(currency) > 8:
        raise ValidationError("Finance transaction currency is invalid.")
    occurred_at = _utc(_required(payload, "occurred_at_utc"))
    raw_fee_name = str(_required(payload, "raw_fee_name")).strip()
    raw_amount = _decimal(_required(payload, "raw_amount"), "raw_amount")
    return {
        "contract_version": FINANCE_TRANSACTION_CONTRACT_VERSION,
        "source_key": source_key,
        "external_transaction_id": str(payload.get("external_transaction_id") or "").strip(),
        "external_order_id": str(payload.get("external_order_id") or "").strip(),
        "external_order_item_id": str(payload.get("external_order_item_id") or "").strip(),
        "seller_sku": str(payload.get("seller_sku") or "").strip(),
        "platform_variant_id": str(payload.get("platform_variant_id") or "").strip(),
        "raw_fee_name": raw_fee_name,
        "raw_amount": str(raw_amount),
        "currency": currency,
        "occurred_at_utc": occurred_at.isoformat(),
    }


__all__ = ["FINANCE_TRANSACTION_CONTRACT_VERSION", "normalize_finance_transaction_record"]
