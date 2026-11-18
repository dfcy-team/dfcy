"""Immutable allocations per physical receipt; no inventory or payment mutations."""
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction

from . import costs, services
from .models import CostAdjustment, CostEntry, CostVersion, InboundOrder, InternalStockReceiptLine, domain_write

ZERO = Decimal(0)
COMPONENTS = ('received_goods_amount', 'received_collection_fee', 'received_freight_fee', 'clearance_fee', 'received_total')


def receipt_allocations(version):
    """Read v2 snapshots, retaining the historical CostEntry fallback."""
    if 'receipt_cost_allocations' in version.summary:
        return version.summary['receipt_cost_allocations']
    return [dict(schema_version=1, receipt_line_id=entry.receipt_line_id,
        shipment_line_id=entry.shipment_line_id, inbound_id=entry.receipt_line.receipt.inbound_id,
        sku_id=entry.shipment_line.sku_id, warehouse_id=entry.receipt_line.receipt.warehouse_id,
        actual_quantity=entry.received_quantity, consumed_quantity=min(entry.received_quantity or 0, entry.quantity),
        **{name: costs.text_number(getattr(entry, name)) for name in COMPONENTS})
        for entry in version.entries.filter(receipt_line__isnull=False).select_related('receipt_line__receipt', 'shipment_line')]


def _sum(values):
    values = list(values)
    return None if any(value is None for value in values) else sum(values, ZERO)


def released(amount, before, quantity, planned):
    if quantity == 0:
        return ZERO
    return None if amount is None else costs.money(amount * Decimal(before + quantity) / planned) - costs.money(amount * Decimal(before) / planned)


def calculate_partial(actor, batch, source, fingerprint, lines, revisions, batch_qty,
        goods_taxes, collection, freight, issues, payload, key, digest, *, automatic_inbound_id=None, fallback_reason=None):
    inbounds = list(InboundOrder.objects.filter(batch=batch, status='confirmed').order_by('pk'))
    receipts = list(InternalStockReceiptLine.objects.filter(receipt__inbound__in=inbounds,
        inbound_line__isnull=False).select_related('inbound_line', 'receipt').order_by('receipt__created_at', 'receipt_id', 'pk'))
    clearance = {}
    for inbound in inbounds:
        revision = revisions.get(('inbound', inbound.pk))
        if revision is None:
            issues.append(f'{inbound.number}：清货费用未维护；无费用时也需确认零。')
        clearance[inbound.pk] = ({line.pk: None for line in costs.source_lines('inbound', inbound)}
            if fallback_reason or revision is None else costs.fee_amounts('inbound', inbound, revision, issues))
    extra = InternalStockReceiptLine.objects.filter(receipt__inbound__in=inbounds, extra_line__isnull=False)
    if extra.exists():
        issues.append('存在额外实收商品，其货值尚未确认，未混入计划商品成本。')
    if not inbounds:
        issues.append('尚未确认实收，本次为发货阶段成本。')
    by_source = {}
    for receipt in receipts:
        by_source.setdefault(receipt.inbound_line.shipment_line_id, []).append(receipt)
    terminated = {}
    for item in source.get('shortage_terminations', []):
        if item['origin'] == 'final_shortage':
            pk = item['shipment_line_id']
            terminated[pk] = terminated.get(pk, 0) + item['quantity']
    entries, allocations, losses = [], [], []
    for line in lines:
        qty = batch_qty[line.pk]
        tax = goods_taxes.get(line.pk, ZERO)
        goods = None if line.unit_price is None else costs.money(line.unit_price * qty) + tax
        if goods is None:
            issues.append(f'{line.sku_code_snapshot}：实际采购价格未填写。')
        collect, transport = collection.get(line.pk, ZERO), freight.get(line.pk, ZERO)
        shipped = _sum((goods, collect, transport))
        consumed = actual = 0
        parts = []
        for receipt in by_source.get(line.pk, []):
            received = receipt.received_quantity
            used = min(received, receipt.inbound_line.expected_quantity)
            if consumed + used > qty:
                raise ValueError('Confirmed receipt consumption exceeds the dispatch allocation.')
            amounts = [released(value, consumed, used, qty) for value in (goods, collect, transport)]
            clear = clearance[receipt.receipt.inbound_id].get(line.pk, ZERO)
            total = _sum([*amounts, clear])
            part = dict(schema_version=2, receipt_line_id=receipt.pk, shipment_line_id=line.pk,
                inbound_id=receipt.receipt.inbound_id, sku_id=line.sku_id, warehouse_id=receipt.receipt.warehouse_id,
                actual_quantity=received, consumed_quantity=used,
                **{name: costs.text_number(value) for name, value in zip(COMPONENTS, [*amounts, clear, total])})
            parts.append(part)
            consumed += used
            actual += received
            if received > receipt.inbound_line.expected_quantity:
                issues.append(f'{line.sku_code_snapshot}：实收超发货（本次应收），额外货值尚需采购核对。')
        allocations.extend(parts)
        lost_qty = min(terminated.get(line.pk, 0), qty - consumed)
        loss = _sum(released(value, consumed, lost_qty, qty) for value in (goods, collect, transport))
        losses.append(loss)
        sums = {name: _sum(None if part[name] is None else Decimal(part[name]) for part in parts) for name in COMPONENTS}
        released_total = _sum(sums[name] for name in COMPONENTS[:3])
        pending = None if shipped is None or released_total is None or loss is None else shipped - released_total - loss
        entries.append(dict(shipment_line=line, receipt_line=None, quantity=qty,
            received_quantity=actual if inbounds else None, goods_amount=goods, goods_tax_amount=tax,
            collection_fee=collect, freight_fee=transport, shipped_total=shipped, pending_total=pending,
            **sums,
            shipped_unit_cost=None if shipped is None else (shipped / qty).quantize(costs.UNIT, rounding=ROUND_HALF_UP),
            received_unit_cost=None if not actual or sums['received_total'] is None else (sums['received_total'] / actual).quantize(costs.UNIT, rounding=ROUND_HALF_UP)))
    summary = dict(schema_version=2, receipt_cost_allocations=allocations,
        shipped_quantity=sum(item['quantity'] for item in entries),
        received_quantity=sum(item['received_quantity'] or 0 for item in entries) if inbounds else None,
        consumed_quantity=sum(item['consumed_quantity'] for item in allocations),
        shortage_loss=costs.text_number(_sum(losses)),
        aggregation_basis='batch planned quantities; confirmed physical receipts; per-receipt capped consumption')
    for name in ('shipped_total', 'received_total', 'pending_total', 'clearance_fee'):
        summary[name] = costs.text_number(_sum(item[name] for item in entries))
    if automatic_inbound_id is not None:
        summary['trigger_inbound_id'] = automatic_inbound_id
    prior = CostVersion.objects.filter(tenant=actor.tenant, batch=batch).order_by('-sequence').first()
    old = {item['receipt_line_id']: item for item in receipt_allocations(prior)} if prior else {}
    with domain_write():
        version = CostVersion.objects.create(tenant=actor.tenant, created_by=actor, batch=batch,
            sequence=prior.sequence + 1 if prior else 1, state='estimated' if issues else 'confirmed',
            stage='received' if inbounds else 'shipped', input_fingerprint=fingerprint,
            source_snapshot=source, summary=summary, issues=list(dict.fromkeys(issues)), creation_key=key, request_hash=digest)
        for item in entries:
            CostEntry.objects.create(tenant=actor.tenant, created_by=actor, cost_version=version, **item)
        for item in allocations:
            previous = old.get(item['receipt_line_id'])
            if previous and previous['received_total'] is not None and item['received_total'] is not None:
                before, after = Decimal(previous['received_total']), Decimal(item['received_total'])
                if before != after:
                    CostAdjustment.objects.create(tenant=actor.tenant, created_by=actor, previous_version=prior,
                        current_version=version, receipt_line_id=item['receipt_line_id'], previous_amount=before,
                        current_amount=after, delta=after-before)
        services._event(actor, batch, 'cost_calculated', key, payload,
            audit={'cost_version_id': version.pk, 'cost_sequence': version.sequence, 'input_fingerprint': fingerprint, 'summary': summary})
    if version.state == 'confirmed':
        from .product_cost_sync import publish_received_costs
        publish_received_costs(version, actor)
    return version


