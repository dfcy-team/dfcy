from .shipment_sources import accessible_shipments
"""Read-only product cost projections; never publish a batch as a global price."""
from decimal import Decimal
from django.db.models import Exists, F, OuterRef, Q

from . import costs, logistics
from .models import CostEntry, CostVersion, DispatchAllocation, PurchaseOrder
from .permissions import internal_orders


def fingerprints_for_entries(entries):
    """Compute current input fingerprints for page owners with bounded queries."""
    from . import services
    from .models import InboundOrder, InboundLine, FeeRecord, ShipmentLine, DispatchAllocation
    from .tax_calculation import contract_cost_allocations

    entries = list(entries)
    owners = {}
    for entry in entries:
        version = entry.cost_version
        owner = ('batch', version.batch) if version.batch_id else ('shipment', version.shipment)
        owners[(owner[0], owner[1].pk)] = owner
    if not owners:
        return {}
    shipment_ids = {obj.pk for kind, obj in owners.values() if kind == 'shipment'}
    batch_ids = {obj.pk for kind, obj in owners.values() if kind == 'batch'}

    allocations = list(DispatchAllocation.objects.filter(
        membership__active_guard=True, membership__batch__status='active',
        membership__batch_id__in=batch_ids,
    ).select_related('membership').order_by('membership__batch_id', 'shipment_line_id'))
    quantities_by_batch = {}
    line_ids_by_batch = {}
    for allocation in allocations:
        quantities_by_batch.setdefault(allocation.membership.batch_id, {})[allocation.shipment_line_id] = allocation.quantity
        line_ids_by_batch.setdefault(allocation.membership.batch_id, set()).add(allocation.shipment_line_id)

    line_query = ShipmentLine.objects.filter(tenant=entries[0].tenant, is_active=True).select_related('shipment')
    if shipment_ids and batch_ids:
        line_query = line_query.filter(Q(shipment_id__in=shipment_ids) | Q(pk__in=set().union(*line_ids_by_batch.values())))
    elif shipment_ids:
        line_query = line_query.filter(shipment_id__in=shipment_ids)
    else:
        all_line_ids = set().union(*line_ids_by_batch.values()) if line_ids_by_batch else set()
        line_query = line_query.filter(pk__in=all_line_ids)
    lines = list(line_query.order_by('pk'))
    lines_by_shipment, lines_by_id = {}, {}
    for line in lines:
        lines_by_shipment.setdefault(line.shipment_id, []).append(line)
        lines_by_id[line.pk] = line

    inbounds = {row.batch_id: row for row in InboundOrder.objects.filter(batch_id__in=batch_ids).order_by('-pk')}
    inbound_lines = list(InboundLine.objects.filter(inbound_id__in=[row.pk for row in inbounds.values()]).order_by('shipment_line_id'))
    inbound_lines_by_id = {}
    for row in inbound_lines:
        inbound_lines_by_id.setdefault(row.inbound_id, []).append(row)

    shipment_line_groups = {pk: lines_by_shipment.get(pk, []) for pk in shipment_ids}
    for batch_id in batch_ids:
            shipment_line_groups[('batch', batch_id)] = [lines_by_id[pk] for pk in sorted(line_ids_by_batch.get(batch_id, set())) if pk in lines_by_id]

    all_shipment_ids = shipment_ids | {line.shipment_id for line in lines}
    fee_filter = Q()
    if all_shipment_ids: fee_filter |= Q(shipment_id__in=all_shipment_ids)
    if batch_ids:
        fee_filter |= Q(batch_id__in=batch_ids) | Q(inbound__batch_id__in=batch_ids)
    fee_revisions = {}
    for fee in FeeRecord.objects.filter(tenant=entries[0].tenant).filter(fee_filter).select_related('current_revision'):
        if fee.shipment_id: key = ('shipment', fee.shipment_id)
        elif fee.batch_id: key = ('batch', fee.batch_id)
        else: key = ('inbound', fee.inbound_id)
        fee_revisions[key] = fee.current_revision

    line_ids = [line.pk for line in lines]
    distribution = list(DispatchAllocation.objects.filter(
        shipment_line_id__in=line_ids, membership__active_guard=True, membership__batch__status='active',
    ).order_by('membership__batch_id', 'shipment_line_id').values(
        'membership__batch_id', 'shipment_line_id', 'quantity'))
    contract_rows = contract_cost_allocations(shipment_ids | {
        line.shipment_id for line in lines
    })
    contract_by_shipment = {row['shipment_id']: row for row in contract_rows}

    result = {}
    for key, (kind, obj) in owners.items():
        inbound = inbounds.get(obj.pk) if kind == 'batch' else None
        if kind == 'shipment':
            source_lines = shipment_line_groups.get(obj.pk, [])
            batch_qty = {}
        else:
            source_lines = shipment_line_groups.get(('batch', obj.pk), [])
            batch_qty = quantities_by_batch.get(obj.pk, {})
        source = {'kind': kind, 'id': obj.pk, 'status': obj.status,
            'lines': [{'id': line.pk, 'shipment_id': line.shipment_id, 'sku': line.sku_code_snapshot,
                'quantity': batch_qty.get(line.pk, line.quantity), 'unit_price': costs.text_number(line.unit_price),
                'collection_arrived': line.shipment.collection_arrived} for line in source_lines],
            'inbound': None if not inbound else {'id': inbound.pk, 'status': inbound.status,
                'receipt_ref': inbound.stock_receipt_ref,
                'lines': [{'id': row.pk, 'shipment_line_id': row.shipment_line_id,
                    'received_quantity': row.received_quantity} for row in inbound_lines_by_id.get(inbound.pk, [])]},
            'fees': []}
        fee_owners = [('shipment', shipment) for shipment in {line.shipment_id: line.shipment for line in source_lines}.values()]
        if kind == 'batch': fee_owners.append(('batch', obj))
        if inbound: fee_owners.append(('inbound', inbound))
        for fee_kind, fee_owner in fee_owners:
            source['fees'].append({'kind': fee_kind, 'id': fee_owner.pk,
                'revision_id': (fee_revisions.get((fee_kind, fee_owner.pk)).pk
                    if fee_revisions.get((fee_kind, fee_owner.pk)) else None)})
        source['dispatch_distribution'] = [row for row in distribution
            if row['shipment_line_id'] in {line.pk for line in source_lines}]
        # A single contract snapshot covers all source lines in one shipment;
        # include it once per shipment in the fingerprint input.
        source_shipment_ids = sorted({line.shipment_id for line in source_lines})
        taxes = [contract_by_shipment[shipment_id] for shipment_id in source_shipment_ids
                 if shipment_id in contract_by_shipment]
        if taxes: source['contract_cost_taxes'] = taxes
        source['fees'].sort(key=lambda row: (row['kind'], row['id']))
        result[key] = services.request_hash(source)
    return result


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
        shipment_line__shipment__in=accessible_shipments(orders)).filter(
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
        'shipment_line__sku', 'shipment_line__purchase_line__order__country', 'shipment_line__shipment__order__country',
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
    order = line.purchase_line.order if line.purchase_line_id else line.shipment.order
    goods_revision = (settlements or {}).get(('shipment', line.shipment_id))
    freight_revision = (settlements or {}).get(('batch', version.batch_id)) if version.batch_id else None
    payment_data = (settlements or {}).get('payments', {})
    goods_payment = payment_data.get(('shipment', line.shipment_id), {})
    freight_payment = payment_data.get(('batch', version.batch_id), {}) if version.batch_id else {}
    def settlement_projection(revision, payment):
        old_amount = revision.recorded_amount if revision else Decimal(0)
        new_amount = payment.get('paid', Decimal(0)) + payment.get('applied', Decimal(0))
        total = old_amount + new_amount
        natures = set(payment.get('natures', set()))
        natures.update(payment.get('historical_natures', ()))
        unclassified = payment.get('unclassified', Decimal(0)) + payment.get('historical_unknown', Decimal(0))
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
    missing_fingerprints = [entry for entry in entries if
        (('batch', entry.cost_version.batch_id) if entry.cost_version.batch_id else
         ('shipment', entry.cost_version.shipment_id)) not in fingerprints]
    if missing_fingerprints:
        fingerprints.update(fingerprints_for_entries(missing_fingerprints))
    details = shipment_line_product_details([entry.shipment_line for entry in entries])
    shipment_ids = {entry.shipment_line.shipment_id for entry in entries if entry.shipment_line.shipment_id}
    batch_ids = {entry.cost_version.batch_id for entry in entries if entry.cost_version.batch_id}
    from .cost_models import PaymentClassification
    from .monthly_nature_balances import allocations, NATURES, ZERO

    tenant_id = entries[0].tenant_id if entries else None
    owner_filter = Q(shipment_id__in=shipment_ids) | Q(batch_id__in=batch_ids)
    records = list(SettlementRecord.objects.filter(tenant_id=tenant_id, current_revision__isnull=False)
                   .filter(owner_filter).select_related('current_revision'))
    payment_rows = list(PaymentRecord.objects.filter(
        tenant_id=tenant_id, purpose='goods', reverses__isnull=True, reversal__isnull=True).filter(owner_filter))
    applications = list(PaymentApplication.objects.filter(
        tenant_id=tenant_id, shipment_id__in=shipment_ids, reverses__isnull=True,
        reversal__isnull=True).select_related('prepayment'))
    payment_ids = {row.pk for row in payment_rows} | {row.prepayment_id for row in applications}
    revision_ids = {row.current_revision_id for row in records}
    reviews = list(PaymentClassification.objects.filter(tenant_id=tenant_id).filter(
        Q(payment_id__in=payment_ids) | Q(settlement_revision_id__in=revision_ids)))
    payment_reviews = {row.payment_id: row.allocations for row in reviews if row.payment_id}
    historical_reviews = {row.settlement_revision_id: row.allocations for row in reviews if row.settlement_revision_id}
    settlements, payments = {}, {}

    def owner_data(key):
        return payments.setdefault(key, {'paid': ZERO, 'applied': ZERO, 'natures': set(),
            'unclassified': ZERO, 'count': 0})

    def add_payment(key, payment, amount, field):
        data = owner_data(key)
        data[field] += amount
        data['count'] += 1
        if amount > ZERO:
            parts = allocations(payment.amount, payment.account_snapshot, payment_reviews.get(payment.pk))
            data['natures'].update(nature for nature, part in parts if nature in NATURES and part > ZERO)
            if not any(nature in NATURES for nature, _ in parts):
                data['unclassified'] += amount

    for row in payment_rows:
        key = ('shipment', row.shipment_id) if row.shipment_id else ('batch', row.batch_id)
        add_payment(key, row, row.amount, 'paid')
    for row in applications:
        add_payment(('shipment', row.shipment_id), row.prepayment, row.amount, 'applied')
    for row in records:
        key = ('shipment', row.shipment_id) if row.shipment_id else ('batch', row.batch_id)
        revision = row.current_revision
        settlements[key] = revision
        recorded = revision.recorded_amount
        if not recorded:
            continue
        parts = [{'nature': (item.get('account_snapshot') or {}).get('nature') or item.get('nature'),
                  'amount': item.get('amount')} for item in revision.payee_allocations or []]
        split = allocations(recorded, {}, parts)
        if split == [('unknown', recorded)] and historical_reviews.get(revision.pk):
            split = allocations(recorded, {}, historical_reviews[revision.pk])
        data = owner_data(key)
        data['historical_natures'] = {nature for nature, amount in split if nature in NATURES and amount > ZERO}
        data['historical_unknown'] = sum((amount for nature, amount in split if nature not in NATURES), ZERO)

    for data in payments.values():
        data['paid_amount'] = format(data['paid'], '.4f')
        data['applied_amount'] = format(data['applied'], '.4f')
        natures = data['natures']
        data['classification'] = ('unclassified' if not natures else
            next(iter(natures)) if len(natures) == 1 and not data['unclassified'] else 'mixed')
    settlements['payments'] = payments
    return [serialize(entry, fingerprints, details.get(entry.shipment_line_id, {}), settlements) for entry in entries]
