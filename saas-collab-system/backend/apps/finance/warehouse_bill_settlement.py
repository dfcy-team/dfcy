"""Invoice-controlled totals. Detail allocations never create a second bill."""
from decimal import Decimal
from itertools import islice

from django.db import transaction
from rest_framework.exceptions import ValidationError

from .warehouse_bill_parser import amount, decimal, text

POLICY = 'business_settlement_v1'
SOURCE_TYPE = 'warehouse_settlement_adjustment'


def invoice_plan(reader, summary):
    """Read only the business invoice, not the sum of its supporting sheets."""
    fus = '账单汇总' in reader.sheets
    sheet = '账单汇总' if fus else next((s for s in reader.sheets if '业务结算' in s), 'Sheet1')
    if sheet not in reader.sheets:
        return None
    label_col, value_col = ('A', 'C') if fus else ('H', 'G')
    lines, grand_total, started, invalid = [], None, False, False
    for row, cells, formulas in islice(reader.rows(sheet, with_formulas=True), 40):
        label, raw = text(cells.get(label_col)), cells.get(value_col)
        value = decimal(raw)
        total_label = label if fus else next((text(cells.get(c)) for c in ['A', 'F', 'H']
                                             if text(cells.get(c)) in {'合计', '总计', '总金额', '总费用'}), '')
        if started and total_label in {'合计', '总计', '总金额', '总费用'}:
            grand_total = amount(value)
            invalid |= value is None
            break
        is_order = label in {'出库费用', '代发费', '一件代发订单', '仓库费用'}
        if is_order:
            started = True
        if not started or not label or label in {'备注', '合计', '总计', '总金额', '总费用'}:
            continue
        if value is None and not text(raw) and value_col not in formulas:
            continue
        invalid |= value is None
        lines.append({'kind': 'order' if is_order else 'other', 'item': label,
                      'amount': amount(value), 'sheet': sheet, 'row': row, 'column': value_col})
    if not lines or not any(line['kind'] == 'order' for line in lines):
        return None
    line_total = sum((decimal(line['amount']) or Decimal(0) for line in lines), Decimal(0))
    total = decimal(grand_total) if grand_total is not None else line_total
    orders = sum((decimal(line['amount']) or Decimal(0) for line in lines if line['kind'] == 'order'), Decimal(0))
    # A TH "仓库费用" line includes warehouse consumables. The supporting
    # order subtotal allocates that line, but can never replace the invoice total.
    if any(line['item'] == '仓库费用' for line in lines) and summary.get('order_bill_total') is not None:
        orders = Decimal(summary['order_bill_total'])
    currency = summary.get('currency', '')
    return {'policy': POLICY, 'bill_number': summary['bill_number'], 'country': summary['country'],
            'bill_month': summary['bill_month'], 'currency': currency, 'lines': lines,
            'total': amount(total), 'order_total': amount(orders), 'other_total': amount(total - orders),
            'line_difference': amount(total - line_total),
            'valid': not invalid and bool(currency) and total is not None,
            'error': '结算清单金额或币种未确认，暂不登记。' if invalid or not currency else ''}


def managed(source):
    return (source or {}).get('type') == SOURCE_TYPE


def refresh_for_fee(user, fee):
    from .warehouse_fee_models import WarehouseBillUpload
    job = WarehouseBillUpload.objects.filter(tenant=user.tenant,
        summary__settlement_active=True, summary__settlement__bill_number=fee.bill_number,
        summary__settlement__country=fee.country, summary__settlement__bill_month=fee.bill_month).first()
    if job:
        reconcile(user, job.pk)


