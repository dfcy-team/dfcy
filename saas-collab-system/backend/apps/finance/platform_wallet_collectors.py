"""Official read-only transactions, not payment instructions or bank receipts.

Lazada: QueryAccountTransactions (existing verified native contract).
TikTok: Get Seller Financial Transactions 202309, seller.finance.info.
Neither documented response provides a current withdrawable balance.
"""
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from rest_framework.exceptions import ValidationError

LAZADA_PATH = '/finance/transaction/accountTransactions/query'
TIKTOK_PATH = '/finance/202309/withdrawals'
CAPABILITIES = {
    'lazada': {'withdrawals': True, 'note': '账户提款流水，按店铺已登记的交易时区业务口径采集；接口未返回当前余额或银行实际到账金额。'},
    'tiktok': {'withdrawals': True, 'note': '提款及提款退回交易；接口未返回当前可提款余额。'},
    'shopee': {'withdrawals': False, 'note': '本土钱包提款与跨境结算须分别验收，暂不将跨境打款当作提款。'},
}
BALANCE_NOTE = '当前已核验的接口未提供店铺实时可提款余额；不以流水净额或结算金额推算。'


def money(value):
    if type(value) not in (str, int, Decimal) or not re.fullmatch(r'[+-]?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?', str(value)):
        raise ValidationError('平台金额格式无效。')
    try:
        number = Decimal(str(value).replace(',', ''))
        if not number.is_finite() or number != number.quantize(Decimal('0.00000001')) or abs(number) >= Decimal('1e20'):
            raise InvalidOperation
        return number
    except InvalidOperation:
        raise ValidationError('平台金额超出支持精度。') from None


def currency(value):
    if not isinstance(value, str) or not re.fullmatch('[A-Z]{3}', value):
        raise ValidationError('平台没有返回明确币种。')
    return value


def identifier(value):
    if (type(value) not in (str, int) or not 1 <= len(str(value)) <= 191
            or not str(value).strip() or str(value) != str(value).strip() or any(ord(c) < 32 for c in str(value))):
        raise ValidationError('平台没有返回有效交易编号。')
    return str(value)


def epoch(value):
    if type(value) is not int or value < 0:
        raise ValidationError('平台交易时间无效。')
    try:
        return datetime.fromtimestamp(value, UTC)
    except (ValueError, OSError, OverflowError):
        raise ValidationError('平台交易时间超出范围。') from None


def collect_lazada(client, start, end):
    from apps.integrations.lazada_api_service import validate_account_page
    rows, seen, differences = [], set(), 0
    # Upstream supports day-grain selectors. Filter exact activation time
    # locally, so the first query never imports earlier transactions that day.
    source_zone = getattr(client, 'wallet_transaction_timezone', None)
    if source_zone is None:
        raise ValidationError('Lazada账户交易无时区，须先核验时间口径。')
    day = start.astimezone(source_zone).date()
    while day <= end.astimezone(source_zone).date():
        page, total, received = 1, None, 0
        while True:
            query = {'start_time': day.strftime('%Y%m%d'), 'end_time': day.strftime('%Y%m%d'),
                     'page_num': page, 'page_size': 100, 'transaction_type': 'Withdrawal'}
            response = client._request('/rest' + LAZADA_PATH, query)
            validate_account_page(response, query)
            data = response['data']
            count = data['page_info']['total_count']
            if total is None:
                total = count
            if total != count or page > 1000:
                raise ValidationError('平台分页总数变化或超过单次安全范围，请重试。')
            for source in data['transactions']:
                key = identifier(source.get('transaction_number'))
                if key in seen or source.get('type') != 'Withdrawal':
                    raise ValidationError('平台提款分页出现重复编号或非提款交易。')
                seen.add(key)
                received += 1
                try:
                    occurred = datetime.strptime(source['transaction_time'], '%d %b %Y %H:%M:%S')
                except (ValueError, TypeError, KeyError):
                    raise ValidationError('Lazada账户交易时间格式未确认。') from None
                # Native account transaction strings do not carry an offset.
                # Their timezone is not inferred from the seller site.
                occurred = occurred.replace(tzinfo=source_zone).astimezone(UTC)
                if occurred.astimezone(source_zone).date() != day:
                    raise ValidationError('平台交易不在查询日期内。')
                if start <= occurred < end:
                    rows.append({'external_id': key, 'source_endpoint': LAZADA_PATH,
                                 'transaction_type': source['sub_type'], 'raw_status': None,
                                 'currency': currency(source['currency']), 'original_amount': source['amount'],
                                 'signed_amount': money(source['amount']), 'occurred_at_utc': occurred,
                                 'api_fields': {'type': source['type'], 'sub_type': source['sub_type'],
                                    'transaction_time': source['transaction_time'],
                                    'time_interpretation': {'timezone': str(source_zone),
                                        'source': getattr(client, 'wallet_transaction_time_source', 'unspecified')}}})
            if page * 100 >= total:
                differences += max(0, total - received)
                break
            page += 1
        day += timedelta(days=1)
    return rows, {'reported_count_difference': differences}


def collect_tiktok(client, start, end):
    rows, seen_ids, seen_tokens, token, total = [], set(), set(), '', None
    while True:
        query = {'shop_cipher': client.authorization.shop_cipher, 'types': 'WITHDRAW,REVERSE',
                 'create_time_ge': int(start.timestamp()), 'create_time_lt': int(end.timestamp()), 'page_size': 100}
        if token:
            query['page_token'] = token
        response = client._request(TIKTOK_PATH, query=query)
        data = response.get('data')
        if response.get('code') != 0 or not isinstance(data, dict) or not isinstance(data.get('withdrawals'), list):
            raise ValidationError('TikTok提款响应不完整。')
        count = data.get('total_count')
        if type(count) is not int or count < 0 or total is not None and count != total:
            raise ValidationError('TikTok提款总数无效或变化。')
        total = count
        if len(data['withdrawals']) > 100:
            raise ValidationError('TikTok提款分页超出范围。')
        for source in data['withdrawals']:
            key = identifier(source.get('id'))
            if key in seen_ids or source.get('type') not in {'WITHDRAW', 'REVERSE'}:
                raise ValidationError('TikTok提款重复或交易类型不符。')
            seen_ids.add(key)
            occurred = epoch(source.get('create_time'))
            # Filters are integer seconds; activation can have subseconds.
            if not int(start.timestamp()) <= int(occurred.timestamp()) < int(end.timestamp()):
                raise ValidationError('TikTok提款超出请求时间范围。')
            status = source.get('status')
            if not isinstance(status, str) or not 1 <= len(status) <= 80:
                raise ValidationError('TikTok提款状态缺失。')
            if occurred >= start:
                rows.append({'external_id': key, 'source_endpoint': TIKTOK_PATH,
                             'transaction_type': source['type'], 'raw_status': status,
                             'currency': currency(source.get('currency')), 'original_amount': str(source.get('amount')),
                             'signed_amount': money(source.get('amount')), 'occurred_at_utc': occurred, 'api_fields': {}})
        next_token = data.get('next_page_token', '')
        if not isinstance(next_token, str) or next_token in seen_tokens and next_token:
            raise ValidationError('TikTok提款游标重复或无效。')
        if not next_token:
            if len(seen_ids) != total:
                raise ValidationError('TikTok提款记录未完整返回。')
            return rows, {}
        if len(seen_tokens) >= 999:
            raise ValidationError('TikTok提款分页超出单次安全范围。')
        seen_tokens.add(next_token)
        token = next_token
