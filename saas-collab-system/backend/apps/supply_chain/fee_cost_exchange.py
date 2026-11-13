"""Freeze the original CNY quote used to convert a fee for cost allocation."""
from decimal import Decimal, InvalidOperation, localcontext
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.masterdata.exchange_rates import tenant_cny_rates
from apps.masterdata.models import DailyExchangeRateSnapshot
from apps.masterdata.monthly_exchange_rates import evidence_hash


def resolve(tenant, request, previous):
    if request is None:
        return dict(previous)
    currency = request['currency']
    if currency == 'CNY':
        return {'currency': 'CNY', 'quote': '1', 'source': 'identity', 'rate_date': None}
    today = timezone.localdate(timezone=ZoneInfo('Asia/Shanghai'))
    requested_day = request.get('rate_date')
    if not requested_day and previous.get('currency') == currency:
        return dict(previous)
    reference = tenant_cny_rates(tenant).get(currency)
    day = requested_day or (reference['date'] if reference else None) or today
    if day > today:
        raise ValidationError('汇率日期不能晚于今天。')
    if previous.get('currency') == currency and previous.get('rate_date') == day.isoformat():
        return dict(previous)
    snapshot = DailyExchangeRateSnapshot.objects.filter(tenant=tenant, rate_date=day).first()
    value = source = None
    if snapshot and currency in snapshot.rates:
        if evidence_hash(day, snapshot.rates) != snapshot.source_hash:
            raise ValidationError('每日汇率快照校验失败，请核对国家档案。')
        value, source = snapshot.rates[currency], snapshot.source_url
    elif reference and reference['date'] == day:
        value, source = reference['rate'], reference['source']
    try:
        quote = Decimal(str(value))
        if not quote.is_finite() or quote <= 0:
            raise InvalidOperation
    except InvalidOperation as exc:
        raise ValidationError(f'{day} 国家档案没有可用的 {currency} 汇率，请先维护汇率。') from exc
    return {'currency': currency, 'quote': format(quote, 'f'), 'source': source, 'rate_date': day.isoformat()}


def to_cny(amount, exchange):
    if not exchange:
        return amount
    with localcontext() as context:
        context.prec = 60
        return amount / Decimal(exchange['quote'])
