"""Top-N anomaly candidates over the recipient's bounded report queries.

Differences describe ingested facts, never certify provider completeness.
"""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

from rest_framework.exceptions import ValidationError
from apps.reports.datasets import query_dataset

TYPES = {'sales_anomalies': ('sales', 3), 'advertising_anomalies': ('advertising', 6)}
THRESHOLD = Decimal('30')
BASELINE_LABELS = {'previous_day': '前一日', 'last_week_same_day': '上周同天', 'last_week_average': '上周日均'}
QUALITY_NOTE = '按当前权限下已入库数据比较，采集完整性未确认；以下为待核验变化，不代表已确认经营异常。缺失日期、无效数值和零基准不参与30%排序。'


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def total(rows, key):
    values = [number(r.get(key)) for r in rows]
    return sum(values, Decimal(0)) if values and all(v is not None for v in values) else None


def metric_value(rows, metric, average=False):
    if metric == 'roas':
        expense, gmv = total(rows, 'expense'), total(rows, 'broad_gmv')
        return gmv / expense if gmv is not None and expense is not None and expense > 0 else None
    value = total(rows, metric)
    return value / 7 if average and value is not None else value


def baselines(D):
    monday = D - timedelta(days=D.weekday())
    return [('previous_day', [D - timedelta(days=1)]), ('last_week_same_day', [D - timedelta(days=7)]),
            ('last_week_average', [monday - timedelta(days=7) + timedelta(days=i) for i in range(7)])]


def compare(rows, D, metric):
    current = metric_value([r for r in rows if str(r.get('date')) == D.isoformat()], metric)
    results = []
    for name, days in baselines(D):
        dates = [d.isoformat() for d in days]
        selected = [r for r in rows if str(r.get('date')) in dates]
        present = {str(r.get('date')) for r in selected}
        missing = [d for d in dates if d not in present]
        value = metric_value(selected, metric, average=name == 'last_week_average') if not missing else None
        change = (current - value) * 100 / value if current is not None and value is not None and value > 0 else None
        status = 'missing_dates' if missing else 'zero_baseline' if value == 0 else 'observed_only' if change is not None else 'unavailable'
        results.append({'baseline': name, 'dates': dates, 'missing_dates': missing, 'value': value, 'change_percent': change, 'status': status,
                        'observed_threshold_met': bool(change is not None and abs(change) >= THRESHOLD), 'anomaly_confirmed': False})
    return current, results


def assemble_anomalies(kind, source, D):
    """Pure assembly; ranks store percentages, never mixes currency amounts."""
    dataset, limit = TYPES[kind]
    D = date.fromisoformat(D) if isinstance(D, str) else D
    base = {'type': kind, 'dataset': dataset, 'date': D.isoformat(), 'limit': limit, 'threshold_percent': 30,
            'quality_note': QUALITY_NOTE, 'source_refreshed_at': str(source.get('refreshed_at') or '未知'), 'items': [], 'data_completeness': 'unverified'}
    if source.get('truncated'):
        return {**base, 'status': 'truncated', 'message': '历史分组超过查询上限，未按部分结果生成Top排名。请缩小范围后重查。'}
    groups = defaultdict(list)
    for row in source.get('rows', []):
        groups[(str(row.get('store_id')), str(row.get('country') or '').upper(), str(row.get('currency') or '未知币种'))].append(row)
    candidates = []
    missing_current, unusable_baselines = 0, 0
    for (sid, country, currency), rows in groups.items():
        if not any(str(r.get('date')) == D.isoformat() for r in rows):
            missing_current += 1
            continue
        metrics = ('gross_sales',) if kind == 'sales_anomalies' else ('expense', 'roas')
        observations, comparisons = {}, {}
        scores = []
        for metric in metrics:
            observations[metric], comparisons[metric] = compare(rows, D, metric)
            valid = [c for c in comparisons[metric] if c['observed_threshold_met']]
            scores.extend((abs(c['change_percent']), metric, c['baseline']) for c in valid)
            unusable_baselines += sum(c['change_percent'] is None for c in comparisons[metric])
        if not scores:
            continue
        score, trigger_metric, trigger_baseline = max(scores)
        labels = source.get('dimension_labels', {})
        candidates.append({'store_id': sid, 'store_name': labels.get('store_id', {}).get(sid, sid), 'country_code': country,
                           'country': labels.get('country', {}).get(country, country or '国家未设置'), 'currency': currency,
                           'observations': observations, 'comparisons': comparisons, 'score': score,
                           'trigger_metric': trigger_metric, 'trigger_baseline': trigger_baseline})
    candidates.sort(key=lambda x: (-x['score'], x['store_id'], x['currency'], x['country_code']))
    # A store with more than one currency/region is still one ranked store.
    unique = []
    seen = set()
    for item in candidates:
        if item['store_id'] not in seen:
            seen.add(item['store_id']); unique.append(item)
    return {**base, 'status': 'available', 'items': unique[:limit], 'eligible_stores': len(unique), 'omitted_stores': max(0, len(unique)-limit),
            'stores_without_observation': missing_current, 'unusable_baselines': unusable_baselines}


def build_anomaly_report(kind, user, filters):
    if filters.get('date_from') != filters.get('date_to'):
        raise ValidationError('异常日报仅支持单日观察窗口。')
    D = date.fromisoformat(filters['date_to'])
    dataset, limit = TYPES[kind]
    metrics = ['gross_sales'] if dataset == 'sales' else ['expense', 'broad_gmv', 'record_count']
    source = query_dataset(SimpleNamespace(user=user), {'dataset': dataset, 'dimensions': ['date', 'country', 'currency', 'store_id'],
                           'metrics': metrics, 'filters': {'date_from': (D-timedelta(days=13)).isoformat(), 'date_to': D.isoformat()}}, use_cache=False)
    data = assemble_anomalies(kind, source, D)
    title = '店铺GMV变化 Top3' if kind == 'sales_anomalies' else '广告变化 Top6'
    summary = f"{D.isoformat()}：已入库数据变化达到30%的店铺 {len(data['items'])} 家（最多{limit}家）。" + QUALITY_NOTE
    if data['status'] == 'truncated':
        summary = data['message']
    return {'title': title, 'summary': summary, 'sections': [], 'anomalies': data,
            'suppress_delivery': data['status'] != 'available' or not data['items']}
