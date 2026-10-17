"""Deterministic fee allocation and append-only cost observations.

The procurement amount basis is shared by prices and fees. Settlement references
do not execute a payment and cost adjustments do not change receipt quantities.
"""
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP, localcontext

from django.core.exceptions import ValidationError
from django.db import transaction
from rest_framework.exceptions import NotFound, PermissionDenied

from . import logistics, services, shipments, dispatch_allocations
from .models import (CostAdjustment, CostEntry, CostVersion, FeeRecord, FeeRevision,
                     InboundOrder, InternalStockReceiptLine, PurchaseOrder, SettlementRecord,
                     SettlementRevision, ShipmentLine, SupplierShipment, domain_write)
from .permissions import MANAGE, VIEW, internal_orders
from .supplier_products import safe_image_url, shipment_line_product_details

ZERO = Decimal('0')
MONEY = Decimal('0.0001')
MEASURE = Decimal('0.000001')
UNIT = Decimal('0.00000001')
FEE_LABELS = {'shipment': '国内发货费用（集货或装柜）', 'batch': '货运费用', 'inbound': '清货费用'}


def decimal(value, *, places=4, nullable=False):
    if value is None and nullable:
        return None
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0 or result != result.quantize(Decimal(1).scaleb(-places)):
            raise ValueError()
        return result
    except Exception as exc:
        raise ValidationError('金额或计量必须是精度范围内的非负数。') from exc


def money(value):
    return None if value is None else value.quantize(MONEY, rounding=ROUND_HALF_UP)


def text_number(value, quantum=MONEY):
    with localcontext() as ctx:
        ctx.prec = 60
        return None if value is None else format(value.quantize(quantum, rounding=ROUND_HALF_UP), 'f')


def target_for(actor, kind, pk, permission=VIEW):
    # This internal-only check must precede shipment_for's supplier-aware helper.
    internal_orders(actor, PurchaseOrder.objects.none(), permission)
    if kind == 'shipment':
        return shipments.shipment_for(actor, pk, permission)
    if kind == 'batch':
        return logistics.batch_for(actor, pk, permission)
    if kind == 'inbound':
        return logistics.inbound_for(actor, pk, permission)
    raise NotFound('费用单据类型不存在。')


def targets(actor, kind):
    orders = internal_orders(actor, PurchaseOrder.objects.all())
    if kind == 'shipment':
        return SupplierShipment.objects.filter(tenant=actor.tenant, order__in=orders, status='submitted')
    if kind == 'batch':
        return logistics.batches_for(actor).filter(status='active')
    if kind == 'inbound':
        return InboundOrder.objects.filter(tenant=actor.tenant, batch__in=logistics.batches_for(actor))
    raise NotFound('费用单据类型不存在。')


def target_data(kind, obj):
    country = obj.order.country_code_snapshot if kind == 'shipment' else (
        obj.batch.country_code_snapshot if kind == 'inbound' else obj.country_code_snapshot)
    return {'kind': kind, 'id': obj.pk, 'number': obj.number, 'country_code': country,
            'version': obj.version, 'stage': obj.stage if kind == 'batch' else obj.status}


def fee_gate(kind, obj):
    if kind == 'shipment':
        return (obj.status == 'submitted' and (obj.collection_arrived or obj.delivery_mode == 'factory_loading'),
                '送集货中心须提交并标记集货到仓；货柜上门装载须先提交发货单。')
    if kind == 'batch':
        return (obj.status == 'active' and obj.stage != 'unmarked', '请先标记有效批次开船。')
    checked = obj.lines.exists() and not obj.lines.filter(received_quantity__isnull=True).exists()
    return (checked and obj.batch.status == 'active', '请先逐行填写实收数量，再维护清货费用。')


def source_lines(kind, obj):
    query = ShipmentLine.objects.filter(tenant=obj.tenant, is_active=True)
    if kind == 'shipment':
        query = query.filter(shipment=obj)
    elif kind == 'batch':
        query = query.filter(pk__in=dispatch_allocations.batch_quantities(obj))
    else:
        query = query.filter(inbound_lines__inbound=obj)
    return list(query.select_related('sku', 'shipment').order_by('pk'))


