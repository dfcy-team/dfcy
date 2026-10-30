"""Procurement-only dispatch and source-preserving inbound commands.

Third-party inventory snapshots remain owned by their connectors. Local receipt
entries record confirmed inbound facts, never a fabricated external balance.
"""
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.masterdata.models import WarehouseMaster
from . import services, shipments, dispatch_allocations
from .dates import business_date
from .models import (DispatchBatch, DispatchMembership, FreightCompany, InboundOrder,
                     InternalStockReceipt, InternalStockReceiptLine, PurchaseOrder, SupplierShipment, domain_write)
from .permissions import MANAGE, VIEW, internal_orders


def batches_for(actor, permission=VIEW):
    orders = internal_orders(actor, PurchaseOrder.objects.all(), permission)
    # History includes removed members; it must never expose another scope's orders.
    denied = DispatchMembership.objects.filter(batch_id=OuterRef('pk')).exclude(shipment__order__in=orders)
    return DispatchBatch.objects.filter(tenant=actor.tenant).annotate(denied=Exists(denied)).filter(denied=False)


def batch_for(actor, pk, permission=MANAGE):
    obj = batches_for(actor, permission).filter(pk=pk).select_related('freight_company', 'planned_warehouse').first()
    if not obj:
        raise NotFound('集货批次不存在或不在授权范围。')
    return obj


@transaction.atomic
def confirm_inbound(actor, pk, payload, key):
    services._internal(actor)
    services._tenant_lock(actor)
    obj = inbound_for(actor, pk)
    if services._prior_event(actor, obj, 'inbound_confirmed', key, payload):
        return obj
    services._version(obj, payload['expected_version'])
    if obj.status != 'draft' or obj.stock_receipt_ref:
        raise ValidationError('入库已经确认，不能重复记账。')
    from .warehouse_archives import warehouse_refs
    warehouse = warehouse_refs(actor, MANAGE).filter(pk=obj.warehouse_id, status='active').first()
    if not warehouse:
        raise ValidationError('入库仓已停用或不在当前可选择的仓库范围内，请重新核对。')
    if warehouse.country_code.upper() != obj.batch.country_code_snapshot or obj.batch.stage != 'arrived_warehouse':
        raise ValidationError('批次必须到仓且仓库必须属于目的国家。')
    lines = list(obj.lines.select_related('shipment_line__shipment'))
    if not lines or any(line.received_quantity is None for line in lines):
        raise ValidationError('请逐行确认实收数量；未核对数量不能视为零。')
    source_quantities = dispatch_allocations.batch_quantities(obj.batch)
    for line in lines:
        if (not line.shipment_line.is_active
                or line.expected_quantity != source_quantities.get(line.shipment_line_id)):
            raise ValidationError('入库来源发生变化，请核对批次与发货明细。')
        if line.received_quantity != line.expected_quantity and not line.difference_note.strip():
            raise ValidationError('实收数量与应收不同，请填写差异原因。')
    with domain_write():
        receipt = InternalStockReceipt.objects.create(tenant=actor.tenant, created_by=actor,
            inbound=obj, warehouse=warehouse, receipt_ref=f'SC2-RECEIPT-{obj.pk}-{uuid4().hex[:12].upper()}')
        for line in lines:
            InternalStockReceiptLine.objects.create(tenant=actor.tenant, created_by=actor,
                receipt=receipt, inbound_line=line, sku=line.shipment_line.sku,
                sku_code_snapshot=line.shipment_line.sku_code_snapshot, received_quantity=line.received_quantity)
        obj.status = 'confirmed'
        obj.stock_receipt_ref, obj.confirmed_by, obj.confirmed_at = receipt.receipt_ref, actor, timezone.now()
        obj.version += 1
        obj.save()
        services._event(actor, obj, 'inbound_confirmed', key, payload, audit={
            'stock_receipt_ref': receipt.receipt_ref, 'warehouse_id': warehouse.pk,
            'received_lines': [{'inbound_line_id': l.pk, 'shipment_line_id': l.shipment_line_id,
                                'received_quantity': l.received_quantity, 'difference_note': l.difference_note} for l in lines]})
    return obj


