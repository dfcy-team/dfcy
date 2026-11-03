"""Auditable daily CNY evidence and arithmetic averages of complete calendar months."""
import calendar
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import hashlib
import json
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from django.utils import timezone

from .models import DailyExchangeRateSnapshot


class ExchangeRateEvidenceError(ValueError):
    pass


def month_days(month):
    first = date.fromisoformat(month + '-01')
    return [first + timedelta(days=i) for i in range(calendar.monthrange(first.year, first.month)[1])]


def normalized_rates(rates):
    result = {}
    if not isinstance(rates, dict) or not rates:
        raise ExchangeRateEvidenceError('每日汇率不是有效币种表。')
    for currency, value in rates.items():
        code = str(currency).upper()
        if len(code) != 3 or not code.isascii() or not code.isalpha():
            continue
        try:
            rate = Decimal(str(value))
            if not rate.is_finite() or rate <= 0:
                raise InvalidOperation()
        except (InvalidOperation, ValueError):
            raise ExchangeRateEvidenceError('每日汇率包含无效值，未保存。') from None
        result[code] = format(rate.normalize(), 'f')
    if 'CNY' in result and Decimal(result['CNY']) != 1:
        raise ExchangeRateEvidenceError('每日汇率基准不是 1 CNY。')
    result['CNY'] = '1'
    if len(result) < 2:
        raise ExchangeRateEvidenceError('每日汇率没有可用外币。')
    return result


def evidence_hash(day, rates):
    body = json.dumps({'date': day.isoformat(), 'cny': rates}, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(body).hexdigest()


def fetch_daily_rates(day, *, opener=urlopen, timeout=12):
    if day > timezone.localdate(timezone=ZoneInfo('Asia/Shanghai')):
        raise ExchangeRateEvidenceError('不能读取未来日期汇率。')
    urls = [f'https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{day}/v1/currencies/cny.json',
            f'https://{day}.currency-api.pages.dev/v1/currencies/cny.json']
    for url in urls:
        try:
            request = Request(url, headers={'Accept': 'application/json', 'User-Agent': 'dfcy-exchange-rate/1.0'})
            with opener(request, timeout=timeout) as response:
                body = json.loads(response.read().decode('utf-8'), parse_float=Decimal)
            if body.get('date') != day.isoformat():
                raise ExchangeRateEvidenceError('返回日期不匹配。')
            rates = normalized_rates(body.get('cny'))
            return {'rates': rates, 'source_url': url}
        except Exception:
            continue
    raise ExchangeRateEvidenceError(f'{day} 每日汇率获取或校验失败；未使用其他日期代替。')


def store_daily_rates(tenant, day, rates, source_url):
    if day > timezone.localdate(timezone=ZoneInfo('Asia/Shanghai')):
        raise ExchangeRateEvidenceError('不能保存未来日期汇率。')
    rates = normalized_rates(rates)
    digest = evidence_hash(day, rates)
    row, created = DailyExchangeRateSnapshot.objects.get_or_create(tenant=tenant, rate_date=day,
        defaults={'rates': rates, 'source_url': source_url, 'source_hash': digest})
    if not created and (row.source_hash != digest or evidence_hash(day, row.rates) != digest):
        raise ExchangeRateEvidenceError(f'{day} 已有每日汇率与新数据冲突；未覆盖原证据。')
    return row


def monthly_average_quotes(tenant, months, pairs, *, as_of=None):
    """Pair=(country, from, to); a missing day/currency never becomes an average."""
    if not months or not pairs:
        return {}
    days = {month: month_days(month) for month in sorted(set(months))}
    rows = {r.rate_date: r for r in DailyExchangeRateSnapshot.objects.filter(
        tenant=tenant, rate_date__range=(min(days.values())[0], max(days.values())[-1]))}
    for day, row in rows.items():
        if evidence_hash(day, row.rates) != row.source_hash:
            raise ExchangeRateEvidenceError(f'{day} 每日汇率证据校验失败。')
    today = as_of or timezone.localdate(timezone=ZoneInfo('Asia/Shanghai'))
    result = {}
    for month, calendar_days in days.items():
        if calendar_days[-1] >= today or any(day not in rows for day in calendar_days):
            continue
        evidence = [rows[day] for day in calendar_days]
        for country, base, target in sorted(set(pairs)):
            if any(base not in r.rates or target not in r.rates for r in evidence):
                continue
            with localcontext() as ctx:
                ctx.prec = 40
                daily = [Decimal(r.rates[target]) / Decimal(r.rates[base]) for r in evidence]
                average = (sum(daily) / len(daily)).quantize(Decimal('.0000000001'), rounding=ROUND_HALF_UP)
            digest = hashlib.sha256('|'.join(r.source_hash for r in evidence).encode()).hexdigest()
            result['|'.join([month, country, base, target])] = {
                'date': month, 'from': base, 'to': target, 'rate': format(average, 'f'),
                'basis': 'monthly_daily_average', 'source': 'SaaS完整自然月每日汇率算术平均',
                'input_id': f'monthavg:{month}:{country}:{base}:{target}:{digest[:12]}',
                'days': len(evidence), 'expected_days': len(calendar_days),
                'daily_ids': [r.pk for r in evidence], 'sources': sorted({r.source_url for r in evidence}),
                'source_hash': digest, 'source_description': f'{month}：{len(evidence)}/{len(calendar_days)}天；逐日交叉汇率后算术平均；按上海时区确认完整月份',
            }
    return result