def measurements(kind, obj, overrides=None):
    lines = source_lines(kind, obj)
    details_by_line = shipment_line_product_details(lines)
    received = dict(obj.lines.values_list('shipment_line_id', 'received_quantity')) if kind == 'inbound' else {}
    batch_qty = dispatch_allocations.batch_quantities(obj) if kind == 'batch' else {}
    overrides = overrides or []
    ids = [row['shipment_line_id'] for row in overrides]
    if len(set(ids)) != len(ids) or not set(ids).issubset({line.pk for line in lines}):
        raise ValidationError('分摊计量行重复或不属于本单据。')
    by_id = {row['shipment_line_id']: row for row in overrides}
    result = []
    for line in lines:
        qty = received.get(line.pk) if kind == 'inbound' else batch_qty.get(line.pk, line.quantity)
        sku = line.sku
        unit_volume, volume_source = sku.package_volume, 'sku_volume'
        if unit_volume is None:
            dimensions = [sku.package_length_cm, sku.package_width_cm, sku.package_height_cm]
            if all(value is not None and value > 0 for value in dimensions):
                unit_volume = dimensions[0] * dimensions[1] * dimensions[2] / Decimal('1000000')
                volume_source = 'sku_dimensions'
        unit_weight = None if sku.package_weight is None else sku.package_weight / Decimal('1000')
        volume = None if unit_volume is None or qty is None else unit_volume * qty
        weight = None if unit_weight is None or qty is None else unit_weight * qty
        override = by_id.get(line.pk, {})
        weight_source = 'sku_weight'
        if override.get('volume_cbm') is not None:
            volume = decimal(override['volume_cbm'], places=6)
            volume_source = 'manual_total'
        if override.get('weight_kg') is not None:
            weight = decimal(override['weight_kg'], places=6)
            weight_source = 'manual_total'
        details = details_by_line.get(line.pk, {})
        result.append({'shipment_line_id': line.pk, 'sku': line.sku_code_snapshot,
            'legacy_sku_code': line.sku.legacy_sku_code or '',
            'product_details': {'image_url': details.get('image_url', '')},
            'image_preview_url': (f'/api/internal/supply-chain/v2/supplier-shipments/{line.shipment_id}/skus/{line.sku_id}/image/'
                if details.get('image_url') else ''),
            'product_name': line.product_name_snapshot, 'quantity': qty,
            'volume_cbm': text_number(volume, MEASURE), 'weight_kg': text_number(weight, MEASURE),
            'volume_source': volume_source, 'weight_source': weight_source,
            'sku_unit_volume_cbm': text_number(unit_volume, MEASURE),
            'sku_unit_weight_kg': text_number(unit_weight, MEASURE)})
    return result


def allocate(amount, rows, method, volume_percent):
    """Allocate integer money units; largest remainders then stable source ID."""
    amount = decimal(amount)
    percent = decimal(volume_percent, places=2)
    if method not in ('volume', 'weight', 'mixed') or percent > 100:
        raise ValidationError('请选择体积、重量或混合方式；体积占比须为 0–100。')
    if any(row['quantity'] is None for row in rows):
        raise ValidationError('未核对数量不能作为分摊依据。')
    participating = [row for row in rows if row['quantity'] > 0]
    if not participating and amount > 0:
        raise ValidationError('没有实收商品，不能分摊正数清货费用。')
    if amount == 0:
        return [{**row, 'amount': '0.0000'} for row in rows]
    with localcontext() as ctx:
        ctx.prec = 60
        volume_ratio = Decimal(1) if method == 'volume' else (ZERO if method == 'weight' else percent / 100)
        weight_ratio = 1 - volume_ratio
        for dimension, ratio, label in [('volume_cbm', volume_ratio, '体积'), ('weight_kg', weight_ratio, '重量')]:
            if ratio and any(row[dimension] is None or Decimal(row[dimension]) <= 0 for row in participating):
                raise ValidationError(f'分摊需要每个参与商品的正数{label}；请完善商品档案或填写本次实测总量。')
        volume_total = sum((Decimal(row['volume_cbm']) for row in participating), ZERO) if volume_ratio else ZERO
        weight_total = sum((Decimal(row['weight_kg']) for row in participating), ZERO) if weight_ratio else ZERO
        units = int(amount / MONEY)
        raw = {}
        for row in participating:
            share = ((volume_ratio * Decimal(row['volume_cbm']) / volume_total if volume_ratio else ZERO)
                     + (weight_ratio * Decimal(row['weight_kg']) / weight_total if weight_ratio else ZERO))
            raw[row['shipment_line_id']] = units * share
        assigned = {pk: int(value.to_integral_value(rounding=ROUND_FLOOR)) for pk, value in raw.items()}
        remainder = units - sum(assigned.values())
        ranking = sorted(raw, key=lambda pk: (-(raw[pk] - assigned[pk]), pk))
        for pk in ranking[:remainder]:
            assigned[pk] += 1
        return [{**row, 'amount': text_number(Decimal(assigned.get(row['shipment_line_id'], 0)) * MONEY)} for row in rows]