def candidates(actor):
    orders = internal_orders(actor, PurchaseOrder.objects.all())
    from django.db.models import Sum, Subquery, F, Value
    from django.db.models.functions import Coalesce
    from .models import ShipmentLine
    used = dispatch_allocations.active().filter(shipment_line_id=OuterRef('pk')).values('shipment_line_id').annotate(total=Sum('quantity')).values('total')
    available = ShipmentLine.objects.filter(shipment_id=OuterRef('pk'), is_active=True).annotate(used=Coalesce(Subquery(used), Value(0))).filter(quantity__gt=F('used'))
    return SupplierShipment.objects.filter(tenant=actor.tenant, order__in=orders, status='submitted').annotate(has_remaining=Exists(available)).filter(has_remaining=True).select_related('order__supplier')


def batch_data(obj):
    prepared = getattr(obj, '_read_batch', None)
    members = prepared['members'] if prepared is not None else obj.memberships.filter(active_guard=True).select_related('shipment__order__supplier')
    shipment_data = [shipments.snapshot(m.shipment, internal=True) for m in members]
    quantities = prepared['quantities'] if prepared is not None else dispatch_allocations.batch_quantities(obj)
    for shipment in shipment_data:
        shipment['allocation_lines'] = [{**line, 'current_batch_quantity': quantities.get(line['id'], 0),
            'available_quantity': line['remaining_quantity'] + quantities.get(line['id'], 0)} for line in shipment['lines']]
        shipment['lines'] = [line for line in shipment['lines'] if line['id'] in quantities]
        for line in shipment['lines']:
            line['source_quantity'] = line['quantity']
            line['quantity'] = quantities[line['id']]
            line['current_batch_quantity'] = quantities[line['id']]
            line['available_quantity'] = line['remaining_quantity'] + line['quantity']
            line['image_preview_url'] = (f"/api/internal/supply-chain/v2/dispatch-batches/{obj.pk}/skus/{line['sku_id']}/image/"
                if (line.get('product_details') or {}).get('image_url') else '')
        shipment['total_quantity'] = sum(line['quantity'] for line in shipment['lines'])
    inbound = prepared['inbound'] if prepared is not None else InboundOrder.objects.filter(batch=obj).first()
    return {'id': obj.pk, 'number': obj.number, 'country_code': obj.country_code_snapshot,
            'supplier_names': ', '.join(sorted({m.shipment.order.supplier.name for m in members})),
            'freight_company_id': obj.freight_company_id, 'freight_company_name': obj.freight_company.name,
            'freight_number': obj.freight_number, 'shipping_marks': obj.shipping_marks_snapshot,
            'fee_per_cbm_snapshot': obj.fee_per_cbm_snapshot,
            'tax_percent_snapshot': obj.tax_percent_snapshot,
            'freight_channel_id': obj.freight_channel_id, 'freight_quote_id': obj.freight_quote_id,
            'freight_quote_snapshot': obj.freight_quote_snapshot, 'container_number': obj.container_number,
            'container_count': obj.container_count, 'planned_warehouse_id': obj.planned_warehouse_id,
            'expected_warehouse_date': obj.expected_warehouse_date,
            'planned_warehouse_name': obj.planned_warehouse.name if obj.planned_warehouse_id else '',
            'notes': obj.notes, 'version': obj.version, 'stage': obj.stage, 'status': obj.status,
            'logistics_dates': {field: getattr(obj, field) for field in ('departed_at', 'arrived_port_at', 'arrived_warehouse_at')},
            'shipment_ids': [m.shipment_id for m in members],
            'shipments': shipment_data,
            'inbound_id': inbound.pk if inbound else None}


def inbound_for(actor, pk, permission=MANAGE):
    obj = InboundOrder.objects.filter(tenant=actor.tenant, batch__in=batches_for(actor, permission), pk=pk).select_related('batch', 'batch__planned_warehouse', 'warehouse').first()
    if not obj:
        raise NotFound('入库单不存在或不在授权范围。')
    return obj


