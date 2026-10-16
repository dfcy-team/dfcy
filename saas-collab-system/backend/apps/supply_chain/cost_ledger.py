"""Read-only product cost projections; never publish a batch as a global price."""
from django.db.models import Exists, F, OuterRef, Q

from . import costs, logistics
from .models import CostEntry, CostVersion, DispatchAllocation, PurchaseOrder
from .permissions import internal_orders


def entries_for(actor, *, history=False):
    orders = internal_orders(actor, PurchaseOrder.objects.all())
    batches = logistics.batches_for(actor)
    newer = CostVersion.objects.filter(tenant_id=OuterRef('tenant_id'),
        sequence__gt=OuterRef('cost_version__sequence')).filter(
        Q(batch__isnull=False, batch_id=OuterRef('cost_version__batch_id')) |
        Q(shipment__isnull=False, shipment_id=OuterRef('cost_version__shipment_id')))
    active = DispatchAllocation.objects.filter(shipment_line_id=OuterRef('shipment_line_id'), membership__active_guard=True, membership__batch__status='active')
    same_batch = active.filter(membership__batch_id=OuterRef('cost_version__batch_id'))
    rows = CostEntry.objects.filter(tenant=actor.tenant, cost_version__tenant=actor.tenant,
        shipment_line__shipment__order__in=orders).filter(
        Q(cost_version__batch__in=batches) |
        Q(cost_version__shipment_id=F('shipment_line__shipment_id'))).annotate(
        has_newer=Exists(newer), has_active_batch=Exists(active), in_owner_batch=Exists(same_batch))
    if not history:
        # A pre-collection shipment calculation and a later batch calculation
        # must not both appear as the current cost of the same source line.
        rows = rows.filter(has_newer=False).filter(
            Q(cost_version__batch__status='active', in_owner_batch=True) |
            Q(cost_version__shipment__status='submitted', has_active_batch=False))
    return rows.select_related('cost_version__batch', 'cost_version__shipment',
        'shipment_line__sku', 'shipment_line__shipment__order__country',
        'receipt_line__receipt__warehouse')


def filter_entries(rows, params):
    for param, field in (('sku_id', 'shipment_line__sku_id'),
                         ('country_id', 'shipment_line__shipment__order__country_id'),
                         ('warehouse_id', 'receipt_line__receipt__warehouse_id'),
                         ('batch_id', 'cost_version__batch_id')):
        if param in params:
            rows = rows.filter(**{field: params[param]})
    if params.get('search'):
        value = params['search']
        rows = rows.filter(Q(shipment_line__sku_code_snapshot__icontains=value) |
                           Q(shipment_line__product_name_snapshot__icontains=value))
    return rows


def serialize(entry, fingerprints, details=None):
    version, line = entry.cost_version, entry.shipment_line
    batch = version.batch
    current_owner = bool((batch and batch.status == 'active' and entry.in_owner_batch) or
                         (version.shipment_id and version.shipment.status == 'submitted' and not entry.has_active_batch))
    latest = not entry.has_newer and current_owner
    status = version.state
    if latest:
        owner = ('batch', batch) if batch else ('shipment', version.shipment)
        key = (owner[0], owner[1].pk)
        if key not in fingerprints:
            fingerprints[key] = costs.inputs(*owner)[1]
        if fingerprints[key] != version.input_fingerprint:
            status = 'recalculation_required'
    warehouse = entry.receipt_line.receipt.warehouse if entry.receipt_line_id else None
    order = line.shipment.order
    return {**costs.entry_data(entry, details), 'id': entry.pk, 'sku_id': line.sku_id,
        'legacy_sku_code': line.sku.legacy_sku_code or '',
        'product_name': line.product_name_snapshot, 'country_id': order.country_id,
        'country_code': order.country_code_snapshot, 'country_name': order.country.name,
        'warehouse_id': warehouse.pk if warehouse else None,
        'warehouse_name': warehouse.name if warehouse else None,
        'batch_id': version.batch_id, 'batch_number': batch.number if batch else None,
        'shipment_id': line.shipment_id, 'shipment_number': line.shipment.number,
        'order_id': order.pk, 'order_number': order.number,
        'cost_version_id': version.pk, 'sequence': version.sequence,
        'kind': 'batch' if batch else 'shipment', 'source_id': version.batch_id or version.shipment_id,
        'stage': version.stage, 'status': status, 'calculated_status': version.state,
        'is_latest': latest, 'created_at': version.created_at}


def serialize_many(entries, fingerprints):
    from .supplier_products import shipment_line_product_details
    entries = list(entries)
    details = shipment_line_product_details([entry.shipment_line for entry in entries])
    return [serialize(entry, fingerprints, details.get(entry.shipment_line_id, {})) for entry in entries]
