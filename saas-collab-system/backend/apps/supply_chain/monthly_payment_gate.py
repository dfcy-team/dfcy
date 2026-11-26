"""Payment reconciliation used by the daily received-cost estimate job."""
from decimal import Decimal, InvalidOperation

from . import costs


def _amount(value):
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def payment_state(actor, batch):
    """Return goods and recorded fee balances without inventing missing fees."""
    goods_sources = []
    for membership in batch.memberships.filter(active_guard=True).select_related('shipment').order_by('pk'):
        summary = costs.payment_summary(actor, 'shipment', membership.shipment_id)['summary']
        due = _amount(summary.get('due_amount'))
        remaining = _amount(summary.get('remaining_amount'))
        goods_sources.append({'shipment_id': membership.shipment_id,
            'due_amount': summary.get('due_amount'), 'paid_amount': summary.get('paid_amount'),
            'remaining_amount': summary.get('remaining_amount'),
            'state': ('unknown' if due is None else 'paid' if remaining == 0 else 'unpaid')})
    goods = {'shipments': goods_sources,
             'state': ('unknown' if not goods_sources or any(row['state'] == 'unknown' for row in goods_sources)
                       else 'paid' if all(row['state'] == 'paid' for row in goods_sources) else 'unpaid')}

    fees = []
    batch_summary = costs.payment_summary(actor, 'batch', batch.pk)
    batch_items = batch_summary.get('fee_items', [])
    for item in batch_items:
        fees.append({'source_kind': 'batch', **item,
                     'state': ('paid' if _amount(item.get('remaining_amount')) == 0 else
                               'unpaid' if _amount(item.get('remaining_amount')) is not None else 'unknown')})
    # Legacy fee revisions may have a total without an item breakdown.
    coverage_incomplete = False
    if not batch_items:
        summary = batch_summary.get('summary', {})
        due = _amount(summary.get('due_amount'))
        if due is not None and due > 0:
            fees.append({'source_kind': 'batch', 'amount': summary.get('due_amount'),
                         'paid_amount': summary.get('paid_amount'),
                         'remaining_amount': summary.get('remaining_amount'),
                         'state': ('paid' if _amount(summary.get('remaining_amount')) == 0 else
                                   'unpaid' if _amount(summary.get('remaining_amount')) is not None else 'unknown')})
    for inbound in batch.inbound_orders.filter(status='confirmed').order_by('pk'):
        summary = costs.payment_summary(actor, 'inbound', inbound.pk)
        for item in summary.get('fee_items', []):
            fees.append({'source_kind': 'inbound', 'source_id': inbound.pk, **item,
                         'state': ('paid' if _amount(item.get('remaining_amount')) == 0 else
                                   'unpaid' if _amount(item.get('remaining_amount')) is not None else 'unknown')})
    from .domestic_expense_models import DomesticExpenseGroup
    for group in DomesticExpenseGroup.objects.filter(tenant_id=actor.tenant_id,
            shipment_id__in=[row['shipment_id'] for row in goods_sources], is_active=True).order_by('pk'):
        summary = costs.payment_summary(actor, 'domestic_expense', group.pk)['summary']
        fees.append({'source_kind': 'domestic_expense', 'source_id': group.pk,
                     'due_amount': summary.get('due_amount'), 'paid_amount': summary.get('paid_amount'),
                     'remaining_amount': summary.get('remaining_amount'),
                     'state': 'paid' if _amount(summary.get('remaining_amount')) == 0 else 'unpaid'})
    coverage_incomplete = coverage_incomplete or any(row['state'] == 'unknown' for row in fees)
    return {'goods': goods, 'recorded_fees': fees,
            'recorded_fees_state': ('unknown' if coverage_incomplete else
                                    'paid' if all(row['state'] == 'paid' for row in fees) else 'unpaid'),
            'coverage_incomplete': coverage_incomplete,
            'ready': (not coverage_incomplete and goods['state'] == 'paid'
                      and all(row['state'] == 'paid' for row in fees))}
