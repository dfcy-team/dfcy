"""Local registration calculations; no inventory, payment or platform effects."""
from datetime import date, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.utils.dateparse import parse_datetime

from rest_framework.exceptions import ValidationError


CURRENCY_DIGITS = {code: 2 for code in ("PHP", "CNY", "USD", "MYR", "THB", "SGD", "BRL", "HKD", "EUR", "TWD", "IDR")}
CURRENCY_DIGITS.update(JPY=0, VND=0, KRW=0)


def gcash_remark(reason, note):
    reason, note = str(reason or "").strip(), str(note or "").strip()
    if reason and note and reason != note:
        return f"原因：{reason}；用途：{note}"
    return reason or note


def gcash_payment_date(value):
    try:
        if isinstance(value, str) and len(value) == 10:
            result = date.fromisoformat(value).isoformat()
            if result == value:
                return result
        # Preserve compatibility with existing timezone-aware registration records.
        legacy = parse_datetime(value) if isinstance(value, str) else None
        if legacy and legacy.utcoffset() is not None:
            return legacy.astimezone(timezone(timedelta(hours=8))).date().isoformat()
    except (ValueError, TypeError, OverflowError):
        pass
    raise ValidationError({"paid_at": "付款日期必须为有效的 YYYY-MM-DD 日期。"})


def decimal_value(value, field, *, positive=False):
    try:
        if isinstance(value, (bool, float)):
            raise ValueError()
        result = Decimal(str(value))
        if not result.is_finite() or result < 0 or (positive and result == 0) or result >= Decimal("1e16"):
            raise ValueError()
        return result
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError({field: "请输入有效的非负十进制金额／汇率；汇率必须大于零。"}) from None


def money(value, currency, field):
    if currency not in CURRENCY_DIGITS:
        raise ValidationError({field: "该币种尚未登记金额精度，请先确认币种。"})
    amount = decimal_value(value, field)
    quantum = Decimal(1).scaleb(-CURRENCY_DIGITS[currency])
    if amount != amount.quantize(quantum):
        raise ValidationError({field: f"金额最多允许 {CURRENCY_DIGITS[currency]} 位小数。"})
    return amount.quantize(quantum)


def promotion_cost(data, currency):
    amount = money(data.get("order_amount"), currency, "order_amount")
    fee_currency = data.get("fee_currency", "")
    fee = money(data.get("fee_amount"), fee_currency, "fee_amount")
    if fee_currency == currency:
        rate = Decimal(1)
        if data.get("exchange_rate") not in (None, "", "1", 1):
            raise ValidationError({"exchange_rate": "同币种汇率必须为 1。"})
    else:
        rate = decimal_value(data.get("exchange_rate"), "exchange_rate", positive=True)
        if rate.as_tuple().exponent < -10:
            raise ValidationError({"exchange_rate": "汇率最多允许 10 位小数。"})
        if not data.get("rate_date") or not str(data.get("rate_source", "")).strip():
            raise ValidationError("跨币种必须填写汇率日期和来源。")
    cost = (amount + fee * rate).quantize(Decimal(1).scaleb(-CURRENCY_DIGITS[currency]), rounding=ROUND_HALF_UP)
    return {"currency": currency, "order_amount": str(amount), "fee_amount": str(fee),
            "fee_currency": fee_currency, "exchange_rate": str(rate), "cost": str(cost),
            "rate_date": data.get("rate_date", ""), "rate_source": data.get("rate_source", "")}


def adjusted_lines(before, changes):
    """Apply only changed SKU quantities; keep the rest of the internal order."""
    quantities = {row["sku_id"]: row["quantity"] for row in before}
    if not isinstance(changes, list) or not changes or len(changes) > 200:
        raise ValidationError("请填写 1 至 200 条商品变化。")
    reductions, additions = {}, {}
    for row in changes:
        if not isinstance(row, dict) or row.get("action") not in {"replace", "add", "reduce"}:
            raise ValidationError("商品变化类型必须为替换、增加或减少。")
        if set(row) - {"action", "old_sku_id", "new_sku_id", "reduce_quantity", "add_quantity"}:
            raise ValidationError("商品变化包含未支持字段。")
        for field, qty_field, total in (("old_sku_id", "reduce_quantity", reductions), ("new_sku_id", "add_quantity", additions)):
            needed = row["action"] == "replace" or (row["action"] == "reduce" and field == "old_sku_id") or (row["action"] == "add" and field == "new_sku_id")
            if not needed:
                if row.get(field) or row.get(qty_field):
                    raise ValidationError("变化类型与商品字段不一致。")
                continue
            sku, quantity = row.get(field), row.get(qty_field)
            if type(sku) is not int or sku <= 0 or type(quantity) is not int or not 0 < quantity <= 1000000:
                raise ValidationError("商品和数量必须为正整数。")
            total[sku] = total.get(sku, 0) + quantity
    for sku, quantity in reductions.items():
        if quantity > quantities.get(sku, 0):
            raise ValidationError("减少数量超过当前待发货数量。")
        quantities[sku] -= quantity
    for sku, quantity in additions.items():
        quantities[sku] = quantities.get(sku, 0) + quantity
    if not any(quantities.values()):
        raise ValidationError("调整后必须至少保留一件商品。")
    if any(quantity > 1000000 for quantity in quantities.values()):
        raise ValidationError("单个商品数量超出登记上限。")
    return [{"sku_id": sku, "quantity": quantity} for sku, quantity in sorted(quantities.items()) if quantity]
