"""Source quantities for manual partial receipts and explicit final shortages."""
from collections import defaultdict
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum

from .models import (InboundOrder, InboundLine, ShipmentLine, DispatchBatch,
                     InboundShortageTermination, domain_write)
from . import dispatch_allocations


def consumed_quantity(line):
    return min(max(int(line.received_quantity or 0), 0), int(line.expected_quantity))


def quantities(batch, *, exclude_draft_id=None):
    cached = getattr(batch, '_manual_progress_context', None)
    if cached is not None and exclude_draft_id is None:
        return cached['quantities']
    planned = dispatch_allocations.batch_quantities(batch)
    received, consumed, reserved, terminated = (defaultdict(int) for _ in range(4))
    query = InboundLine.objects.filter(inbound__batch_id=batch.pk).exclude(inbound__status='cancelled').select_related('inbound')
    for line in query:
        if line.inbound.status == 'confirmed':
            received[line.shipment_line_id] += int(line.received_quantity or 0)
            consumed[line.shipment_line_id] += consumed_quantity(line)
        elif line.inbound.status == 'draft' and line.inbound_id != exclude_draft_id:
            reserved[line.shipment_line_id] += line.expected_quantity
    for row in InboundShortageTermination.objects.filter(batch_id=batch.pk).values('shipment_line_id').annotate(total=Sum('quantity')):
        terminated[row['shipment_line_id']] = row['total']
    return planned, received, consumed, reserved, terminated


def progress(batch):
    planned, received, consumed, reserved, terminated = quantities(batch)
    cached = getattr(batch, '_manual_progress_context', None)
    sources = cached['sources'] if cached is not None else list(ShipmentLine.objects.filter(pk__in=planned).select_related('shipment', 'sku').order_by('shipment_id', 'pk'))
    candidates = []
    for line in sources:
        remaining = max(0, planned[line.pk] - consumed[line.pk] - terminated[line.pk])
        available = max(0, remaining - reserved[line.pk])
        candidates.append({'shipment_line_id': line.pk, 'shipment_id': line.shipment_id,
            'sku_id': line.sku_id,
            'shipment_number': line.shipment.number, 'sku': line.sku_code_snapshot,
            'legacy_sku_code': line.sku.legacy_sku_code or '', 'product_name': line.product_name_snapshot,
            'allocated_quantity': planned[line.pk], 'received_quantity': received[line.pk],
            'fulfilled_quantity': consumed[line.pk], 'reserved_quantity': reserved[line.pk],
            'remaining_quantity': remaining, 'available_quantity': available,
            'shortage_terminated_quantity': terminated[line.pk]})
    header = {'planned_quantity': sum(planned.values()), 'received_quantity': sum(received.values()),
        'fulfilled_quantity': sum(consumed.values()), 'reserved_quantity': sum(reserved.values()),
        'remaining_quantity': sum(r['remaining_quantity'] for r in candidates),
        'available_quantity': sum(r['available_quantity'] for r in candidates),
        'shortage_terminated_quantity': sum(terminated.values())}
    header['closed'] = bool(planned) and header['remaining_quantity'] == 0
    docs = cached['docs'] if cached is not None else list(InboundOrder.objects.filter(batch_id=batch.pk).select_related('warehouse').order_by('pk'))
    inbounds = [{'id': doc.pk, 'number': doc.number, 'status': doc.status,
        'warehouse_id': doc.warehouse_id, 'warehouse_name': doc.warehouse.name,
        'version': doc.version, 'receipt_mode': doc.receipt_mode} for doc in docs]
    return {'inbound_progress': header, 'inbound_candidates': candidates, 'inbounds': inbounds}


def prepare_progress(batches, planned_by_batch):
    """List views use four scoped reads rather than four reads for every batch."""
    if not batches:
        return
    ids = [batch.pk for batch in batches]
    tenant_ids = {batch.tenant_id for batch in batches}
    context = {batch.pk: {'quantities': (planned_by_batch[batch.pk], *(defaultdict(int) for _ in range(4))),
        'sources': [], 'docs': []} for batch in batches}
    source_batches = defaultdict(list)
    for batch in batches:
        for source_id in planned_by_batch[batch.pk]:
            source_batches[source_id].append(batch.pk)
    for source in ShipmentLine.objects.filter(tenant_id__in=tenant_ids, pk__in=source_batches).select_related('shipment', 'sku').order_by('shipment_id', 'pk'):
        for batch_id in source_batches[source.pk]:
            context[batch_id]['sources'].append(source)
    for line in InboundLine.objects.filter(tenant_id__in=tenant_ids, inbound__batch_id__in=ids).exclude(inbound__status='cancelled').select_related('inbound'):
        _, received, consumed, reserved, _ = context[line.inbound.batch_id]['quantities']
        if line.inbound.status == 'confirmed':
            received[line.shipment_line_id] += int(line.received_quantity or 0)
            consumed[line.shipment_line_id] += consumed_quantity(line)
        elif line.inbound.status == 'draft':
            reserved[line.shipment_line_id] += line.expected_quantity
    for row in InboundShortageTermination.objects.filter(tenant_id__in=tenant_ids, batch_id__in=ids).values('batch_id', 'shipment_line_id').annotate(total=Sum('quantity')):
        context[row['batch_id']]['quantities'][4][row['shipment_line_id']] = row['total']
    for doc in InboundOrder.objects.filter(tenant_id__in=tenant_ids, batch_id__in=ids).select_related('warehouse').order_by('pk'):
        context[doc.batch_id]['docs'].append(doc)
    for batch in batches:
        batch._manual_progress_context = context[batch.pk]


