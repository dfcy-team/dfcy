"""Source conservation and evidence coverage are separate from profit attribution."""
from collections import defaultdict
from decimal import Decimal
from rest_framework.exceptions import ValidationError


def check_sources(source):
    raw = {f"finance-transaction:{row['id']}": row for row in source['raw']}
    flows = [row for row in source['raw_flows'] if row['source_id'].startswith('finance-transaction:')]
    if (len(raw) != len(source['raw']) or len(flows) != len(raw)
            or {row['source_id'] for row in flows} != set(raw)):
        raise ValidationError('原始财务流水存在重复或遗漏，未生成候选批次。')
    totals = defaultdict(lambda: Decimal('0'))
    for flow in flows:
        row = raw.get(flow['source_id'])
        if not row or flow['currency'] != row['currency'] or Decimal(str(flow['amount'])) != Decimal(str(row['amount'])):
            raise ValidationError('原始流水金额或币种未守恒，未生成候选批次。')
        if flow['kind'] == 'settlement' and flow.get('status') != 'reference':
            raise ValidationError('净结算额不能重复计入收入。')
        totals[row['currency']] += Decimal(str(row['amount']))
    coverage = []
    by_subject = defaultdict(list)
    for row in source['facts']:
        by_subject[(row.get('store_id'), row['kind'])].append(row)
    kinds = ['sales', 'refund', 'order_fee', 'advertising', 'product_cost', 'warehouse_order',
             'warehouse_other', 'gcash', 'promotion', 'adjustment']
    for store in source['scope']['stores']:
        for kind in kinds:
            rows = by_subject[(store, kind)]
            unknown = sum(r['amount'] is None for r in rows)
            status = 'missing' if not rows else 'pending' if unknown else (
                'observed_zero' if all(Decimal(r['amount']) == 0 for r in rows) else 'evidence_present')
            coverage.append({'store_id': store, 'kind': kind, 'status': status, 'rows': len(rows), 'unknown_rows': unknown})
    return {'raw_conservation_passed': True, 'raw_rows': len(raw),
        'original_totals_by_currency': {key: str(value) for key, value in totals.items()},
        'coverage': coverage, 'coverage_complete': all(r['status'] in {'observed_zero', 'evidence_present'} for r in coverage),
        'basis': '仅已存在的零金额记录标为零；缺少记录仍待核，上传账单不等于费用登记。'}
