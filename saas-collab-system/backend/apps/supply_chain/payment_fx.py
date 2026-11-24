from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext

from rest_framework.exceptions import ValidationError


def snapshot(currency, amount, rate=None):
    """Return immutable FX snapshot fields; amount always remains original currency."""
    if not currency:
        if rate not in (None, ''):
            raise ValidationError({'exchange_rate': '来源币种未明确时不能记录汇率。'})
        return None, None
    try:
        amount = Decimal(amount)
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({'amount': '金额无效。'})
    if not amount.is_finite() or amount <= 0 or amount >= Decimal('1e20'):
        raise ValidationError({'amount': '金额须为有限正数。'})
    if currency == 'CNY':
        if rate not in (None, '', Decimal('1'), '1', '1.00000000'):
            raise ValidationError({'exchange_rate': '人民币汇率必须为1。'})
        return Decimal('1'), amount.quantize(Decimal('.0001'), rounding=ROUND_HALF_UP)
    if rate in (None, ''):
        return None, None
    try:
        rate = Decimal(rate)
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError({'exchange_rate': '汇率须为有限正数。'})
    if not rate.is_finite() or rate <= 0 or rate.as_tuple().exponent < -8:
        raise ValidationError({'exchange_rate': '汇率须为有限正数且最多8位小数。'})
    if rate >= Decimal('1e12'):
        raise ValidationError({'exchange_rate': '汇率超出字段范围。'})
    with localcontext() as ctx:
        ctx.prec = 50
        cny = (amount * rate).quantize(Decimal('.0001'), rounding=ROUND_HALF_UP)
    if cny >= Decimal('1e20'):
        raise ValidationError({'exchange_rate': '人民币折算金额超出字段范围。'})
    return rate, cny

def effective_snapshot(currency, amount, exchange_rate, cny_amount):
    """Return stored FX fields, deriving only the historical implicit CNY case.

    This is a pure, read-only compatibility view. It never consults current
    rates or repairs a partial stored pair; write-time validation remains the
    responsibility of the caller.
    """
    if exchange_rate is not None or cny_amount is not None:
        return exchange_rate, cny_amount
    if currency != 'CNY':
        return None, None
    try:
        original = Decimal(amount)
    except (InvalidOperation, TypeError, ValueError):
        return None, None
    if not original.is_finite():
        return None, None
    with localcontext() as ctx:
        digits = len(original.as_tuple().digits)
        integer_digits = max(1, original.adjusted() + 1) if original else 1
        ctx.prec = max(28, digits, integer_digits + 5)
        rounded = original.quantize(Decimal('.0001'), rounding=ROUND_HALF_UP)
    return Decimal('1'), rounded
