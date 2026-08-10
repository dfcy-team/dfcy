import hashlib
import json

from django.db import IntegrityError, transaction
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit.services import write_operation_log

from .models import (
    FulfillmentStatusEvent,
    Influencer,
    InfluencerRestriction,
    OutreachTask,
    SampleFulfillment,
    SampleItem,
    SkuPriceSnapshot,
)


def _payload_hash(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _audit(user, action, object_type, instance, before=None, after=None):
    write_operation_log(
        tenant=user.tenant,
        user=user,
        module="influencers",
        action=action,
        object_type=object_type,
        object_id=instance.pk,
        before_data=before or {},
        after_data=after or {},
    )


def _save(instance):
    try:
        instance.save()
    except DjangoValidationError as exc:
        raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages) from exc


@transaction.atomic
def create_outreach_task(*, user, validated_data):
    task = OutreachTask(tenant=user.tenant, dispatcher=user, **validated_data)
    _save(task)
    _audit(user, "outreach_create", "outreach_task", task, after={"task_no": task.task_no, "status": task.status})
    return task


@transaction.atomic
def transition_outreach_task(*, user, task, status, expected_version):
    task = OutreachTask.objects.select_for_update().get(pk=task.pk, tenant=user.tenant)
    if task.version != expected_version:
        raise ValidationError({"version": "Task was changed by another request."}, code="conflict")
    if status not in OutreachTask.Status.values:
        raise ValidationError({"status": "Unsupported task status."})
    allowed = {
        OutreachTask.Status.PENDING: {OutreachTask.Status.IN_PROGRESS, OutreachTask.Status.CANCELLED},
        OutreachTask.Status.IN_PROGRESS: {OutreachTask.Status.COMPLETED, OutreachTask.Status.CANCELLED},
        OutreachTask.Status.COMPLETED: set(),
        OutreachTask.Status.CANCELLED: set(),
    }
    if status not in allowed[task.status]:
        raise ValidationError({"status": f"Transition from {task.status} to {status} is not allowed."})
    before = {"status": task.status, "version": task.version}
    now = timezone.now()
    if status == OutreachTask.Status.IN_PROGRESS and task.started_at is None:
        task.started_at = now
    if status in {OutreachTask.Status.COMPLETED, OutreachTask.Status.CANCELLED}:
        task.finalized_at = now
    task.status = status
    task.version += 1
    _save(task)
    _audit(user, "outreach_status", "outreach_task", task, before=before, after={"status": task.status, "version": task.version})
    return task


def _price_for_item(tenant, store_id, payload):
    sku = str(payload.get("requested_sku") or "").strip()
    product_id = str(payload.get("external_product_id") or "").strip()
    site_code = str(payload.get("site_code") or "").strip()
    if not sku:
        return None
    queryset = SkuPriceSnapshot.objects.select_related("listing").filter(
        tenant=tenant,
        listing__store_id=store_id,
        listing__site_code=site_code,
        external_sku__iexact=sku,
    )
    if product_id:
        queryset = queryset.filter(listing__external_product_id=product_id)
    return queryset.order_by("-source_updated_at", "-imported_at", "-id").first()


@transaction.atomic
def create_sample_fulfillment(*, user, request_key, validated_data, item_payloads):
    request_hash = _payload_hash({"fulfillment": validated_data, "items": item_payloads})
    existing = SampleFulfillment.objects.filter(tenant=user.tenant, request_key=request_key).first()
    if existing:
        if existing.request_hash != request_hash:
            raise ValidationError({"idempotency_key": "Key was already used with a different payload."}, code="conflict")
        return existing, False

    influencer = Influencer.objects.select_for_update().get(
        pk=validated_data["influencer"].pk,
        tenant=user.tenant,
    )
    validated_data["influencer"] = influencer
    if InfluencerRestriction.objects.filter(tenant=user.tenant, influencer=influencer, is_blacklisted=True).exists():
        raise ValidationError({"influencer": "Blacklisted influencers cannot receive samples."})

    fulfillment = SampleFulfillment(
        tenant=user.tenant,
        request_key=request_key,
        request_hash=request_hash,
        **validated_data,
    )
    try:
        with transaction.atomic():
            _save(fulfillment)
    except IntegrityError:
        existing = SampleFulfillment.objects.select_for_update().get(tenant=user.tenant, request_key=request_key)
        if existing.request_hash != request_hash:
            raise ValidationError({"idempotency_key": "Key was already used with a different payload."}, code="conflict")
        return existing, False

    for payload in item_payloads:
        snapshot = _price_for_item(user.tenant, fulfillment.store_id, payload)
        item = SampleItem(
            tenant=user.tenant,
            fulfillment=fulfillment,
            unit_price=snapshot.effective_price if snapshot else None,
            unit_cost=snapshot.inbound_cost if snapshot else None,
            currency=snapshot.currency if snapshot else "",
            price_match_status="matched" if snapshot else "not_imported",
            **payload,
        )
        _save(item)
    FulfillmentStatusEvent.objects.create(
        tenant=user.tenant,
        fulfillment=fulfillment,
        from_status="",
        to_status=fulfillment.status,
        actor=user,
        reason="created",
    )
    _audit(user, "sample_create", "sample_fulfillment", fulfillment, after={"fulfillment_no": fulfillment.fulfillment_no, "status": fulfillment.status})
    return fulfillment, True


@transaction.atomic
def transition_sample_fulfillment(*, user, fulfillment, status, expected_version, reason=""):
    fulfillment = SampleFulfillment.objects.select_for_update().get(pk=fulfillment.pk, tenant=user.tenant)
    if fulfillment.version != expected_version:
        raise ValidationError({"version": "Fulfillment was changed by another request."}, code="conflict")
    if status not in SampleFulfillment.Status.values:
        raise ValidationError({"status": "Unsupported fulfillment status."})
    allowed = {
        SampleFulfillment.Status.PENDING: {SampleFulfillment.Status.PROCESSING, SampleFulfillment.Status.CANCELLED},
        SampleFulfillment.Status.PROCESSING: {SampleFulfillment.Status.SHIPPED, SampleFulfillment.Status.CANCELLED},
        SampleFulfillment.Status.SHIPPED: {SampleFulfillment.Status.DELIVERED, SampleFulfillment.Status.CANCELLED},
        SampleFulfillment.Status.DELIVERED: {SampleFulfillment.Status.COMPLETED, SampleFulfillment.Status.CANCELLED},
        SampleFulfillment.Status.COMPLETED: set(),
        SampleFulfillment.Status.CANCELLED: set(),
    }
    if status not in allowed[fulfillment.status]:
        raise ValidationError({"status": f"Transition from {fulfillment.status} to {status} is not allowed."})
    before_status = fulfillment.status
    fulfillment.status = status
    fulfillment.version += 1
    if status in {SampleFulfillment.Status.COMPLETED, SampleFulfillment.Status.CANCELLED}:
        fulfillment.finalized_at = timezone.now()
    _save(fulfillment)
    FulfillmentStatusEvent.objects.create(
        tenant=user.tenant,
        fulfillment=fulfillment,
        from_status=before_status,
        to_status=status,
        actor=user,
        reason=reason,
    )
    _audit(user, "sample_status", "sample_fulfillment", fulfillment, before={"status": before_status}, after={"status": status, "version": fulfillment.version})
    return fulfillment