def fee_record(kind, obj):
    return FeeRecord.objects.filter(tenant=obj.tenant, **{kind: obj}).select_related('current_revision').first()


def fee_data(revision):
    if not revision:
        return None
    return {'id': revision.fee_id, 'revision_id': revision.pk, 'version': revision.sequence,
            'amount': text_number(revision.amount), 'state': revision.state, 'method': revision.method,
            'volume_percent': text_number(revision.volume_percent, Decimal('.01')),
            'billed_cbm': text_number(revision.billed_cbm, MEASURE), 'notes': revision.notes,
            'reason': revision.reason, 'allocations': revision.allocations, 'created_at': revision.created_at}


@transaction.atomic
def save_fee(actor, kind, pk, payload, key):
    services._internal(actor)
    services._tenant_lock(actor)
    obj = target_for(actor, kind, pk, MANAGE)
    if services._prior_event(actor, obj, 'fee_revised', key, payload):
        return obj
    services._version(obj, payload['expected_source_version'])
    allowed, explanation = fee_gate(kind, obj)
    if not allowed:
        raise ValidationError(explanation)
    if not payload['reason'].strip():
        raise ValidationError('请填写本次费用维护或更正原因。')
    record = fee_record(kind, obj)
    if payload['expected_version'] != (record.version if record else 0):
        raise ValidationError('费用版本已变化，请重新加载。')
    rows = measurements(kind, obj, payload.get('measurements'))
    allocations = allocate(payload['amount'], rows, payload['method'], payload['volume_percent'])
    cbm = decimal(payload.get('billed_cbm'), places=6, nullable=True)
    if kind == 'shipment' and cbm is not None:
        raise ValidationError('到集货点费用不设置货运或清货计费方数。')
    with domain_write():
        if record is None:
            record = FeeRecord.objects.create(tenant=actor.tenant, created_by=actor, **{kind: obj})
        else:
            record.version += 1
        revision = FeeRevision.objects.create(tenant=actor.tenant, created_by=actor, fee=record,
            sequence=record.version, amount=decimal(payload['amount']), state=payload['state'],
            method=payload['method'], volume_percent=decimal(payload['volume_percent'], places=2),
            billed_cbm=cbm, notes=payload.get('notes', ''), reason=payload['reason'], allocations=allocations)
        record.current_revision = revision
        record.save()
        if kind == 'batch':
            obj.billed_cbm = cbm
        elif kind == 'inbound':
            obj.clearance_cbm = cbm
        obj.version += 1
        obj.save()
        services._event(actor, obj, 'fee_revised', key, payload,
                        audit={'fee_id': record.pk, 'fee_revision_id': revision.pk, 'allocations': allocations})
    return obj


def canonical(actor, kind, obj, permission=VIEW):
    if kind == 'inbound':
        return 'batch', logistics.batch_for(actor, obj.batch_id, permission)
    if kind == 'shipment':
        memberships = list(obj.dispatch_memberships.filter(active_guard=True))
        membership = memberships[0] if len(memberships) == 1 else None
        if membership:
            return 'batch', logistics.batch_for(actor, membership.batch_id, permission)
    return kind, obj