def inbound_data(obj):
    lines = list(obj.lines.select_related('shipment_line__sku__spu__category_node',
        'shipment_line__shipment__order__supplier'))
    from .supplier_products import shipment_line_product_details
    details = shipment_line_product_details([line.shipment_line for line in lines])
    return {'id': obj.pk, 'number': obj.number, 'batch_id': obj.batch_id, 'batch_number': obj.batch.number,
            'supplier_names': ', '.join(sorted({line.shipment_line.shipment.order.supplier.name for line in lines})),
            'country_code': obj.batch.country_code_snapshot, 'warehouse_id': obj.warehouse_id,
            'planned_warehouse_id': obj.batch.planned_warehouse_id,
            'planned_warehouse_name': obj.batch.planned_warehouse.name if obj.batch.planned_warehouse_id else '',
            'warehouse_name': obj.warehouse.name, 'status': obj.status, 'version': obj.version,
            'notes': obj.notes, 'stock_receipt_ref': obj.stock_receipt_ref, 'confirmed_at': obj.confirmed_at,
            'lines': [{'id': line.pk, 'shipment_line_id': line.shipment_line_id,
                       'shipment_number': line.shipment_line.shipment.number,
                       'order_number': line.shipment_line.shipment.order.number,
                       'supplier_name': line.shipment_line.shipment.order.supplier.name,
                       'sku': line.shipment_line.sku_code_snapshot, 'sku_id': line.shipment_line.sku_id,
                       'legacy_sku_code': line.shipment_line.sku.legacy_sku_code or '',
                       'product_details': {'image_url': details.get(line.shipment_line_id, {}).get('image_url', '')},
                       'image_preview_url': (f'/api/internal/supply-chain/v2/inbound-orders/{obj.pk}/skus/{line.shipment_line.sku_id}/image/'
                           if details.get(line.shipment_line_id, {}).get('image_url') else ''),
                       'product_name': line.shipment_line.product_name_snapshot,
                       'expected_quantity': line.expected_quantity, 'received_quantity': line.received_quantity,
                       'difference_note': line.difference_note} for line in lines]}


@transaction.atomic
def create_batch(actor, payload, key):
    services._internal(actor)
    services._tenant_lock(actor)
    previous = DispatchBatch.objects.filter(tenant=actor.tenant, creation_key=services._key(key)).first()
    if previous:
        batch_for(actor, previous.pk)
        return services._matching_replay(previous, services.request_hash(payload))
    versions = {row['id']: row['version'] for row in payload['shipment_versions']}
    ids = payload['shipment_ids']
    if len(set(ids)) != len(ids) or len(versions) != len(payload['shipment_versions']) or set(versions) != set(ids):
        raise ValidationError('每张已选发货单必须携带唯一的当前版本。')
    rows = list(services._internal_shipments(actor).filter(pk__in=ids))
    if len(rows) != len(ids):
        raise NotFound('所选发货单不存在或不在授权范围。')
    for row in rows:
        services._version(row, versions[row.pk])
    obj = services.create_dispatch_batch(actor, payload, idempotency_key=key)
    with domain_write():
        # Hash the client payload, not the generated number, for stable retries.
        obj.request_hash = services.request_hash(payload)
        obj.save()
        for row in rows:
            row.version += 1
            row.save()
            services._event(actor, row, 'dispatch_assigned', key, {'batch_id': obj.pk})
    return obj


@transaction.atomic
def update_batch(actor, pk, payload, key):
    services._internal(actor)
    services._tenant_lock(actor)
    obj = batch_for(actor, pk)
    if services._prior_event(actor, obj, 'metadata_updated', key, payload):
        return obj
    services._version(obj, payload['expected_version'])
    if obj.stage != 'unmarked' or obj.status != 'active':
        raise ValidationError('开船后不能通过本阶段修改货运信息。')
    snapshot_fields = ('freight_company_id', 'shipping_marks_snapshot', 'freight_channel_id', 'freight_quote_id',
                       'freight_quote_snapshot', 'fee_per_cbm_snapshot', 'tax_percent_snapshot', 'freight_number',
                       'container_number', 'container_count', 'planned_warehouse_id', 'expected_warehouse_date', 'notes')
    before = {field: getattr(obj, field) for field in snapshot_fields}
    with domain_write():
        carrier_changed = 'freight_company_id' in payload and payload['freight_company_id'] != obj.freight_company_id
        channel_id = payload.get('freight_channel_id', None if carrier_changed else obj.freight_channel_id)
        quote_id = payload.get('freight_quote_id', None if carrier_changed else obj.freight_quote_id)
        if carrier_changed or channel_id != obj.freight_channel_id or quote_id != obj.freight_quote_id:
            from .freight_channels import batch_freight_values
            carrier = services._master(FreightCompany, actor, payload.get('freight_company_id', obj.freight_company_id), is_active=True)
            if 'international' not in carrier.service_scopes:
                raise ValidationError('所选货运公司未启用国际货运服务范围。')
            for field, value in batch_freight_values(actor, carrier, obj.country_code_snapshot, channel_id, quote_id).items():
                setattr(obj, field, value)
        if 'planned_warehouse_id' in payload and payload['planned_warehouse_id'] != obj.planned_warehouse_id:
            from .warehouse_archives import warehouse_refs
            if obj.planned_warehouse_id and not payload.get('reason', '').strip():
                raise ValidationError('更换或取消计划目的仓需要填写原因。')
            planned = warehouse_refs(actor, MANAGE).filter(pk=payload['planned_warehouse_id'], status='active', country_code__iexact=obj.country_code_snapshot).first() if payload['planned_warehouse_id'] else None
            if payload['planned_warehouse_id'] and not planned:
                raise ValidationError('请选择该国家已启用且有权选择的计划仓库。')
            obj.planned_warehouse = planned
        if 'container_count' in payload and (type(payload['container_count']) is not int or not 1 <= payload['container_count'] <= 1000):
            raise ValidationError('货柜数量必须为 1 至 1000 的整数。')
        for field in ('freight_number', 'notes', 'container_number', 'container_count', 'expected_warehouse_date'):
            if field in payload:
                setattr(obj, field, payload[field])
        obj.version += 1
        obj.save()
        services._event(actor, obj, 'metadata_updated', key, payload, audit={
            'before': before, 'after': {field: getattr(obj, field) for field in snapshot_fields},
        })
    return obj


