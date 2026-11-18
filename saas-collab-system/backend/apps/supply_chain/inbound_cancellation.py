"""Audited cancellation for draft inbound orders without downstream effects."""
from django.core.exceptions import ValidationError
from django.db import transaction

from . import logistics, services
from .models import (BusinessEvent, FeeRecord, InboundNotificationOutbox,
                     InternalStockReceipt, PaymentRecord, PaymentTermsRecord,
                     InboundOrder, domain_write)


@transaction.atomic
def cancel_inbound(actor, pk, payload, key):
    """Cancel a draft inbound while preserving all source/count history."""
    services._internal(actor)
    services._tenant_lock(actor)
    inbound = logistics.inbound_for(actor, pk)
    inbound = InboundOrder.objects.select_for_update().get(pk=inbound.pk, tenant_id=actor.tenant_id)
    normalized = {"expected_version": payload.get("expected_version"),
                  "reason": (payload.get("reason") or "").strip()}
    prior = BusinessEvent.objects.filter(tenant_id=actor.tenant_id,
        aggregate_type="inboundorder", aggregate_id=inbound.pk,
        action="inbound_cancelled", request_key=services._key(key)).first()
    if prior:
        services._matching_replay(prior, services.request_hash(normalized))
        return inbound
    services._version(inbound, normalized["expected_version"])
    if not normalized["reason"]:
        raise ValidationError({"reason": "作废原因不能为空。"})
    if inbound.status != InboundOrder.Status.DRAFT:
        raise ValidationError("只能作废待核对的入库单。")
    if inbound.stock_receipt_ref or InternalStockReceipt.objects.filter(inbound_id=inbound.pk).exists():
        raise ValidationError("已有库存入库凭证，不能作废。")
    if (FeeRecord.objects.filter(inbound_id=inbound.pk).exists()
            or PaymentRecord.objects.filter(inbound_id=inbound.pk).exists()
            or PaymentTermsRecord.objects.filter(inbound_id=inbound.pk).exists()):
        raise ValidationError("入库单已有费用或付款关联，不能作废。")
    if InboundNotificationOutbox.objects.filter(inbound_id=inbound.pk).exists():
        raise ValidationError("入库单已有通知记录，不能作废。")
    with domain_write():
        inbound.status = InboundOrder.Status.CANCELLED
        inbound.version += 1
        inbound.save()
        inbound.batch.version += 1
        inbound.batch.save()
        services._event(actor, inbound, "inbound_cancelled", key, normalized)
    return inbound