def inputs(kind, obj):
    lines = source_lines(kind, obj)
    inbound = InboundOrder.objects.filter(batch=obj).first() if kind == 'batch' else None
    inbound_rows = list(inbound.lines.order_by('shipment_line_id')) if inbound else []
    batch_qty = dispatch_allocations.batch_quantities(obj) if kind == 'batch' else {}
    source = {'kind': kind, 'id': obj.pk, 'status': obj.status,
        'lines': [{'id': line.pk, 'shipment_id': line.shipment_id, 'sku': line.sku_code_snapshot,
                   'quantity': batch_qty.get(line.pk, line.quantity), 'unit_price': text_number(line.unit_price),
                   'collection_arrived': line.shipment.collection_arrived} for line in lines],
        'inbound': None if not inbound else {'id': inbound.pk, 'status': inbound.status,
                   'receipt_ref': inbound.stock_receipt_ref,
                   'lines': [{'id': row.pk, 'shipment_line_id': row.shipment_line_id,
                              'received_quantity': row.received_quantity} for row in inbound_rows]}, 'fees': []}
    owners = [('shipment', shipment) for shipment in {line.shipment_id: line.shipment for line in lines}.values()]
    if kind == 'batch':
        owners.append(('batch', obj))
    if inbound:
        owners.append(('inbound', inbound))
    revisions = {}
    for owner_kind, owner in owners:
        record = fee_record(owner_kind, owner)
        revision = record.current_revision if record else None
        revisions[(owner_kind, owner.pk)] = revision
        source['fees'].append({'kind': owner_kind, 'id': owner.pk,
                              'revision_id': revision.pk if revision else None})
    source['dispatch_distribution'] = list(dispatch_allocations.active().filter(shipment_line_id__in=[line.pk for line in lines]).order_by('membership__batch_id', 'shipment_line_id').values('membership__batch_id', 'shipment_line_id', 'quantity'))
    source['fees'].sort(key=lambda row: (row['kind'], row['id']))
    return source, services.request_hash(source), lines, inbound, inbound_rows, revisions


def fee_amounts(kind, owner, revision, issues):
    if revision is None:
        issues.append(f'{owner.number}：{FEE_LABELS[kind]}未维护；无费用时也需确认零。')
        return {line.pk: None for line in source_lines(kind, owner)}
    current = {row['shipment_line_id']: row['quantity'] for row in measurements(kind, owner)}
    frozen = {row['shipment_line_id']: row['quantity'] for row in revision.allocations}
    if current != frozen:
        raise ValidationError(f'{owner.number}：分摊数量已变化，请重新维护{FEE_LABELS[kind]}。')
    if revision.state != 'confirmed':
        issues.append(f'{owner.number}：{FEE_LABELS[kind]}仍为暂估。')
    return {row['shipment_line_id']: Decimal(row['amount']) for row in revision.allocations}


def entry_data(entry, details=None):
    details = details or {'image_url': safe_image_url(entry.shipment_line.sku.image_url, entry.tenant_id)}
    image_url = details.get('image_url', '')
    result = {'shipment_line_id': entry.shipment_line_id, 'receipt_line_id': entry.receipt_line_id,
              'sku': entry.shipment_line.sku_code_snapshot,
              'legacy_sku_code': entry.shipment_line.sku.legacy_sku_code or '', 'quantity': entry.quantity,
              'product_details': {'image_url': image_url},
              'image_preview_url': (f'/api/internal/supply-chain/v2/supplier-shipments/{entry.shipment_line.shipment_id}/skus/{entry.shipment_line.sku_id}/image/'
                  if image_url else ''),
              'received_quantity': entry.received_quantity}
    for name in ('goods_amount', 'collection_fee', 'freight_fee', 'clearance_fee', 'received_goods_amount',
                 'received_collection_fee', 'received_freight_fee', 'shipped_total', 'received_total', 'pending_total'):
        result[name] = text_number(getattr(entry, name))
    for name in ('shipped_unit_cost', 'received_unit_cost'):
        result[name] = text_number(getattr(entry, name), UNIT)
    return result


