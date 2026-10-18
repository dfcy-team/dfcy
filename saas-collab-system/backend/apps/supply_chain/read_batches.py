"""Request-local read projections, prepared only after authorized pagination.

No shared cache, business writes, or reuse by mutation commands.
"""
from collections import defaultdict

from .models import BoxInfoAttachment, DispatchMembership, InboundOrder, ShipmentLine
from .dispatch_allocations import active, distribution
from .supplier_products import shipment_line_product_details


def prepare_shipments(rows):
    if not rows:
        return
    # The caller already enforced scope. Constrain every auxiliary read to
    # these exact tenant/record identities rather than a broader tenant query.
    for tenant_id in {row.tenant_id for row in rows}:
        scoped = [row for row in rows if row.tenant_id == tenant_id]
        ids = [row.pk for row in scoped]
        lines = list(ShipmentLine.objects.filter(tenant_id=tenant_id, shipment_id__in=ids, is_active=True)
            .select_related('sku__spu__category_node', 'shipment__order').order_by('shipment_id', 'line_number'))
        details = shipment_line_product_details(lines)
        line_groups, member_groups, files, allocations = (defaultdict(list) for _ in range(4))
        for line in lines:
            line_groups[line.shipment_id].append(line)
        for row in DispatchMembership.objects.filter(tenant_id=tenant_id, shipment_id__in=ids,
                active_guard=True).select_related('batch').order_by('pk'):
            member_groups[row.shipment_id].append(row)
        for row in BoxInfoAttachment.objects.filter(tenant_id=tenant_id, shipment_id__in=ids,
                is_active=True).select_related('file'):
            files[row.shipment_id].append(row)
        for row in active().filter(tenant_id=tenant_id, shipment_line__shipment_id__in=ids).select_related(
                'membership__batch', 'shipment_line').order_by('pk'):
            allocations[row.shipment_line.shipment_id].append(row)
        for row in scoped:
            used = defaultdict(int)
            for allocation in allocations[row.pk]:
                used[allocation.shipment_line_id] += allocation.quantity
            row._read_shipment = {'lines': line_groups[row.pk], 'details': details,
                'members': member_groups[row.pk], 'attachments': files[row.pk],
                'used': used, 'distribution': distribution(row, rows=allocations[row.pk])}


def prepare_batches(rows):
    if not rows:
        return
    for tenant_id in {row.tenant_id for row in rows}:
        scoped = [row for row in rows if row.tenant_id == tenant_id]
        ids = [row.pk for row in scoped]
        groups = defaultdict(list)
        members = list(DispatchMembership.objects.filter(tenant_id=tenant_id, batch_id__in=ids,
            active_guard=True).select_related('shipment__order__supplier').order_by('batch_id', 'shipment_id'))
        prepare_shipments([member.shipment for member in members])
        for member in members:
            groups[member.batch_id].append(member)
        quantities = defaultdict(dict)
        for allocation in active().filter(tenant_id=tenant_id, membership__batch_id__in=ids).values(
                'membership__batch_id', 'shipment_line_id', 'quantity'):
            quantities[allocation['membership__batch_id']][allocation['shipment_line_id']] = allocation['quantity']
        inbound = {row.batch_id: row for row in InboundOrder.objects.filter(tenant_id=tenant_id, batch_id__in=ids)}
        for row in scoped:
            row._read_batch = {'members': groups[row.pk], 'quantities': quantities[row.pk], 'inbound': inbound.get(row.pk)}