def reference_for_inbound(inbound):
    version = CostVersion.objects.filter(tenant_id=inbound.tenant_id, creation_key=f'auto-inbound-cost-{inbound.pk}').first()
    return None if version is None else costs.cost_data(version, detail=False)


def estimate_for_inbound(actor, inbound):
    key = f'auto-inbound-cost-{inbound.pk}'
    previous = CostVersion.objects.filter(tenant=actor.tenant, creation_key=key).first()
    if previous:
        return previous
    batch = inbound.batch
    batch.refresh_from_db()
    payload = {'expected_source_version': batch.version, 'expected_input_fingerprint': costs.inputs('batch', batch)[1]}
    try:
        with transaction.atomic():
            return costs.calculate(actor, 'batch', batch.pk, payload, key, automatic_inbound_id=inbound.pk)
    except Exception as exc:
        # The isolated savepoint rolls back strict remeasurement, while receipt facts survive.
        with transaction.atomic():
            return costs.calculate(actor, 'batch', batch.pk, payload, key,
                automatic_inbound_id=inbound.pk, _fallback_reason=f'{type(exc).__name__}: {exc}')


def estimate_for_batch_shortage(actor, batch, request_key):
    """Reflect explicit final shortage in provisional costs without changing payments."""
    key = 'auto-shortage-cost-' + str(batch.pk) + '-' + services.request_hash({'key':request_key})[:24]
    previous = CostVersion.objects.filter(tenant=actor.tenant,creation_key=key).first()
    if previous:
        return previous
    batch.refresh_from_db()
    payload={'expected_source_version':batch.version,'expected_input_fingerprint':costs.inputs('batch',batch)[1]}
    reason='最终未到货短缺已终止，自动更新暂估；差异金额仍需财务核对。'
    try:
        with transaction.atomic():
            return costs.calculate(actor,'batch',batch.pk,payload,key,automatic_reason=reason)
    except Exception as exc:
        with transaction.atomic():
            return costs.calculate(actor,'batch',batch.pk,payload,key,automatic_reason=reason,
                _fallback_reason=f'{type(exc).__name__}: {exc}')