@transaction.atomic
def update_expected_warehouse_date(actor, pk, payload, key):
    services._internal(actor)
    services._tenant_lock(actor)
    obj = batch_for(actor, pk)
    if services._prior_event(actor, obj, 'expected_warehouse_date_updated', key, payload):
        return obj
    services._version(obj, payload['expected_version'])
    _reason(payload)
    if obj.status != 'active' or obj.stage == 'arrived_warehouse':
        raise ValidationError('仅有效且尚未到仓的批次可以维护预计到仓日期。')
    previous = obj.expected_warehouse_date
    if previous == payload.get('expected_warehouse_date'):
        raise ValidationError('预计到仓日期没有变化。')
    with domain_write():
        obj.expected_warehouse_date = payload.get('expected_warehouse_date')
        obj.version += 1
        obj.save()
        services._event(actor, obj, 'expected_warehouse_date_updated', key, payload, audit={
            'previous_expected_warehouse_date': previous,
            'current_expected_warehouse_date': obj.expected_warehouse_date,
        })
    return obj


def _editable_members(obj):
    if obj.status != 'active' or obj.stage != 'unmarked' or InboundOrder.objects.filter(batch=obj).exists():
        raise ValidationError('只有尚未开船的有效批次可以调整集货或取消。')


def _reason(payload):
    if not str(payload.get('reason', '')).strip():
        raise ValidationError('请填写本次调整原因。')


def _release(actor, obj, members, key):
    for member in members:
        member.active_guard = None
        member.version += 1
        member.save()
        row = member.shipment
        row.version += 1
        row.save()
        services._event(actor, row, 'dispatch_released', key, {'batch_id': obj.pk})


@transaction.atomic
def replace_members(actor, pk, payload, key):
    services._internal(actor)
    services._tenant_lock(actor)
    obj = batch_for(actor, pk)
    if services._prior_event(actor, obj, 'members_changed', key, payload):
        return obj
    services._version(obj, payload['expected_version'])
    _editable_members(obj)
    _reason(payload)
    ids = payload['shipment_ids']
    versions = {row['id']: row['version'] for row in payload['shipment_versions']}
    if not ids or len(set(ids)) != len(ids) or len(versions) != len(payload['shipment_versions']) or set(versions) != set(ids):
        raise ValidationError('每张已选发货单必须携带唯一的当前版本，批次不能为空。')
    rows = list(services._internal_shipments(actor).filter(pk__in=ids).select_related('order'))
    if len(rows) != len(ids):
        raise NotFound('所选发货单不存在或不在授权范围。')
    for row in rows:
        services._version(row, versions[row.pk])
        if row.status != 'submitted' or row.order.country_code_snapshot != obj.country_code_snapshot:
            raise ValidationError('只能选择同一目的国家的已提交发货单。')
    quantities = dispatch_allocations.resolve(rows, payload.get('allocations'), obj)
    members = list(obj.memberships.filter(active_guard=True).select_related('shipment'))
    previous_ids = {m.shipment_id for m in members}
    previous_quantities = dispatch_allocations.batch_quantities(obj)
    if previous_quantities == quantities:
        raise ValidationError('集货商品及数量未改变，无需保存。')
    with domain_write():
        _release(actor, obj, members, key)
        dispatch_allocations.reserve(actor, obj, rows, quantities)
        for row in rows:
            if row.pk not in previous_ids:
                row.version += 1
                row.save()
            services._event(actor, row, 'dispatch_assigned', key, {'batch_id': obj.pk, 'allocations': quantities})
        obj.version += 1
        obj.save()
        services._event(actor, obj, 'members_changed', key, payload,
                        audit={'previous_shipment_ids': sorted(previous_ids), 'current_shipment_ids': ids, 'previous_allocations': previous_quantities, 'allocations': quantities})
    return obj


