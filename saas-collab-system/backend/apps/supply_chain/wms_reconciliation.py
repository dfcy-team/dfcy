"""Audited, quantity-only links between confirmed local receipts and WMS facts."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from rest_framework.exceptions import NotFound, PermissionDenied

from apps.commerce.models import InboundRecord
from apps.permissions.services import check_user_permission
from apps.sales_management.scopes import filter_inventory_queryset
from . import logistics, services
from .models import BusinessEvent, InternalStockReceiptLine, WmsReceiptAllocation, domain_write
from .permissions import MANAGE


def _wms_access(actor):
    if not check_user_permission(actor, 'sales_management.view'):
        raise PermissionDenied('需要 sales_management.view 才能读取 WMS 入库事实。')
    return filter_inventory_queryset(actor, 'sales_management.view', InboundRecord.objects.filter(tenant_id=actor.tenant_id))


def _eligible_wms(rows):
    return rows.filter(source_run__status='success', source_run__failed_count=0,
        source_run__sync_job__resource_type='inbound',
        source_run__sync_job__integration_config__platform='jifeng_wms')


def _line_for(actor, inbound, line_id):
    inbound_line = inbound.lines.select_related('shipment_line__sku', 'inbound__batch').filter(pk=line_id).first()
    if not inbound_line:
        raise NotFound('本地入库行不可访问。')
    if inbound.status != 'confirmed':
        raise ValidationError('仅已确认入库行可与 WMS 实收关联。')
    try:
        return inbound_line.stock_entry
    except InternalStockReceiptLine.DoesNotExist as exc:
        raise ValidationError('本地入库行缺少已确认的实收记录。') from exc


def _wms_data(row, linked=0):
    return {'id': row.pk, 'external_inbound_id': row.external_inbound_id,
        'external_line_id': row.external_line_id, 'site_code': row.site_code,
        'warehouse_id': row.warehouse_id, 'sku_id': row.internal_sku_id,
        'source_sku': row.source_sku, 'received_quantity': row.received_quantity,
        'allocated_quantity': linked, 'remaining_quantity': max(0, row.received_quantity - linked),
        'received_at_utc': row.received_at_utc}


def _matches(local, wms):
    inbound = local.receipt.inbound
    return (wms.tenant_id == local.tenant_id and wms.internal_sku_id == local.sku_id and
        wms.warehouse_id == local.receipt.warehouse_id and
        wms.site_code.upper() == inbound.batch.country_code_snapshot.upper())


def _active_for_local(local):
    return WmsReceiptAllocation.objects.filter(tenant_id=local.tenant_id, receipt_line=local, is_active=True)


def reconcile_data(actor, inbound, line_id=None):
    if inbound.status != 'confirmed':
        raise ValidationError('仅已确认入库单可查看 WMS 对账。')
    local_lines = inbound.stock_receipt.lines.select_related('receipt__inbound__batch', 'sku')
    if line_id:
        local_lines = local_lines.filter(pk=line_id)
    visible_wms = _eligible_wms(_wms_access(actor))
    results = []
    for local in local_lines.order_by('pk'):
        allocations = list(_active_for_local(local).select_related('wms_line__source_run__sync_job__integration_config'))
        rows = []
        for allocation in allocations:
            wms = visible_wms.filter(pk=allocation.wms_line_id).first()
            totals = WmsReceiptAllocation.objects.filter(tenant_id=actor.tenant_id,
                wms_line_id=allocation.wms_line_id, is_active=True).aggregate(total=Sum('quantity'))['total'] or 0
            good = bool(wms and _matches(local, wms) and totals <= wms.received_quantity)
            rows.append({'id': allocation.pk, 'version': allocation.version, 'quantity': allocation.quantity,
                'status': 'matched' if good else 'needs_review',
                'wms_line': _wms_data(wms, totals) if wms and _matches(local, wms) else None})
        active_total = sum(a['quantity'] for a in rows)
        valid_total = sum(a['quantity'] for a in rows if a['status'] == 'matched')
        results.append({'inbound_line_id': local.inbound_line_id, 'receipt_line_id': local.pk, 'sku': local.sku_code_snapshot,
            'sku_id': local.sku_id, 'warehouse_id': local.receipt.warehouse_id,
            'local_received_quantity': local.received_quantity,
            'allocated_quantity': active_total, 'valid_quantity': valid_total,
            'remaining_quantity': max(0, local.received_quantity - active_total),
            'allocations': rows})
    return results


def candidates(actor, inbound, line_id, search=''):
    logistics.inbound_for(actor, inbound.pk, 'supply.v2.view')
    local = _line_for(actor, inbound, line_id)
    rows = _eligible_wms(_wms_access(actor)).filter(site_code__iexact=inbound.batch.country_code_snapshot,
        warehouse_id=local.receipt.warehouse_id, internal_sku_id=local.sku_id)
    if search:
        from django.db.models import Q
        rows = rows.filter(Q(external_inbound_id__icontains=search) | Q(external_line_id__icontains=search) | Q(source_sku__icontains=search))
    existing = dict(WmsReceiptAllocation.objects.filter(tenant_id=actor.tenant_id, is_active=True,
        wms_line_id__in=rows.values('pk')).values('wms_line_id').annotate(total=Sum('quantity')).values_list('wms_line_id', 'total'))
    return [_wms_data(row, existing.get(row.pk, 0)) for row in rows.select_related('source_run').order_by('-received_at_utc', '-pk')[:100]]


@transaction.atomic
def allocate(actor, inbound, payload, key):
    services._internal(actor)
    services._tenant_lock(actor)
    inbound = logistics.inbound_for(actor, inbound.pk, MANAGE)
    line = _line_for(actor, inbound, payload['inbound_line_id'])
    digest, key = services.request_hash(payload), services._key(key)
    previous = WmsReceiptAllocation.objects.filter(tenant_id=actor.tenant_id, creation_key=key).first()
    if previous:
        services._matching_replay(previous, digest)
        return previous
    wms = _eligible_wms(_wms_access(actor)).select_for_update().filter(pk=payload['wms_line_id']).first()
    if not wms:
        raise NotFound('WMS 入库行不存在或不在当前库存数据范围。')
    if not _matches(line, wms):
        raise ValidationError('WMS 行的国家、仓库和 SKU 必须与本地入库行一致。')
    quantity = payload['quantity']
    if type(quantity) is not int or quantity <= 0:
        raise ValidationError('关联数量必须是正整数。')
    local_used = _active_for_local(line).aggregate(total=Sum('quantity'))['total'] or 0
    wms_used = WmsReceiptAllocation.objects.filter(tenant_id=actor.tenant_id,
        wms_line=wms, is_active=True).aggregate(total=Sum('quantity'))['total'] or 0
    if local_used + quantity > line.received_quantity:
        raise ValidationError('关联数量超过本地实收剩余量。')
    if wms_used + quantity > wms.received_quantity:
        raise ValidationError('关联数量超过 WMS 实收剩余量。')
    with domain_write():
        row = WmsReceiptAllocation(tenant=actor.tenant, created_by=actor, receipt_line=line,
            wms_line=wms, quantity=quantity, notes=payload.get('notes', ''), is_active=True,
            creation_key=key, request_hash=digest)
        row.save()
        BusinessEvent.objects.create(tenant=actor.tenant, created_by=actor,
            aggregate_type='wmsreceiptallocation', aggregate_id=row.pk, aggregate_version=row.version,
            action='created', request_key=key, request_hash=digest,
            payload={'receipt_line_id': line.pk, 'wms_line_id': wms.pk, 'quantity': quantity, 'notes': row.notes})
    return row


@transaction.atomic
def deactivate(actor, inbound, allocation_id, payload, key):
    services._internal(actor)
    services._tenant_lock(actor)
    inbound = logistics.inbound_for(actor, inbound.pk, MANAGE)
    allocation = WmsReceiptAllocation.objects.filter(tenant_id=actor.tenant_id,
        receipt_line__receipt__inbound=inbound, pk=allocation_id).first()
    if not allocation:
        raise NotFound('WMS 关联记录不可访问。')
    key, digest = services._key(key), services.request_hash(payload)
    previous = BusinessEvent.objects.filter(tenant_id=actor.tenant_id, aggregate_type='wmsreceiptallocation',
        aggregate_id=allocation.pk, action='deactivated', request_key=key).first()
    if previous:
        services._matching_replay(previous, digest)
        return allocation
    services._version(allocation, payload['expected_version'])
    if not payload.get('reason', '').strip():
        raise ValidationError('解除 WMS 关联必须填写原因。')
    if not allocation.is_active:
        raise ValidationError('该 WMS 关联已经解除。')
    with domain_write():
        allocation.is_active = False
        allocation.version += 1
        allocation.save()
        BusinessEvent.objects.create(tenant=actor.tenant, created_by=actor,
            aggregate_type='wmsreceiptallocation', aggregate_id=allocation.pk, aggregate_version=allocation.version,
            action='deactivated', request_key=key, request_hash=digest,
            payload={'reason': payload['reason'].strip(), 'quantity': allocation.quantity,
                'receipt_line_id': allocation.receipt_line_id, 'wms_line_id': allocation.wms_line_id})
    return allocation
