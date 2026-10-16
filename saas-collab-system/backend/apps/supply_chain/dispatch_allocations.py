"""Quantity reservations. Mutations require the caller's tenant transaction lock."""
from django.core.exceptions import ValidationError
from django.db.models import Sum

from .models import DispatchAllocation, DispatchMembership, ShipmentLine


def active():
    return DispatchAllocation.objects.filter(membership__active_guard=True, membership__batch__status='active')


def batch_quantities(batch):
    return dict(active().filter(membership__batch=batch).values_list('shipment_line_id', 'quantity'))


def totals(line_ids, exclude_batch=None):
    query = active().filter(shipment_line_id__in=line_ids)
    if exclude_batch:
        query = query.exclude(membership__batch=exclude_batch)
    return dict(query.values('shipment_line_id').annotate(total=Sum('quantity')).values_list('shipment_line_id', 'total'))


def resolve(shipments, allocations=None, batch=None):
    lines = {line.pk: line for line in ShipmentLine.objects.filter(shipment__in=shipments, is_active=True)}
    used = totals(lines, batch)
    if allocations is None:
        allocations = [{'shipment_line_id': pk, 'quantity': line.quantity - used.get(pk, 0)}
                       for pk, line in lines.items() if line.quantity > used.get(pk, 0)]
    result = {}
    for row in allocations:
        pk, qty = row['shipment_line_id'], row['quantity']
        if pk in result or pk not in lines or isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise ValidationError('集货商品必须属于所选发货单，不得重复，数量须为正整数。')
        if qty > lines[pk].quantity - used.get(pk, 0):
            raise ValidationError(f'{lines[pk].sku_code_snapshot}：本次数量超过剩余可集货数量，请刷新。')
        result[pk] = qty
    if {lines[pk].shipment_id for pk in result} != {row.pk for row in shipments}:
        raise ValidationError('每张所选发货单至少选择一个有剩余数量的商品。')
    return result


def reserve(actor, batch, shipments, quantities):
    lines = {line.pk: line for line in ShipmentLine.objects.filter(pk__in=quantities)}
    for shipment in shipments:
        member = DispatchMembership.objects.create(tenant=actor.tenant, created_by=actor, batch=batch, shipment=shipment)
        for pk, qty in quantities.items():
            if lines[pk].shipment_id == shipment.pk:
                DispatchAllocation.objects.create(tenant=actor.tenant, created_by=actor,
                    membership=member, shipment_line=lines[pk], quantity=qty)


def distribution(shipment):
    rows = list(active().filter(shipment_line__shipment=shipment).select_related('membership__batch').order_by('pk'))
    groups = {}
    for row in rows:
        batch = row.membership.batch
        group = groups.setdefault(batch.pk, {'batch_id': batch.pk, 'batch_number': batch.number,
            'stage': batch.stage, 'quantity': 0, 'lines': [],
            'logistics_dates': {f: getattr(batch, f) for f in ('departed_at', 'arrived_port_at', 'arrived_warehouse_at')}})
        group['quantity'] += row.quantity
        group['lines'].append({'shipment_line_id': row.shipment_line_id, 'quantity': row.quantity})
    return list(groups.values())