@transaction.atomic
def reconcile(user, job_id, *, activate=False):
    from .warehouse_bill_uploads import require_original
    from .warehouse_fee_models import WarehouseBillUpload, WarehouseFee
    from .warehouse_fee_services import FeeInput, content, hash_value, log, require

    require_original(user)
    require(user, 'register')
    from apps.tenants.models import Tenant
    Tenant.objects.select_for_update().get(pk=user.tenant_id)
    job = WarehouseBillUpload.objects.select_for_update().get(pk=job_id, tenant=user.tenant)
    plan = job.summary.get('settlement') or {}
    if plan.get('policy') != POLICY or not plan.get('valid'):
        raise ValidationError('业务结算清单金额或币种未确认，不能登记差额。')
    if not activate and not job.summary.get('settlement_active'):
        return
    if activate:
        require(user, 'edit')
        if WarehouseFee.objects.filter(tenant=user.tenant, source__sha256=job.file_hash).exclude(
                bill_number=plan['bill_number']).exclude(status='void').exists():
            raise ValidationError('同一原账单已按其他名称登记，不能改名后重复登记。')
        if WarehouseBillUpload.objects.filter(tenant=user.tenant, file_hash=job.file_hash,
                summary__settlement_active=True).exclude(summary__settlement__bill_number=plan['bill_number']).exists():
            raise ValidationError('同一原账单已按其他名称登记，不能改名后重复登记。')
        # One active authority per business bill, even if the same file was
        # uploaded by several users or replaced with a newer retained copy.
        peers = WarehouseBillUpload.objects.select_for_update().filter(tenant=user.tenant,
            summary__settlement_active=True, summary__settlement__bill_number=plan['bill_number'],
            summary__settlement__country=plan['country'], summary__settlement__bill_month=plan['bill_month']).exclude(pk=job.pk)
        for peer in peers:
            peer.summary = {**peer.summary, 'settlement_active': False}
            peer.save(update_fields=['summary', 'updated_at'])
    fees = list(WarehouseFee.objects.select_for_update().filter(tenant=user.tenant,
        bill_number=plan['bill_number'], country=plan['country'], bill_month=plan['bill_month']).select_related('warehouse', 'store'))
    base = [fee for fee in fees if fee.status == 'registered' and not managed(fee.source)]
    if any(fee.currency != plan['currency'] for fee in base):
        raise ValidationError('已登记明细与结算清单币种不同，须先按原账单结算证据更正，不能直接相减。')
    allocated = {kind: sum((fee.amount for fee in base if fee.kind == kind), Decimal(0)) for kind in ['order', 'other']}
    detail = decimal(job.summary.get('order_detail_sum'))
    detail = detail if detail is not None else Decimal(plan['order_total'])
    components = {
        'order_pending': ('待核对订单费用差额', detail - allocated['order']),
        'order_difference': ('订单结算调整差额', Decimal(plan['order_total']) - detail),
        'other_difference': ('其他费用结算调整差额', Decimal(plan['other_total']) - allocated['other']),
    }
    # Never infer one warehouse from the small subset of already matched orders.
    warehouse_id = job.summary.get('settlement_warehouse_id')
    results = []
    for component, (item, value) in components.items():
        identity = [plan['country'], plan['bill_month'], plan['bill_number'], component]
        reference = 'SETTLEMENT:' + hash_value(identity)[:40]
        key = hash_value(['warehouse_settlement', *identity])
        current = next((fee for fee in fees if fee.business_key == key), None)
        if not current and not value:
            continue
        data = dict(kind='other', country=plan['country'], warehouse_id=warehouse_id, store_id=None,
                    external_order_id='', bill_number=plan['bill_number'], bill_month=plan['bill_month'],
                    fee_item=item, reference=reference, amount=amount(value), currency=plan['currency'],
                    note='按业务结算清单登记；差额随订单费用登记同步重算。' + (' 仓库待分配。' if not warehouse_id else ''))
        serializer = FeeInput(data=data, context={'settlement_adjustment': True})
        serializer.is_valid(raise_exception=True)
        values = dict(serializer.validated_data)
        source = {'type': SOURCE_TYPE, 'policy': POLICY, 'component': component,
                  'sha256': job.file_hash, 'file_name': job.file_name, 'job_id': str(job.pk),
                  'invoice': plan, 'allocated_orders': amount(allocated['order']),
                  'allocated_other': amount(allocated['other']), 'order_detail_sum': amount(detail),
                  'warehouse_pending': warehouse_id is None}
        status = 'registered' if value else 'void'
        if current:
            before = {**content(current), 'status': current.status, 'source': current.source}
            if current.content_hash == hash_value(values) and current.status == status and current.source == source:
                results.append(current)
                continue
            for field, val in values.items():
                setattr(current, field, val)
            current.source, current.status = source, status
            current.content_hash = hash_value(values)
            current.version += 1
            current.save()
            log(current, user, 'settlement_reconcile', before, '业务结算清单口径调整，保留原登记和差额计算依据')
        else:
            current = WarehouseFee.objects.create(tenant=user.tenant, **values, source=source,
                business_key=key, content_hash=hash_value(values), status=status, match_status='not_applicable', created_by=user)
            log(current, user, 'settlement_reconcile', reason='按业务结算清单登记差额')
        results.append(current)
    registered = WarehouseFee.objects.filter(tenant=user.tenant, country=plan['country'],
        bill_number=plan['bill_number'], bill_month=plan['bill_month'], status='registered')
    from django.db.models import Sum
    actual = registered.aggregate(total=Sum('amount'))['total'] or Decimal(0)
    if actual != Decimal(plan['total']):
        raise ValidationError('结算登记总额校验失败，本次调整已回滚。')
    job.summary = {**job.summary, 'settlement_active': True, 'settlement_result': {
        'registered_total': amount(actual), 'currency': plan['currency'],
        'allocated_orders': amount(allocated['order']), 'allocated_other': amount(allocated['other']),
        'adjustments': [{'id': fee.pk, 'item': fee.fee_item, 'amount': amount(fee.amount),
                         'status': fee.status, 'warehouse_id': fee.warehouse_id} for fee in results],
    }}
    job.save(update_fields=['summary', 'updated_at'])
    return job.summary['settlement_result']