def _normalize_lines(lines):
    if not isinstance(lines, list) or not lines:
        raise ValidationError('请选择本次入库商品并填写数量，不能自动生成整批入库单。')
    normalized, seen = [], set()
    for row in lines:
        if not isinstance(row, dict):
            raise ValidationError('入库商品格式不正确。')
        pk, qty = row.get('shipment_line_id'), row.get('quantity')
        if isinstance(pk, bool) or not isinstance(pk, int) or isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0 or pk in seen:
            raise ValidationError('入库商品不得重复，数量须为正整数。')
        seen.add(pk); normalized.append({'shipment_line_id': pk, 'quantity': qty})
    return sorted(normalized, key=lambda row: row['shipment_line_id'])


@transaction.atomic
def create_manual_inbound(actor, batch_id, *, warehouse_id, expected_version, idempotency_key,
                          lines, reason='', notes=''):
    from . import logistics, services
    from .numbering import number_for
    from .warehouse_archives import warehouse_refs
    from .permissions import MANAGE
    services._internal(actor); services._tenant_lock(actor)
    permitted = logistics.batch_for(actor, batch_id, MANAGE)
    batch = DispatchBatch.objects.select_for_update().get(pk=permitted.pk, tenant_id=actor.tenant_id)
    normalized = _normalize_lines(lines)
    selected_warehouse = warehouse_id or batch.planned_warehouse_id
    payload = {'expected_version': expected_version, 'warehouse_id': selected_warehouse,
        'lines': normalized, 'reason': str(reason or '').strip(), 'notes': str(notes or '').strip()}
    event = services._prior_event(actor, batch, 'inbound_created', idempotency_key, payload)
    if event:
        return InboundOrder.objects.get(tenant_id=actor.tenant_id, pk=event.payload['inbound_id'], batch=batch)
    services._version(batch, expected_version)
    if batch.status != 'active' or batch.stage != 'arrived_warehouse':
        raise ValidationError('只有已到仓的有效发运批次可新建入库单。')
    warehouse = warehouse_refs(actor, MANAGE).filter(pk=selected_warehouse, status='active',
        country_code__iexact=batch.country_code_snapshot).first()
    if warehouse is None:
        raise ValidationError('请选择目的国家已启用且有权选择的仓库。')
    if batch.planned_warehouse_id and warehouse.pk != batch.planned_warehouse_id and not payload['reason']:
        raise ValidationError('实际入库仓与计划目的仓不同，请填写改仓原因。')
    planned, received, consumed, reserved, terminated = quantities(batch)
    source_ids = {row['shipment_line_id'] for row in normalized}
    sources = {line.pk: line for line in ShipmentLine.objects.filter(pk__in=source_ids, is_active=True)}
    if source_ids != set(sources) or not source_ids.issubset(planned):
        raise ValidationError('入库商品必须来自本发运批次的有效发货明细。')
    for row in normalized:
        pk = row['shipment_line_id']
        available = max(0, planned[pk] - consumed[pk] - reserved[pk] - terminated[pk])
        if row['quantity'] > available:
            raise ValidationError(f'{sources[pk].sku_code_snapshot}：本次数量超过剩余可入库数量 {available}，请刷新。')
    with domain_write():
        key = 'IN-' + str(batch.pk) + '-' + services.request_hash({'key': services._key(idempotency_key)})[:24]
        inbound = InboundOrder.objects.create(tenant=actor.tenant, created_by=actor,
            number=number_for(actor, 'inbound_order', key, batch.country_code_snapshot), batch=batch,
            warehouse=warehouse, receipt_mode='manual_partial', notes=payload['notes'])
        for row in normalized:
            InboundLine.objects.create(tenant=actor.tenant, created_by=actor, inbound=inbound,
                shipment_line=sources[row['shipment_line_id']], expected_quantity=row['quantity'])
        batch.version += 1; batch.save()
        services._event(actor, batch, 'inbound_created', idempotency_key, payload,
            audit={'inbound_id': inbound.pk, 'inbound_number': inbound.number})
    return inbound


def validate_confirmation(inbound):
    """Caller holds tenant lock; current draft must still fit its source plan."""
    planned, received, consumed, reserved, terminated = quantities(inbound.batch, exclude_draft_id=inbound.pk)
    rows = list(inbound.lines.select_related('shipment_line__shipment'))
    for row in rows:
        pk = row.shipment_line_id
        available = planned.get(pk, 0) - consumed[pk] - reserved[pk] - terminated[pk]
        if not row.shipment_line.is_active or row.expected_quantity <= 0 or row.expected_quantity > available:
            raise ValidationError('入库来源或可入库数量已变化，请核对发运批次。')
    return rows


def preserve_legacy_shortage(inbound, actor):
    """Only explicit trusted legacy-full receipts retain old close-on-count behavior."""
    if inbound.receipt_mode != 'legacy_full' or inbound.status != 'confirmed':
        return
    for row in inbound.lines.select_related('shipment_line__purchase_line', 'shipment_line__shipment'):
        quantity = max(0, row.expected_quantity - int(row.received_quantity or 0))
        if not quantity:
            continue
        source = row.shipment_line
        order_id = source.purchase_line.order_id if source.purchase_line_id else source.shipment.order_id
        key = f'legacy-inbound-{inbound.pk}'
        if InboundShortageTermination.objects.filter(tenant_id=inbound.tenant_id,request_key=key,batch_id=inbound.batch_id,shipment_line_id=source.pk).exists():
            continue
        with domain_write():
            InboundShortageTermination.objects.create(tenant_id=inbound.tenant_id,created_by=actor,
                purchase_order_id=order_id,batch_id=inbound.batch_id,shipment_line=source,quantity=quantity,
                reason=row.difference_note or '保留历史整批入库已结案口径',request_key=key,origin='legacy_closed')
