import re
from decimal import Decimal, InvalidOperation


NORMALIZATION_VERSION = "marketplace-fees.v2"

_FEE_RULES = {
    "ITEM_PRICE": ("income", 1),
    "ITEM_PRICE_REVERSAL": ("adjustment", -1),
    "REFUND": ("refund", -1),
    "COMMISSION": ("platform_fee", -1),
    "COMMISSION_REVERSAL": ("adjustment", 1),
    "PAYMENT_FEE": ("platform_fee", -1),
    "SHIPPING_FEE": ("logistics_fee", -1),
    "SHIPPING_ADJUSTMENT": ("adjustment", -1),
    "FREE_SHIPPING": ("logistics_fee", -1),
    "SELLER_DISCOUNT": ("discount", -1),
    "PLATFORM_DISCOUNT": ("discount", -1),
    "VOUCHER": ("discount", -1),
    "AFFILIATE_FEE": ("platform_fee", -1),
    "WITHHOLDING_TAX": ("tax", -1),
    "PROCESSING_FEE": ("platform_fee", -1),
}

_ALIASES = {
    "item price": "ITEM_PRICE",
    "item_price": "ITEM_PRICE",
    "sales": "ITEM_PRICE",
    "sales revenue": "ITEM_PRICE",
    "item price reversal": "ITEM_PRICE_REVERSAL",
    "item_price_reversal": "ITEM_PRICE_REVERSAL",
    "refund": "REFUND",
    "commission": "COMMISSION",
    "commission fee": "COMMISSION",
    "commission_fee": "COMMISSION",
    "commission reversal": "COMMISSION_REVERSAL",
    "commission_reversal": "COMMISSION_REVERSAL",
    "payment fee": "PAYMENT_FEE",
    "payment_fee": "PAYMENT_FEE",
    "shipping fee": "SHIPPING_FEE",
    "shipping_fee": "SHIPPING_FEE",
    "shipping adjustment": "SHIPPING_ADJUSTMENT",
    "shipping_adjustment": "SHIPPING_ADJUSTMENT",
    "free shipping": "FREE_SHIPPING",
    "free_shipping": "FREE_SHIPPING",
    "seller discount": "SELLER_DISCOUNT",
    "seller_discount": "SELLER_DISCOUNT",
    "platform discount": "PLATFORM_DISCOUNT",
    "platform_discount": "PLATFORM_DISCOUNT",
    "voucher": "VOUCHER",
    "affiliate fee": "AFFILIATE_FEE",
    "affiliate_fee": "AFFILIATE_FEE",
    "withholding tax": "WITHHOLDING_TAX",
    "withholding_tax": "WITHHOLDING_TAX",
    "processing fee": "PROCESSING_FEE",
    "processing_fee": "PROCESSING_FEE",
    "service fee": "PROCESSING_FEE",
    "service_fee": "PROCESSING_FEE",
    "seller transaction fee": "PAYMENT_FEE",
    "seller_transaction_fee": "PAYMENT_FEE",
    "transaction fee": "PAYMENT_FEE",
    "transaction_fee": "PAYMENT_FEE",
}


def _fee_key(raw_name):
    text = str(raw_name or "").strip()
    upper = text.upper()
    if upper in _FEE_RULES:
        return upper
    normalized = re.sub(r"[^a-z0-9_]+", " ", text.casefold()).strip()
    return _ALIASES.get(normalized, "OTHER")


def normalize_fee(raw_name, raw_amount):
    try:
        amount = Decimal(str(raw_amount))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("raw_amount must be a decimal amount") from exc
    code = _fee_key(raw_name)
    if code == "OTHER":
        category, signed = "other", amount
    else:
        category, direction = _FEE_RULES[code]
        signed = abs(amount) if direction > 0 else -abs(amount)
    return {
        "raw_fee_name": str(raw_name or "").strip(),
        "raw_amount": amount,
        "fee_code": code,
        "fee_category": category,
        "signed_amount": signed,
        "normalization_version": NORMALIZATION_VERSION,
    }


__all__ = ["NORMALIZATION_VERSION", "normalize_fee"]