def cost_data(obj, fingerprint=None, *, detail=True):
    result = {'id': obj.pk, 'sequence': obj.sequence,
        'status': 'recalculation_required' if fingerprint and obj.input_fingerprint != fingerprint else obj.state,
        'calculated_status': obj.state, 'stage': obj.stage, 'issues': obj.issues,
        'summary': obj.summary, 'created_at': obj.created_at}
    if detail:
        entries = list(obj.entries.select_related('shipment_line__sku__spu__category_node',
            'shipment_line__shipment__order'))
        details_by_line = shipment_line_product_details([entry.shipment_line for entry in entries])
        result['entries'] = [entry_data(entry, details_by_line.get(entry.shipment_line_id, {})) for entry in entries]
        result['adjustments'] = [{'receipt_line_id': row.receipt_line_id,
            'previous_amount': text_number(row.previous_amount), 'current_amount': text_number(row.current_amount),
            'delta': text_number(row.delta)} for row in obj.adjustments.order_by('receipt_line_id')]
    return result


@transaction.atomic
def calculate(actor, kind, pk, payload, key):
    services._internal(actor)
    services._tenant_lock(actor)
    obj = target_for(actor, kind, pk, MANAGE)
    if kind == 'shipment' and obj.dispatch_memberships.filter(active_guard=True).exists():
        raise ValidationError('已集货的成本请按具体集货批次计算。')
    canonical_kind, canonical_obj = canonical(actor, kind, obj, MANAGE)
    if canonical_kind != kind or canonical_obj.pk != obj.pk:
        raise ValidationError('已集货的成本请按集货批次计算，避免重复形成入库成本调整。')
    digest, key = services.request_hash({'kind': kind, 'id': pk, **payload}), services._key(key)
    replay = CostVersion.objects.filter(tenant=actor.tenant, creation_key=key).first()
    if replay:
        services._matching_replay(replay, digest)
        return replay
    services._version(obj, payload['expected_source_version'])
    if obj.status != ('submitted' if kind == 'shipment' else 'active'):
        raise ValidationError('请对已提交发货单或有效集货批次计算成本。')
    source, fingerprint, lines, inbound, inbound_rows, revisions = inputs(kind, obj)
    if payload['expected_input_fingerprint'] != fingerprint:
        raise ValidationError('价格、费用或入库数量已变化，请重新加载后计算。')
    if not lines:
        raise ValidationError('没有商品，不能计算成本。')
    issues, collection = [], {}
    for shipment in {line.shipment_id: line.shipment for line in lines}.values():
        collection.update(fee_amounts('shipment', shipment, revisions[('shipment', shipment.pk)], issues))
    batch_qty = dispatch_allocations.batch_quantities(obj) if kind == 'batch' else {}
    if kind == 'batch':
        # Cumulative rounding assigns each source fee exactly once, including the unallocated remainder.
        before = {}
        for allocation in source['dispatch_distribution']:
            if allocation['membership__batch_id'] < obj.pk:
                pk = allocation['shipment_line_id']
                before[pk] = before.get(pk, 0) + allocation['quantity']
        for line in lines:
            amount = collection.get(line.pk)
            if amount is not None:
                start = before.get(line.pk, 0)
                collection[line.pk] = money(amount * Decimal(start + batch_qty[line.pk]) / line.quantity) - money(amount * Decimal(start) / line.quantity)
    freight = fee_amounts('batch', obj, revisions[('batch', obj.pk)], issues) if kind == 'batch' else {}
    clearance = fee_amounts('inbound', inbound, revisions[('inbound', inbound.pk)], issues) if inbound else {}
    checked = bool(inbound_rows) and all(row.received_quantity is not None for row in inbound_rows)
    if inbound and (not checked or inbound.status != 'confirmed'):
        issues.append('入库数量尚未核对并确认，入库成本仅为暂估。')
    if not inbound:
        issues.append('尚未生成并确认入库，本次为发货阶段成本。')
    quantities = {row.shipment_line_id: row.received_quantity for row in inbound_rows}
    receipts = {row.inbound_line.shipment_line_id: row for row in
        InternalStockReceiptLine.objects.filter(receipt__inbound=inbound).select_related('inbound_line')} if inbound else {}
    entries = []
    with localcontext() as ctx:
        ctx.prec = 60
        for line in lines:
            qty, received = batch_qty.get(line.pk, line.quantity), quantities.get(line.pk) if checked else None
            goods = None if line.unit_price is None else money(line.unit_price * qty)
            if goods is None:
                issues.append(f'{line.shipment.number} / {line.sku_code_snapshot}：实际采购价格未填写。')
            collect, transport, clear = collection.get(line.pk, ZERO), freight.get(line.pk, ZERO), clearance.get(line.pk, ZERO)
            shipped_total = None if any(value is None for value in (goods, collect, transport)) else goods + collect + transport
            proportion = None if received is None else Decimal(min(received, qty)) / qty
            released_goods = None if proportion is None or goods is None else money(goods * proportion)
            released_collect = None if proportion is None or collect is None else money(collect * proportion)
            released_transport = None if proportion is None or transport is None else money(transport * proportion)
            if received == 0:
                released_goods = released_collect = released_transport = ZERO
            received_total = (None if received is None or any(value is None for value in (
                              released_goods, released_collect, released_transport, clear)) else
                              released_goods + released_collect + released_transport + clear)
            pending = None if shipped_total is None else (shipped_total if received is None else
                      shipped_total - (released_goods or ZERO) - released_collect - released_transport)
            if received is not None and received > qty:
                issues.append(f'{line.sku_code_snapshot}：实收超发货；额外货值尚需采购核对，成本仍为暂估。')
            entries.append({'shipment_line': line, 'receipt_line': receipts.get(line.pk),
                'quantity': qty, 'received_quantity': received, 'goods_amount': goods,
                'collection_fee': collect, 'freight_fee': transport, 'clearance_fee': clear,
                'received_goods_amount': released_goods, 'received_collection_fee': released_collect,
                'received_freight_fee': released_transport, 'shipped_total': shipped_total,
                'received_total': received_total, 'pending_total': pending,
                'shipped_unit_cost': None if shipped_total is None else (shipped_total / qty).quantize(UNIT, rounding=ROUND_HALF_UP),
                'received_unit_cost': None if not received or received_total is None else (received_total / received).quantize(UNIT, rounding=ROUND_HALF_UP)})
    def total(name):
        with localcontext() as ctx:
            ctx.prec = 60
            return None if any(row[name] is None for row in entries) else text_number(sum((row[name] for row in entries), ZERO))
    summary = {'shipped_quantity': sum(row['quantity'] for row in entries),
        'received_quantity': sum(row['received_quantity'] for row in entries) if checked else None,
        'shipped_total': total('shipped_total'), 'received_total': total('received_total'), 'pending_total': total('pending_total')}
    prior = CostVersion.objects.filter(tenant=actor.tenant, **{kind: obj}).order_by('-sequence').first()
    prior_entries = {row.receipt_line_id: row for row in prior.entries.all() if row.receipt_line_id} if prior else {}
    with domain_write():
        version = CostVersion.objects.create(tenant=actor.tenant, created_by=actor, **{kind: obj},
            sequence=prior.sequence + 1 if prior else 1, state='estimated' if issues else 'confirmed',
            stage='received' if checked else 'shipped', input_fingerprint=fingerprint, source_snapshot=source,
            summary=summary, issues=list(dict.fromkeys(issues)), creation_key=key, request_hash=digest)
        for row in entries:
            entry = CostEntry.objects.create(tenant=actor.tenant, created_by=actor, cost_version=version, **row)
            old = prior_entries.get(entry.receipt_line_id)
            if (old and old.received_total is not None and entry.received_total is not None
                    and old.received_total != entry.received_total):
                CostAdjustment.objects.create(tenant=actor.tenant, created_by=actor, previous_version=prior,
                    current_version=version, receipt_line=entry.receipt_line, previous_amount=old.received_total,
                    current_amount=entry.received_total, delta=entry.received_total - old.received_total)
        services._event(actor, obj, 'cost_calculated', key, payload, audit={'cost_version_id': version.pk,
                       'cost_sequence': version.sequence, 'input_fingerprint': fingerprint, 'summary': summary})
    return version


