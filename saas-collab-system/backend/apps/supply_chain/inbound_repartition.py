"""Audited, explicit correction of an untouched draft into shipment-specific drafts."""
from django.core.exceptions import ValidationError
from django.db import transaction

from . import logistics, services
from .models import (BusinessEvent, CostVersion, FeeRecord, InboundNotificationOutbox,
    InboundOrder, InternalStockReceipt, PaymentRecord, PaymentTermsRecord, domain_write)


@transaction.atomic
def restore_and_split_by_shipment(actor, pk, *, expected_version, reason, key):
    """Retain the original number and all line IDs; never post stock or money."""
    from .numbering import number_for
    from .permissions import MANAGE
    from .inbound_split import quantities
    services._internal(actor)
    services._tenant_lock(actor)
    permitted = logistics.inbound_for(actor, pk, MANAGE)
    inbound = InboundOrder.objects.select_for_update().get(pk=permitted.pk, tenant_id=actor.tenant_id)
    batch = logistics.batch_for(actor, inbound.batch_id, MANAGE)
    payload = {'expected_version': expected_version, 'reason': str(reason or '').strip()}
    prior = services._prior_event(actor, inbound, 'inbound_restored_split', key, payload)
    if prior:
        return list(InboundOrder.objects.filter(tenant_id=actor.tenant_id,
            pk__in=prior.payload['inbound_ids']).order_by('pk'))
    services._version(inbound, expected_version)
    if not payload['reason'] or inbound.status not in ('draft', 'cancelled'):
        raise ValidationError('只能拆分未入库的草稿或无后续业务的已作废单，且必须填写原因。')
    if batch.status != 'active' or batch.stage != 'arrived_warehouse':
        raise ValidationError('批次必须有效且已到仓。')
    if (inbound.stock_receipt_ref or inbound.confirmed_at or
        InternalStockReceipt.objects.filter(inbound=inbound).exists() or
        FeeRecord.objects.filter(inbound=inbound).exists() or
        PaymentRecord.objects.filter(inbound=inbound).exists() or
        PaymentTermsRecord.objects.filter(inbound=inbound).exists() or
        InboundNotificationOutbox.objects.filter(inbound=inbound).exists() or
        CostVersion.objects.filter(batch_id=batch.pk).exists() or inbound.extra_lines.exists()):
        raise ValidationError('单据已有实收、成本、费用、付款或通知关联，不能恢复拆分。')
    rows = list(inbound.lines.select_related('shipment_line__shipment').order_by('shipment_line__shipment_id', 'pk'))
    groups = {}
    for row in rows:
        if row.received_quantity is not None or row.difference_note:
            raise ValidationError('单据已有核对记录，不能直接拆分。')
        groups.setdefault(row.shipment_line.shipment_id, []).append(row)
    if len(groups) != 2:
        raise ValidationError('本次修正要求恰好两张发货单。')
    planned, _, consumed, reserved, terminated = quantities(batch, exclude_draft_id=inbound.pk)
    for row in rows:
        source_id = row.shipment_line_id
        if (not row.shipment_line.is_active or row.shipment_line.shipment.status != 'submitted'
            or row.expected_quantity <= 0 or row.expected_quantity >
            planned.get(source_id, 0) - consumed[source_id] - reserved[source_id] - terminated[source_id]):
            raise ValidationError('来源或剩余数量已变化，停止拆分。')
    old_status = inbound.status
    with domain_write():
        new = InboundOrder.objects.create(tenant=actor.tenant, created_by=actor,
            number=number_for(actor, 'inbound_order', 'split-' + str(inbound.pk) + '-' +
                services.request_hash({'key': services._key(key)})[:24], batch.country_code_snapshot),
            batch=batch, warehouse=inbound.warehouse, receipt_mode='manual_partial',
            notes=f'由 {inbound.number} 按发货单拆分；{payload["reason"]}')
        moved = list(groups.values())[1]
        for row in moved:
            row.inbound = new
            row.version += 1
            row.save()
        inbound.status = 'draft'
        inbound.receipt_mode = 'manual_partial'
        inbound.version += 1
        inbound.save()
        batch.version += 1
        batch.save()
        audit = {'previous_status': old_status, 'inbound_ids': [inbound.pk, new.pk],
            'new_number': new.number, 'moved_line_ids': [r.pk for r in moved],
            'shipment_ids': list(groups)}
        services._event(actor, inbound, 'inbound_restored_split', key, payload, audit=audit)
        services._event(actor, new, 'inbound_created_by_split', key, payload,
            audit={'original_inbound_id': inbound.pk, 'line_ids': [r.pk for r in moved]})
        services._event(actor, batch, 'inbound_repartitioned', key, payload, audit=audit)
    return [inbound, new]
