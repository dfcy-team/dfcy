from .shipment_sources import accessible_shipments
"""Read-only product cost projections; never publish a batch as a global price."""
from decimal import Decimal
from django.db.models import Exists, F, OuterRef, Q, Value

from . import costs, logistics
from .models import CostEntry, CostVersion, DispatchAllocation, PurchaseOrder
from .permissions import internal_orders


def fingerprints_for_entries(entries):
    """Batch-load inputs while using the exact calculation source serializer."""
    from .models import InboundOrder, InboundLine, InboundShortageTermination, FeeRecord, ShipmentLine
    from .tax_calculation import contract_cost_allocations
    entries = list(entries)
    owners = {}
    for entry in entries:
        version = entry.cost_version
        kind, owner = ('batch', version.batch) if version.batch_id else ('shipment', version.shipment)
        owners[(kind, owner.pk)] = (kind, owner)
    if not owners:
        return {}
    batches = {pk for kind, pk in owners if kind == 'batch'}
    shipments = {pk for kind, pk in owners if kind == 'shipment'}
    quantities = {}
    for row in DispatchAllocation.objects.filter(membership__batch_id__in=batches,
            membership__active_guard=True, membership__batch__status='active').values('membership__batch_id', 'shipment_line_id', 'quantity'):
        quantities.setdefault(row['membership__batch_id'], {})[row['shipment_line_id']] = row['quantity']
    ids = {pk for group in quantities.values() for pk in group}
    lines = list(ShipmentLine.objects.filter(tenant_id=entries[0].tenant_id, is_active=True).filter(
        Q(pk__in=ids) | Q(shipment_id__in=shipments)).select_related('shipment').order_by('pk'))
    by_shipment, by_id = {}, {}
    for line in lines:
        by_shipment.setdefault(line.shipment_id, []).append(line)
        by_id[line.pk] = line
    grouped = {key: by_shipment.get(key[1], []) if key[0] == 'shipment' else
        [by_id[pk] for pk in sorted(quantities.get(key[1], {})) if pk in by_id] for key in owners}
    inbounds, inbound_lines, terminations = {}, {}, {}
    for row in InboundOrder.objects.filter(batch_id__in=batches).order_by('pk'):
        inbounds.setdefault(row.batch_id, []).append(row)
    for row in InboundLine.objects.filter(inbound__batch_id__in=batches).order_by('shipment_line_id'):
        inbound_lines.setdefault(row.inbound_id, []).append(row)
    for row in InboundShortageTermination.objects.filter(batch_id__in=batches, origin='final_shortage').order_by('pk').values('id', 'batch_id', 'shipment_line_id', 'quantity', 'origin'):
        batch_id = row.pop('batch_id')
        terminations.setdefault(batch_id, []).append(row)
    shipment_ids = {line.shipment_id for line in lines}
    revisions = {}
    for row in FeeRecord.objects.filter(tenant_id=entries[0].tenant_id).filter(
            Q(shipment_id__in=shipment_ids) | Q(batch_id__in=batches) | Q(inbound__batch_id__in=batches)).select_related('current_revision'):
        key = ('shipment', row.shipment_id) if row.shipment_id else ('batch', row.batch_id) if row.batch_id else ('inbound', row.inbound_id)
        revisions[key] = row.current_revision
    distribution = list(DispatchAllocation.objects.filter(shipment_line_id__in=[line.pk for line in lines],
        membership__active_guard=True, membership__batch__status='active').order_by('membership__batch_id', 'shipment_line_id').values('membership__batch_id', 'shipment_line_id', 'quantity'))
    from .domestic_expense_costs import snapshots
    expense_groups = snapshots(entries[0].tenant_id, shipment_ids)
    data = dict(lines=grouped, inbounds=inbounds, inbound_lines=inbound_lines, terminations=terminations,
        quantities=quantities, revisions=revisions, distribution=distribution, taxes=contract_cost_allocations(shipment_ids), expense_groups=expense_groups)
    return {key: costs.inputs(*owner, data=data)[1] for key, owner in owners.items()}


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
                         ('batch_id', 'cost_version__batch_id')):
        if param in params:
            rows = rows.filter(**{field: params[param]})
    if 'warehouse_id' in params:
        from .models import InternalStockReceiptLine
        matching = InternalStockReceiptLine.objects.filter(
            receipt__inbound__batch_id=OuterRef('cost_version__batch_id'),
            inbound_line__shipment_line_id=OuterRef('shipment_line_id'),
            receipt__warehouse_id=params['warehouse_id'], receipt__inbound__status='confirmed',
            receipt__created_at__lte=OuterRef('cost_version__created_at'))
        rows = rows.annotate(_warehouse_match=Exists(matching),
            _projection_warehouse_id=Value(int(params['warehouse_id']))).filter(
                Q(receipt_line__receipt__warehouse_id=params['warehouse_id']) | Q(_warehouse_match=True))
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
    result = {**costs.entry_data(entry, details), 'id': entry.pk, 'sku_id': line.sku_id,
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
    if 'receipt_cost_allocations' in version.summary:
        allocations = [row for row in version.summary['receipt_cost_allocations'] if row['shipment_line_id'] == line.pk]
        projection = getattr(entry, '_projection_warehouse_id', None)
        if projection is not None:
            allocations = [row for row in allocations if row['warehouse_id'] == projection]
            result['received_quantity'] = sum(row['actual_quantity'] for row in allocations)
            for name in ('received_goods_amount', 'received_collection_fee', 'received_freight_fee', 'clearance_fee', 'received_total'):
                values = [row[name] for row in allocations]
                result[name] = None if any(value is None for value in values) else costs.text_number(sum((Decimal(value) for value in values), Decimal(0)))
            quantity, amount = result['received_quantity'], result['received_total']
            result['received_unit_cost'] = costs.text_number(Decimal(amount) / quantity, costs.UNIT) if quantity and amount is not None else None
            # Planned and pending costs remain explicitly batch-wide.
            result['aggregation_basis'] = 'warehouse_received; planned_and_pending_are_batch_totals; payments_are_source_totals'
            from apps.masterdata.models import WarehouseMaster
            warehouse = WarehouseMaster.objects.get(tenant_id=entry.tenant_id, pk=projection)
            result.update(warehouse_id=warehouse.pk, warehouse_name=warehouse.name)
        else:
            result['aggregation_basis'] = 'batch_totals; receipt_cost_allocations identify warehouse shares'
            warehouse_ids = {row['warehouse_id'] for row in allocations}
            if len(warehouse_ids) == 1:
                from apps.masterdata.models import WarehouseMaster
                warehouse = WarehouseMaster.objects.get(tenant_id=entry.tenant_id, pk=next(iter(warehouse_ids)))
                result.update(warehouse_id=warehouse.pk, warehouse_name=warehouse.name)
        result['receipt_cost_allocations'] = allocations
        result['warehouse_ids'] = sorted({row['warehouse_id'] for row in allocations})
    return result



def serialize_many(entries, fingerprints):
    from .supplier_products import shipment_line_product_details
    from django.db.models import Q
    from .models import SettlementRecord, PaymentRecord, PaymentApplication
    entries = list(entries)
    # Historical/inactive owners never use fingerprint status validation in serialize().
    missing_fingerprints = [entry for entry in entries if not entry.has_newer and
        ((entry.cost_version.batch_id and entry.cost_version.batch.status == 'active' and entry.in_owner_batch) or
         (entry.cost_version.shipment_id and entry.cost_version.shipment.status == 'submitted' and not entry.has_active_batch)) and
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