def settlement_amount(kind, obj):
    if kind == 'shipment':
        lines = source_lines(kind, obj)
        if obj.status != 'submitted' or not lines or any(line.unit_price is None for line in lines):
            return None
        with localcontext() as ctx:
            ctx.prec = 60
            return sum((money(line.unit_price * line.quantity) for line in lines), ZERO)
    if kind == 'batch':
        record = fee_record(kind, obj)
        revision = record.current_revision if record else None
        return revision.amount if obj.status == 'active' and revision and revision.state == 'confirmed' else None
    return None


def settlement_data(kind, obj):
    if kind not in ('shipment', 'batch'):
        return None, []
    current = settlement_amount(kind, obj)
    record = SettlementRecord.objects.filter(tenant=obj.tenant, **{kind: obj}).select_related('current_revision').first()
    revision = record.current_revision if record else None
    history = [] if not record else [{'version': row.sequence, 'recorded_amount': text_number(row.recorded_amount),
        'reference_number': row.reference_number, 'date': row.date, 'notes': row.notes, 'reason': row.reason,
        'source_amount': row.source_snapshot.get('amount'), 'created_at': row.created_at}
        for row in record.revisions.order_by('-sequence')]
    recorded = revision.recorded_amount if revision else ZERO
    if revision and current is not None:
        due = current - Decimal(revision.source_snapshot['amount'])
    else:
        due = None
    terms = None
    if kind == 'shipment':
        from .payment_terms import shipment_payment_reference
        terms = shipment_payment_reference(obj)
    return {'version': record.version if record else 0, 'recorded_amount': text_number(recorded), 'payment_terms': terms,
        'reference_number': revision.reference_number if revision else '', 'date': revision.date if revision else None,
        'notes': revision.notes if revision else '', 'current_amount': text_number(current),
        'unsettled_amount': None if current is None else text_number(max(current - recorded, ZERO)),
        'over_recorded_amount': None if current is None else text_number(max(recorded - current, ZERO)),
        'status': ('unsettled' if not revision or current is None or (recorded == 0 and current > 0) else
                   'partially_settled' if recorded < current else 'settled'),
        'adjustment_due': text_number(due), 'supported': True}, history


