"""Immutable file reconciliation for new warehouse uploads; legacy policies stay intact."""
from collections import defaultdict
from decimal import Decimal
import re

from .warehouse_bill_parser import amount, decimal

POLICY = 'file_settlement_v2'
HALF_CENT = Decimal('0.005')


def is_file_policy(source):
    return (source or {}).get('registration_mode') == POLICY


def difference_state(value):
    number = decimal(value)
    if number is None:
        return 'unavailable'
    if number < 0:
        return 'manual_review'
    return 'confirmation_required' if number >= HALF_CENT else 'no_fee'


def processing_difference(summary, detail, other=None):
    """Reconcile the complete detail, never the selected or registered subset."""
    total = decimal(summary.get('file_total'))
    other = decimal(summary.get('file_other_total')) if other is None else other
    value = total - detail - other if all(v is not None for v in (total, detail, other)) else None
    summary['processing_difference'] = amount(value)
    summary['net_difference'] = amount(value)
    summary['effective_order_total'] = amount(detail)
    summary['effective_other_total'] = amount(other)
    summary['difference_state'] = difference_state(value)
    validation = summary.setdefault('validation', {})
    items = [i for i in validation.get('items', []) if i['code'] not in {
        'order_total_mismatch', 'negative_processing_difference', 'negative_difference', 'uncovered_difference'}]
    if value is not None and value < 0:
        items.append(dict(code='negative_processing_difference', level='batch', sheet='', row=None, field='',
                          message='订单明细与其他费用合计超过结算总额，负处理费差额须人工核对。'))
    validation.update(items=items, count=len(items), blocking=any(i['level'] == 'batch' for i in items),
                      requires_ack=summary['difference_state'] == 'confirmation_required')


def refresh_processing_difference(summary):
    if summary.get('registration_mode') != POLICY:
        return
    detail = decimal(summary.get('order_detail_sum'))
    correction = decimal(summary.get('corrected_order_difference'))
    control = decimal(summary.get('file_order_total'))
    if correction is not None and control is not None:
        detail = control + correction
    other = decimal(summary.get('corrected_other_total', summary.get('file_other_total')))
    processing_difference(summary, detail, other)


def settlement_facts(facts, summary):
    """Replace supporting other-fee rows with authoritative invoice projects."""
    from .warehouse_bill_parser import BillError
    plan = summary.get('settlement') or {}
    if not plan.get('lines'):
        raise BillError('未识别结算表项目，请配置原文件格式，不能退回支持明细取数。')
    warehouses = {f['raw_warehouse'] for f in facts if f.get('raw_warehouse')}
    warehouse = next(iter(warehouses)) if len(warehouses) == 1 else ''
    result = [f for f in facts if f['kind'] == 'order']
    for line in plan['lines']:
        if line.get('kind') != 'other' or decimal(line.get('amount')) == 0:
            continue
        result.append(dict(kind='other', country=summary['country'], bill_month=summary['bill_month'],
            bill_number=summary['bill_number'], fee_item=line['item'], reference=f"{line['sheet']}!{line['row']}",
            external_order_id='', amount=line['amount'], currency='CNY', occurred_on=None,
            raw_store='', raw_warehouse=warehouse, raw_platform='', raw_stores=[], raw_warehouses=[warehouse],
            sheet=line['sheet'], row=line['row'], source_rows=[line['row']], raw_amount=line['amount'],
            tracking_numbers=[], issues=[]))
    return result


def audit_file(facts, summary):
    findings, duplicates = [], defaultdict(list)

    def issue(code, level, message, fact=None, field=''):
        entry = dict(code=code, level=level, message=message, sheet=(fact or {}).get('sheet', ''),
                     row=(fact or {}).get('row'), field=field)
        findings.append(entry)
        if fact is not None:
            fact.setdefault('validation', []).append(entry)
            if message not in fact['issues']:
                fact['issues'].append(message)

    for fact in facts:
        # Old invoice-progress diagnostics are replaced with structured file checks.
        fact['issues'] = [m for m in fact.get('issues', []) if not m.startswith((
            '订单明细与账单汇总差额', '其他费用明细与账单汇总差额', '原账单订单计费重复', '订单费用汇总不可核对'))]
        value = decimal(fact.get('amount'))
        if value is None or value <= 0:
            issue('invalid_amount', 'row', '金额缺失、超限或非正数，请核对原金额及公式缓存', fact, 'amount')
        if fact['kind'] == 'order':
            number = fact.get('external_order_id', '').strip()
            if not number or re.fullmatch(r'\d+(?:\.\d+)?[Ee][+-]\d+', number) or any('科学计数法' in m for m in fact['issues']):
                issue('invalid_number', 'row', '单号缺失或为科学计数法，不能可靠关联订单', fact, 'external_order_id')
            else:
                duplicates[(fact.get('raw_warehouse', ''), number)].append(fact)
    for group in duplicates.values():
        if len(group) > 1:
            for fact in group:
                issue('duplicate_number', 'row', '同仓库单号有多行费用，需核对分项或重复；未自动合并', fact, 'external_order_id')
                fact['possible_duplicate'] = True
                fact['reference'] += f':ROW:{fact["row"]}'
    plan = summary.get('settlement') or {}
    total, control = decimal(plan.get('total')), decimal(plan.get('order_total'))
    orders = [decimal(f['amount']) for f in facts if f['kind'] == 'order']
    others = [decimal(f['amount']) for f in facts if f['kind'] == 'other']
    other = sum(others, Decimal(0)) if all(v is not None for v in others) else None
    if not orders:
        issue('missing_orders', 'batch', '缺少仓库处理费明细，请检查工作表用途。')
    if any(v is None for v in orders + others):
        issue('incomplete_amounts', 'batch', '原金额无法完整读取，允许保留草稿，禁止确认登记。')
    if total is None or total < 0:
        issue('invalid_controls', 'batch', '结算总额缺失或无效。')
    line_difference = decimal(plan.get('line_difference'))
    if line_difference is not None and abs(line_difference) > HALF_CENT:
        issue('settlement_mismatch', 'warning', '原表项目小计与结算总额不一致，请核对；处理费差额按实际明细计算。')
    summary.update(registration_mode=POLICY, other_fee_source='settlement_sheet',
        file_total=amount(total), file_order_total=amount(control), file_other_total=amount(other),
        validation={'blocking': any(i['level'] == 'batch' for i in findings), 'count': len(findings),
                    'items': sorted(findings, key=lambda i: {'batch': 0, 'warning': 1, 'row': 2}[i['level']])})
    plan['policy'] = POLICY
    summary['settlement'] = plan
    processing_difference(summary, sum(orders, Decimal(0)) if orders and all(v is not None for v in orders) else None)
    return facts, summary
