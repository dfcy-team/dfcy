"""Request-local read projections, prepared only after authorized pagination.

No shared cache, business writes, or reuse by mutation commands.
"""
from collections import defaultdict
from django.db.models import Sum

from .models import BoxInfoAttachment, DispatchMembership, InboundOrder, ShipmentLine
from .dispatch_allocations import active, distribution
from .supplier_products import shipment_line_product_details


def prepare_shipments(rows, *, summary=False):
    if not rows:
        return
    # The caller already enforced scope. Constrain every auxiliary read to
    # these exact tenant/record identities rather than a broader tenant query.
    for tenant_id in {row.tenant_id for row in rows}:
        scoped = [row for row in rows if row.tenant_id == tenant_id]
        ids = [row.pk for row in scoped]
        if summary:
            # The list projection deliberately avoids SKU/product-image joins and
            # file metadata. Details continue through the original full path.
            line_groups, member_groups, file_groups, allocation_groups = (
                defaultdict(list) for _ in range(4))
            order_groups = defaultdict(dict)
            shipment_by_id = {row.pk: row for row in scoped}
            line_rows = ShipmentLine.objects.filter(tenant_id=tenant_id, shipment_id__in=ids,
                is_active=True).values("pk", "shipment_id", "quantity", "purchase_line__order_id",
                    "purchase_line__order__number").order_by("shipment_id", "line_number")
            for line in line_rows:
                shipment = shipment_by_id[line["shipment_id"]]
                order_id = line["purchase_line__order_id"] or shipment.order_id
                order_number = line["purchase_line__order__number"] or shipment.order.number
                line_groups[line["shipment_id"]].append({"id": line["pk"],
                    "quantity": line["quantity"], "purchase_order_id": order_id,
                    "purchase_order_number": order_number})
                order_groups[line["shipment_id"]][order_id] = order_number
            for member in DispatchMembership.objects.filter(tenant_id=tenant_id, shipment_id__in=ids,
                    active_guard=True).select_related("batch").order_by("pk"):
                member_groups[member.shipment_id].append(member)
            for attachment in BoxInfoAttachment.objects.filter(tenant_id=tenant_id, shipment_id__in=ids,
                    is_active=True).values("shipment_id", "pk"):
                file_groups[attachment["shipment_id"]].append({"id": attachment["pk"]})
            allocation_rows = active().filter(tenant_id=tenant_id,
                shipment_line__shipment_id__in=ids).values(
                    "shipment_line__shipment_id", "membership__batch_id", "membership__batch__number",
                    "membership__batch__stage", "membership__batch__freight_quote_snapshot",
                    "membership__batch__freight_quote__billing_basis",
                    "membership__batch__freight_quote__container_type").annotate(
                        quantity=Sum("quantity")).order_by(
                            "shipment_line__shipment_id", "membership__batch_id")
            for allocation in allocation_rows:
                snapshot = allocation["membership__batch__freight_quote_snapshot"] or {}
                allocation_groups[allocation["shipment_line__shipment_id"]].append({
                    "batch_id": allocation["membership__batch_id"],
                    "batch_number": allocation["membership__batch__number"],
                    "stage": allocation["membership__batch__stage"],
                    "billing_basis": snapshot.get("billing_basis") or allocation[
                        "membership__batch__freight_quote__billing_basis"] or "",
                    "container_type": snapshot.get("container_type") or allocation[
                        "membership__batch__freight_quote__container_type"] or "",
                    "quantity": allocation["quantity"],
                })
            for row in scoped:
                orders = order_groups[row.pk]
                if not orders:
                    orders[row.order_id] = row.order.number
                row._read_shipment = {
                    "summary": True,
                    "total_quantity": sum(line["quantity"] for line in line_groups[row.pk]),
                    "lines": line_groups[row.pk],
                    "orders": orders,
                    "members": member_groups[row.pk],
                    "attachments": file_groups[row.pk],
                    "distribution": allocation_groups[row.pk],
                }
            continue
        lines = list(ShipmentLine.objects.filter(tenant_id=tenant_id, shipment_id__in=ids, is_active=True)
            .select_related('sku__spu__category_node', 'shipment__order', 'purchase_line__order').order_by('shipment_id', 'line_number'))
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
                'membership__batch__freight_quote', 'shipment_line').order_by('pk'):
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
        from .inbound_split import prepare_progress
        prepare_progress(scoped, quantities)
        for row in scoped:
            row._read_batch = {'members': groups[row.pk], 'quantities': quantities[row.pk]}