@transaction.atomic
def save_settlement(actor, kind, pk, payload, key):
    services._internal(actor)
    services._tenant_lock(actor)
    obj = target_for(actor, kind, pk, MANAGE)
    if kind not in ('shipment', 'batch'):
        raise ValidationError('结算登记仅适用于供应商发货货值与集货货运费用。')
    if services._prior_event(actor, obj, 'settlement_registered', key, payload):
        return obj
    services._version(obj, payload['expected_source_version'])
    current = settlement_amount(kind, obj)
    if current is None:
        raise ValidationError('请先补齐有效发货价格，或将货运费用标记为已确认。')
    if not payload['reference_number'].strip() or not payload['reason'].strip():
        raise ValidationError('请填写结算来源单号和登记原因。')
    record = SettlementRecord.objects.filter(tenant=obj.tenant, **{kind: obj}).first()
    if payload['expected_version'] != (record.version if record else 0):
        raise ValidationError('结算登记已变化，请重新加载。')
    with domain_write():
        if record is None:
            record = SettlementRecord.objects.create(tenant=actor.tenant, created_by=actor, **{kind: obj})
        else:
            record.version += 1
        revision = SettlementRevision.objects.create(tenant=actor.tenant, created_by=actor, settlement=record,
            sequence=record.version, recorded_amount=decimal(payload['recorded_amount']),
            reference_number=payload['reference_number'], date=services._date(payload['date']),
            notes=payload.get('notes', ''), reason=payload['reason'],
            source_snapshot={'kind': kind, 'id': obj.pk, 'source_version': obj.version, 'amount': text_number(current)})
        record.current_revision = revision
        record.save()
        services._event(actor, obj, 'settlement_registered', key, payload, audit={'settlement_revision_id': revision.pk,
            'source_amount': text_number(current), 'registered_cumulative_amount': text_number(revision.recorded_amount)})
    return obj


