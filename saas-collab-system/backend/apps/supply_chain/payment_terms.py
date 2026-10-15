"""Supplier terms are frozen at confirmation, not inferred from archive creation."""
from datetime import timedelta
from zoneinfo import ZoneInfo
from django.conf import settings
from django.utils import timezone

START_LABELS = {'unspecified': '未约定', 'shipment_date': '供应商发货日', 'collection_arrival': '集货到仓日',
                'warehouse_arrival': '目的仓到仓日', 'reconciliation_date': '对账确认日'}


def supplier_terms(supplier):
    return {'days': supplier.payment_term_days, 'start': supplier.payment_term_start,
            'start_label': START_LABELS.get(supplier.payment_term_start, '未约定')}


def order_terms(order):
    if order.status == 'draft':
        return {**supplier_terms(order.supplier), 'state': 'draft_reference'}
    return {**order.supplier_terms_snapshot, 'state': 'frozen' if order.supplier_terms_snapshot else 'unrecorded'}


def _local_date(value):
    if not value:
        return None
    return timezone.localdate(value, timezone=ZoneInfo(getattr(settings, 'SUPPLY_CHAIN_TIME_ZONE', 'Asia/Shanghai')))


def shipment_payment_reference(shipment):
    terms = order_terms(shipment.order)
    result = {**terms, 'anchor_date': None, 'due_date': None, 'message': '历史采购单未记录账期约定。'}
    if terms['state'] == 'unrecorded':
        return result
    if terms.get('days') is None or terms.get('start') == 'unspecified':
        result['message'] = '账期或起算方式尚未约定。'
        return result
    anchor = None
    start = terms['start']
    if start == 'shipment_date':
        anchor = shipment.shipment_date if shipment.status == 'submitted' else None
    elif start == 'collection_arrival':
        anchor = _local_date(shipment.collection_arrived_at)
    elif start == 'warehouse_arrival':
        member = shipment.dispatch_memberships.filter(active_guard=True).select_related('batch').first()
        anchor = _local_date(member.batch.arrived_warehouse_at) if member else None
    if anchor:
        result.update(anchor_date=anchor.isoformat(), due_date=(anchor + timedelta(days=terms['days'])).isoformat(), message='按采购确认时的账期约定计算。')
    else:
        result['message'] = '待确认对账日期，暂不推算到期日。' if start == 'reconciliation_date' else '起算业务节点尚未发生，暂不推算到期日。'
    return result
