"""Exact TK settlement values; missing amounts must never become zero."""

import re
from decimal import Decimal, InvalidOperation

from rest_framework.exceptions import ValidationError


def amount(value, currency):
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValidationError("TK_FINANCE_CURRENCY_REQUIRED")
    if isinstance(value, dict):
        nested_currency = value.get("currency")
        if nested_currency is not None and nested_currency != currency:
            raise ValidationError("TK_FINANCE_CURRENCY_MISMATCH")
        value = value.get("amount")
    if isinstance(value, (bool, float)) or value in (None, ""):
        raise ValidationError("TK_FINANCE_AMOUNT_MISSING_OR_INVALID")
    try:
        number = Decimal(value)
        if (not number.is_finite() or abs(number) >= Decimal("1e16")
                or number != number.quantize(Decimal("0.0001"))):
            raise InvalidOperation
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError("TK_FINANCE_AMOUNT_MISSING_OR_INVALID") from None
    return str(number)


def records(data, key, maximum):
    rows = data.get(key) if isinstance(data, dict) else None
    if not isinstance(rows, list) or len(rows) > maximum or any(not isinstance(row, dict) for row in rows):
        raise ValidationError("TK_FINANCE_RECORD_LIST_INVALID")
    return rows


def page_token(data):
    value = data.get("next_page_token", "")
    if (not isinstance(value, str) or len(value) > 4096 or value != value.strip()
            or any(ord(char) < 32 for char in value)):
        raise ValidationError("TK_FINANCE_PAGE_TOKEN_INVALID")
    return value
