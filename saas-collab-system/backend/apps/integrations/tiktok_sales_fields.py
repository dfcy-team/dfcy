"""Lossless TikTok sales projection. No shared marketplace amount fallbacks."""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from rest_framework.exceptions import ValidationError


REFUND_STATUSES = {
    "RETURN_OR_REFUND_REQUEST_PENDING": "pending",
    "REFUND_OR_RETURN_REQUEST_REJECT": "rejected",
    "AWAITING_BUYER_SHIP": "processing",
    "BUYER_SHIPPED_ITEM": "processing",
    "REJECT_RECEIVE_PACKAGE": "rejected",
    "RETURN_OR_REFUND_REQUEST_SUCCESS": "processing",
    "RETURN_OR_REFUND_REQUEST_CANCEL": "cancelled",
    "RETURN_OR_REFUND_REQUEST_COMPLETE": "completed",
    "REPLACEMENT_REQUEST_PENDING": "pending",
    "REPLACEMENT_REQUEST_REJECT": "rejected",
    "REPLACEMENT_REQUEST_REFUND_SUCCESS": "processing",
    "REPLACEMENT_REQUEST_CANCEL": "cancelled",
    "REPLACEMENT_REQUEST_COMPLETE": "replacement_completed",
}


def money(value):
    if isinstance(value, (bool, float)) or value in (None, ""):
        raise ValidationError("TK_SALES_MONEY_MISSING_OR_INVALID")
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError("TK_SALES_MONEY_MISSING_OR_INVALID") from None
    if (not amount.is_finite() or amount < 0 or amount >= Decimal("1e16")
            or amount != amount.quantize(Decimal("0.0001"))):
        raise ValidationError("TK_SALES_MONEY_MISSING_OR_INVALID")
    return str(amount)


def timestamp(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).isascii() or not str(value).isdecimal():
        raise ValidationError("TK_SALES_TIMESTAMP_INVALID")
    try:
        return datetime.fromtimestamp(int(value), UTC)
    except (OverflowError, OSError, ValueError):
        raise ValidationError("TK_SALES_TIMESTAMP_INVALID") from None


def order_fields(record, store):
    payment = record.get("payment")
    if not isinstance(payment, dict):
        raise ValidationError("TK_SALES_PAYMENT_MISSING")
    try:
        zone = ZoneInfo(store.timezone)
    except (AttributeError, ZoneInfoNotFoundError, ValueError):
        raise ValidationError("TK_SALES_STORE_TIMEZONE_INVALID") from None
    fields = {
        "raw_status": str(record.get("status") or "UNKNOWN"),
        "business_date": timestamp(record.get("create_time")).astimezone(zone).date().isoformat(),
    }
    for source, target in (("sub_total", "subtotal_amount"), ("seller_discount", "seller_discount_amount"),
                           ("platform_discount", "platform_discount_amount"), ("tax", "tax_amount"),
                           ("total_amount", "gross_amount"), ("shipping_fee", "shipping_amount")):
        fields[target] = money(payment.get(source))
    # The legacy aggregate is total discount; components remain independent.
    fields["discount_amount"] = str(Decimal(fields["seller_discount_amount"]) + Decimal(fields["platform_discount_amount"]))
    for source, target in (("cancel_time", "cancelled_at_utc"), ("delivery_time", "delivered_at_utc")):
        fields[target] = timestamp(record[source]).isoformat() if record.get(source) not in (None, "", 0, "0") else None
    fields["completed_at_utc"] = None
    return fields


def order_line_fields(item, currency):
    if item.get("currency") not in (None, "", currency):
        raise ValidationError("TK_SALES_LINE_CURRENCY_MISMATCH")
    return {
        "original_unit_price": money(item.get("original_price")),
        "sale_unit_price": money(item.get("sale_price")),
        "unit_price": money(item.get("sale_price")),
        "discount_amount": str(Decimal(money(item.get("seller_discount"))) + Decimal(money(item.get("platform_discount")))),
        "variation_snapshot": str(item.get("sku_name") or ""),
        "currency": currency,
    }


def refund_status(value):
    try:
        return REFUND_STATUSES[value]
    except (KeyError, TypeError):
        raise ValidationError("TK_REFUND_STATUS_UNMAPPED") from None


def refund_money(value, currency):
    if not isinstance(value, dict) or value.get("currency") != currency:
        raise ValidationError("TK_REFUND_AMOUNT_OR_CURRENCY_INVALID")
    return money(value.get("refund_total"))
