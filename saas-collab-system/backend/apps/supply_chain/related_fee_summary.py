"""Read-only source fee summaries; these amounts are not inbound allocations."""
from .models import DispatchMembership, FeeRecord
from .domestic_expense_models import DomesticExpenseGroup


def related_fees(actor, kind, obj):
    from .costs import targets, text_number

    if kind not in ('inbound', 'batch', 'shipment'):
        return []

    if kind == 'shipment':
        shipment_ids = [obj.pk]
    elif kind == 'inbound':
        shipment_ids = obj.lines.values_list('shipment_line__shipment_id', flat=True)
    else:
        shipment_ids = DispatchMembership.objects.filter(
            batch_id=obj.pk, active_guard=True
        ).values_list('shipment_id', flat=True)

    shipments = list(targets(actor, 'shipment').filter(pk__in=shipment_ids))
    batches = list(targets(actor, 'batch').filter(pk=obj.batch_id)) if kind == 'inbound' else []
    owners = ([('shipment', row) for row in shipments if kind != 'shipment']
              + [('batch', row) for row in batches])

    shipment_records = FeeRecord.objects.filter(
        tenant_id=actor.tenant_id, shipment_id__in=[row.pk for row in shipments]
    ).select_related('current_revision')
    lookup = {('shipment', row.shipment_id): row for row in shipment_records}
    if batches:
        batch_records = FeeRecord.objects.filter(
            tenant_id=actor.tenant_id, batch_id__in=[row.pk for row in batches]
        ).select_related('current_revision')
        lookup.update({('batch', row.batch_id): row for row in batch_records})

    result = []
    for source_kind, owner in owners:
        record = lookup.get((source_kind, owner.pk))
        revision = record.current_revision if record else None
        if revision:
            result.append({
                'kind': source_kind, 'id': owner.pk, 'number': owner.number,
                'label': '关联发货费用' if source_kind == 'shipment' else '关联批次费用',
                'amount': text_number(revision.amount),
                'currency': (revision.cost_exchange or {}).get('currency'),
                'state': revision.state, 'basis': 'source_total',
            })

    shipment_numbers = {row.pk: row.number for row in shipments}
    groups = DomesticExpenseGroup.objects.filter(
        tenant_id=actor.tenant_id, shipment_id__in=shipment_numbers, is_active=True
    )
    for group in groups:
        result.append({
            'kind': 'shipment', 'id': group.shipment_id,
            'number': shipment_numbers[group.shipment_id],
            'label': '本单国内费用明细' if kind == 'shipment' else '关联国内费用明细',
            'amount': text_number(group.amount), 'currency': group.currency,
            'state': 'recorded', 'basis': 'source_total',
        })
    return result