def context(actor, kind, pk):
    obj = target_for(actor, kind, pk)
    allowed, reason = fee_gate(kind, obj)
    try:
        target_for(actor, kind, pk, MANAGE)
    except (NotFound, PermissionDenied):
        allowed, reason = False, '本单据仅有查看权限。'
    target = {**target_data(kind, obj), 'fee_editable': allowed, 'fee_block_reason': '' if allowed else reason,
              'calculation_kind': kind, 'calculation_id': obj.pk, 'calculation_version': obj.version,
              'calculation_allowed': False}
    latest, history, fingerprint = None, [], None
    try:
        calc_kind, calc_obj = canonical(actor, kind, obj)
        target.update(calculation_kind=calc_kind, calculation_id=calc_obj.pk, calculation_version=calc_obj.version)
        _, fingerprint, *_ = inputs(calc_kind, calc_obj)
        versions = CostVersion.objects.filter(tenant=actor.tenant, **{calc_kind: calc_obj}).order_by('-sequence')
        latest_obj = versions.first()
        latest = cost_data(latest_obj, fingerprint) if latest_obj else None
        history = [cost_data(row, detail=False) for row in versions[:100]]
        target_for(actor, calc_kind, calc_obj.pk, MANAGE)
        target['related_batches'] = dispatch_allocations.distribution(obj) if kind == 'shipment' else []
        target['calculation_allowed'] = (kind != 'shipment' or not target['related_batches']) and calc_obj.status == (
            'submitted' if calc_kind == 'shipment' else 'active')
    except (NotFound, PermissionDenied):
        # A scoped buyer may see this supplier's shipment but not the whole batch.
        target['calculation_allowed'] = False
    record = fee_record(kind, obj)
    fee = fee_data(record.current_revision) if record else None
    fee_history = [fee_data(row) for row in record.revisions.order_by('-sequence')[:100]] if record else []
    settlement, settlement_history = settlement_data(kind, obj)
    current_measurements = measurements(kind, obj)
    # Retain explicitly measured totals when only amount/ratio changes; a changed
    # quantity needs new measurement and must not reuse the old total silently.
    frozen = {row['shipment_line_id']: row for row in fee['allocations']} if fee else {}
    for row in current_measurements:
        old = frozen.get(row['shipment_line_id'])
        if old and old['quantity'] == row['quantity']:
            for name, source_name in [('volume_cbm', 'volume_source'), ('weight_kg', 'weight_source')]:
                if old.get(source_name) == 'manual_total':
                    row[name], row[source_name] = old[name], 'manual_total'
    legacy_by_line = {row['shipment_line_id']: row['legacy_sku_code'] for row in current_measurements}
    image_by_line = {row['shipment_line_id']: (row['product_details'], row['image_preview_url']) for row in current_measurements}
    for fee_value in [fee, *fee_history]:
        if fee_value:
            for allocation in fee_value.get('allocations', []):
                if 'legacy_sku_code' not in allocation:
                    allocation['legacy_sku_code'] = legacy_by_line.get(allocation['shipment_line_id'], '')
                if 'product_details' not in allocation:
                    allocation['product_details'], allocation['image_preview_url'] = image_by_line.get(
                        allocation['shipment_line_id'], ({'image_url': ''}, ''))
    from .freight_channels import freight_reference
    quote_reference = freight_reference(obj, fee.get('billed_cbm') if fee else None) if kind == 'batch' else None
    return {'target': target, 'fee': fee, 'fee_history': fee_history, 'freight_quote_reference': quote_reference,
        'measurements': current_measurements, 'latest_cost': latest, 'cost_history': history,
        'input_fingerprint': fingerprint, 'settlement': settlement,
        'settlement_supported': kind in ('shipment', 'batch'), 'settlement_history': settlement_history}


def version_for(actor, kind, pk, sequence):
    obj = target_for(actor, kind, pk)
    calc_kind, calc_obj = canonical(actor, kind, obj)
    version = CostVersion.objects.filter(tenant=actor.tenant, sequence=sequence, **{calc_kind: calc_obj}).first()
    if version is None:
        raise NotFound('成本版本不存在。')
    return cost_data(version)
