"""Keep accepted historical inputs when refreshing the two current calendar months."""
import json
import re
from copy import deepcopy
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone


def recent_scope(stores):
    today = timezone.localdate(timezone=ZoneInfo('Asia/Shanghai'))
    start = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    return {'from': start.isoformat(), 'to': today.isoformat(), 'stores': stores}


def assignment(html, name):
    match = re.search(re.escape(name) + r'\s*=\s*', html)
    if not match:
        raise ValueError('Missing accepted source: ' + name)
    return json.JSONDecoder().raw_decode(html[match.end():])[0]


def preserve_history(template, fresh, start):
    """Only dated recent inputs are replaced; undated evidence remains historical."""
    snapshot = json.loads(re.search(r'id="snapshot">([\s\S]*?)</script>', template)[1])
    old = snapshot['database']
    result = deepcopy(fresh)

    def historical(row):
        day = str(row.get('date') or row.get('month') or '')
        return not day or day[:7] < start[:7]

    def rows(before, after):
        retained = [r for r in before if historical(r)]
        identities = {r.get('source_id', r.get('id')) for r in retained} - {None}
        return retained + [r for r in after if not historical(r)
                           and r.get('source_id', r.get('id')) not in identities]

    for key in ('facts', 'raw_flows', 'cost_flows'):
        result[key] = rows(old.get(key, []), fresh.get(key, []))
    result['raw'] = rows(snapshot['raw'], fresh['raw'])
    result['shopee_income'] = rows(snapshot['shopee_income'], fresh['shopee_income'])
    result['sku_members'] = rows(snapshot['lazada_saas']['sku_members'], fresh['sku_members'])
    result['shares'] = {key: rows(old['shares'].get(key, []), fresh['shares'].get(key, []))
                        for key in old['shares'].keys() | fresh['shares'].keys()}
    for kind in ('historical', 'monthly'):
        result['rates'][kind] = {**{k:v for k,v in old['rates'][kind].items() if k[:7] < start[:7]},
                                **{k:v for k,v in fresh['rates'][kind].items() if k[:7] >= start[:7]}}
    # An order can settle in more than one month. Keep its accepted historical
    # item identity/date; monetary facts themselves remain month-specific.
    protected = {str(r['store_id'])+'|'+r['external_order_id'] for r in old['facts']
                 if historical(r) and r.get('store_id') and r.get('external_order_id')}
    result['order_dates'] = {**fresh['order_dates'], **{k:v for k,v in old['order_dates'].items() if k in protected}}
    sku = assignment(template, 'HTML2_SKU_ORDER_SALES')
    for key in ('orders', 'exchanges'):
        result['sku_sales'][key] = {**fresh['sku_sales'].get(key, {}),
                                    **{k:v for k,v in sku.get(key, {}).items() if k in protected}}
    recharge = assignment(template, 'HTML2_RECHARGE_DATA')
    months = {str(r.get('date') or r.get('month') or '')[:7] for r in old['facts']}
    result['recharge']['history'] = {month: recharge.get('history', {}).get(month,
        {'transactions': recharge['transactions'], 'actualSpend': recharge.get('actualSpend')})
        for month in months if month and month < start[:7]}
    result['recharge']['transactions'] = rows(recharge['transactions'], fresh['recharge']['transactions'])
    previous, current = recharge.get('actualSpend'), fresh['recharge'].get('actualSpend')
    if previous:
        current = current or {**previous, 'monthly': [], 'days': []}
        result['recharge']['actualSpend'] = {**current,
            'monthly': rows(previous['monthly'], current['monthly']), 'days': rows(previous['days'], current['days'])}
    cycles = assignment(template, 'HTML2_LAZADA_CYCLES')
    result['cycles']['history'] = {month: cycles.get('history', {}).get(month, cycles['shops'])
        for month in months
        if month and month < start[:7]}
    for shop, previous in cycles['shops'].items():
        current = result['cycles']['shops'].setdefault(shop, {**previous, 'rows': [], 'months': {}})
        current['rows'] = rows(previous['rows'], current['rows'])
        current['months'] = {**{k:v for k,v in previous['months'].items() if k < start[:7]},
                             **{k:v for k,v in current['months'].items() if k >= start[:7]}}
    products = assignment(template, 'HTML2_PRODUCT_LINK_DATA')
    for key in ('rows', 'products'):
        # Keep catalogue entries for historical orders absent from the recent read.
        seen = {json.dumps(r, sort_keys=True) for r in result['products'][key]}
        result['products'][key] += [r for r in products[key] if json.dumps(r, sort_keys=True) not in seen]
    result['source_counts'] = {**fresh['source_counts'], 'platform_finance': len(result['raw']),
                              'facts': len(result['facts']), 'order_items': sum(map(len,result['sku_sales']['orders'].values()))}
    return result