@transaction.atomic
def cancel_batch(actor, pk, payload, key):
    services._internal(actor)
    services._tenant_lock(actor)
    obj = batch_for(actor, pk)
    if services._prior_event(actor, obj, 'batch_cancelled', key, payload):
        return obj
    services._version(obj, payload['expected_version'])
    _editable_members(obj)
    _reason(payload)
    members = list(obj.memberships.filter(active_guard=True).select_related('shipment'))
    with domain_write():
        _release(actor, obj, members, key)
        obj.status = 'cancelled'
        obj.version += 1
        obj.save()
        services._event(actor, obj, 'batch_cancelled', key, payload,
                        audit={'released_shipment_ids': [m.shipment_id for m in members]})
    return obj


@transaction.atomic
def correct_dates(actor, pk, payload, key):
    services._internal(actor)
    services._tenant_lock(actor)
    obj = batch_for(actor, pk)
    if services._prior_event(actor, obj, 'logistics_date_corrected', key, payload):
        return obj
    services._version(obj, payload['expected_version'])
    _reason(payload)
    fields = {'departed': 'departed_at', 'arrived_port': 'arrived_port_at', 'arrived_warehouse': 'arrived_warehouse_at'}
    field = fields.get(payload['stage'])
    occurred_at = payload['occurred_at']
    if obj.status != 'active' or not field or getattr(obj, field) is None:
        raise ValidationError('只能更正有效批次中已经记录的节点时间。')
    if timezone.is_naive(occurred_at):
        raise ValidationError('请使用包含时区的实际物流时间。')
    dates = [occurred_at if f == field else getattr(obj, f) for f in fields.values()]
    recorded = [d for d in dates if d is not None]
    if any(a > b for a, b in zip(recorded, recorded[1:])):
        raise ValidationError('更正后的开船、到港、到仓时间必须依次递增。')
    previous = getattr(obj, field)
    with domain_write():
        setattr(obj, field, occurred_at)
        obj.version += 1
        obj.save()
        services._event(actor, obj, 'logistics_date_corrected', key, payload,
                        audit={'previous_occurred_at': previous.isoformat(), 'current_stage': obj.stage})
    return obj


@transaction.atomic
def update_inbound(actor, pk, payload, key):
    services._internal(actor)
    services._tenant_lock(actor)
    obj = inbound_for(actor, pk)
    if services._prior_event(actor, obj, 'receipt_checked', key, payload):
        return obj
    services._version(obj, payload['expected_version'])
    if obj.status != 'draft':
        raise ValidationError('已入库单据不能回改收货数量或仓库。')
    from .warehouse_archives import warehouse_refs
    warehouse = warehouse_refs(actor, MANAGE).filter(pk=payload.get('warehouse_id', obj.warehouse_id), status='active', country_code__iexact=obj.batch.country_code_snapshot).first()
    if not warehouse:
        raise ValidationError('请选择目的国家对应且有权选择的有效仓库。')
    old_warehouse_id = obj.warehouse_id
    if warehouse.pk != old_warehouse_id and not payload.get('reason', '').strip():
        raise ValidationError('更换实际入库仓库需要填写改仓原因。')
    rows = payload.get('lines')
    saved = {line.pk: line for line in obj.lines.all()}
    if rows is not None:
        ids = [row['id'] for row in rows]
        if len(set(ids)) != len(ids) or set(ids) != set(saved):
            raise ValidationError('请核对全部入库来源行，不能增删或混入其他单据行。')
    with domain_write():
        for row in rows or []:
            line = saved[row['id']]
            qty = row['received_quantity']
            reason = row.get('difference_note', '')
            if qty is not None and qty != line.expected_quantity and not reason.strip():
                raise ValidationError('实收数量与应收不同，请填写差异原因。')
            line.received_quantity, line.difference_note = qty, reason
            line.version += 1
            line.save()
        obj.warehouse = warehouse
        obj.notes = payload.get('notes', obj.notes)
        obj.version += 1
        obj.save()
        services._event(actor, obj, 'receipt_checked', key, payload, audit={'old_warehouse_id': old_warehouse_id, 'new_warehouse_id': warehouse.pk})
    return obj
