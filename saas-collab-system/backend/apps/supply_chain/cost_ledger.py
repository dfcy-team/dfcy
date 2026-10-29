"""Read-only product cost projections; never publish a batch as a global price."""
from decimal import Decimal
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


def serialize(entry, fingerprints, details=None, settlements=None):
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
    goods_revision = (settlements or {}).get(('shipment', line.shipment_id))
    freight_revision = (settlements or {}).get(('batch', version.batch_id)) if version.batch_id else None
    payment_data = (settlements or {}).get('payments', {})
    goods_payment = payment_data.get(('shipment', line.shipment_id), {})
    freight_payment = payment_data.get(('batch', version.batch_id), {}) if version.batch_id else {}
    def settlement_projection(revision, payment):
        zero = Decimal('0')
        old_amount = revision.recorded_amount if revision else zero
        _, old_nature, old_unclassified = costs._settlement_allocation_data(revision) if revision else ([], 'unclassified', zero)
        new_amount = payment.get('paid', zero) + payment.get('applied', zero)
        total = old_amount + new_amount
        natures = set(payment.get('natures', set()))
        if old_amount and old_nature in ('corporate', 'personal', 'mixed'):
            if old_nature == 'mixed':
                natures.update(('corporate', 'personal'))
            else:
                natures.add(old_nature)
        unclassified = old_unclassified + payment.get('unclassified', zero)
        nature = ('unclassified' if not natures else next(iter(natures)) if len(natures) == 1 and not unclassified else 'mixed')
        if not total:
            return ('unclassified', None, None, revision.sequence if revision else None, 'current')
        return (nature, costs.text_number(unclassified), costs.text_number(total),
            (revision.sequence if revision else 0) + payment.get('count', 0), 'payment_transactions' if new_amount else 'current')
    goods_settlement = settlement_projection(goods_revision, goods_payment)
    freight_settlement = settlement_projection(freight_revision, freight_payment)
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
        'is_latest': latest, 'created_at': version.created_at,
        'goods_settlement_nature': goods_settlement[0], 'goods_settlement_unclassified_amount': goods_settlement[1],
        'goods_settlement_recorded_amount': goods_settlement[2], 'goods_settlement_version': goods_settlement[3],
        'goods_settlement_basis': goods_settlement[4],
        'freight_settlement_nature': freight_settlement[0], 'freight_settlement_unclassified_amount': freight_settlement[1],
        'freight_settlement_recorded_amount': freight_settlement[2], 'freight_settlement_version': freight_settlement[3],
        'freight_settlement_basis': freight_settlement[4],
        'goods_payment_amount': goods_payment.get('paid_amount', '0.0000'),
        'goods_payment_classification': goods_payment.get('classification', 'unclassified'),
        'goods_prepayment_applied_amount': goods_payment.get('applied_amount', '0.0000'),
        'freight_payment_amount': freight_payment.get('paid_amount', '0.0000'),
        'freight_payment_classification': freight_payment.get('classification', 'unclassified')}


def serialize_many(entries, fingerprints):
    from .supplier_products import shipment_line_product_details
    from django.db.models import Q
    from .models import SettlementRecord, PaymentRecord, PaymentApplication
    entries = list(entries)
    details = shipment_line_product_details([entry.shipment_line for entry in entries])
    shipment_ids = {entry.shipment_line.shipment_id for entry in entries if entry.shipment_line.shipment_id}
    batch_ids = {entry.cost_version.batch_id for entry in entries if entry.cost_version.batch_id}
    records = SettlementRecord.objects.filter(tenant_id=entries[0].tenant_id if entries else None).filter(
        Q(shipment_id__in=shipment_ids) | Q(batch_id__in=batch_ids)).select_related('current_revision')
    settlements = {}
    for record in records:
        if record.current_revision_id:
            settlements[('shipment', record.shipment_id) if record.shipment_id else ('batch', record.batch_id)] = record.current_revision
    payments = {}
    owner_filter = Q(shipment_id__in=shipment_ids) | Q(batch_id__in=batch_ids)
    payment_rows = PaymentRecord.objects.filter(tenant_id=entries[0].tenant_id if entries else None,
        reverses__isnull=True, reversal__isnull=True).filter(owner_filter).select_related('payee_account')
    for item in payment_rows:
        key = ('shipment', item.shipment_id) if item.shipment_id else ('batch', item.batch_id)
        data = payments.setdefault(key, {'amount': Decimal('0'), 'natures': set(), 'count': 0})
        data['amount'] += item.amount
        data['count'] += 1
        nature = (item.account_snapshot or {}).get('nature')
        if nature:
            data['natures'].add(nature)
    for item in PaymentApplication.objects.filter(tenant_id=entries[0].tenant_id if entries else None,
            shipment_id__in=shipment_ids, reverses__isnull=True, reversal__isnull=True).select_related('prepayment'):
        key = ('shipment', item.shipment_id)
        data = payments.setdefault(key, {'amount': Decimal('0'), 'natures': set(), 'count': 0})
        data['applied'] = data.get('applied', Decimal('0')) + item.amount
        data['count'] += 1
        nature = (item.prepayment.account_snapshot or {}).get('nature')
        if nature:
            data['natures'].add(nature)
    for data in payments.values():
        data['paid_amount'] = format(data['amount'], '.4f')
        data['applied_amount'] = format(data.get('applied', 0), '.4f')
        natures = data['natures']
        data['classification'] = next(iter(natures)) if len(natures) == 1 else ('mixed' if natures else 'unclassified')
        data['paid'] = data['amount']
        data['unclassified'] = data['amount']+data.get('applied', 0) if not natures else 0
    settlements['payments'] = payments
    return [serialize(entry, fingerprints, details.get(entry.shipment_line_id, {}), settlements) for entry in entries]
