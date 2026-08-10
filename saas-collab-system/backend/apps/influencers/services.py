import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from uuid import UUID

from django.db import IntegrityError, transaction
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Model, QuerySet
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit.services import write_operation_log
from apps.masterdata.models import StoreMaster

from .models import (
    FulfillmentStatusEvent,
    Influencer,
    InfluencerRestriction,
    OutreachTask,
    SampleFulfillment,
    SampleItem,
    SkuPriceSnapshot,
)


def _canonical_scalar(value):
    """Reduce request data to deterministic JSON scalars and relation primary keys."""
    if isinstance(value, Model):
        return _canonical_scalar(value.pk)
    if isinstance(value, Mapping):
        return {str(key): _canonical_scalar(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical_scalar(item) for item in value]
    if isinstance(value, set):
        return sorted((_canonical_scalar(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True, default=str))
    if isinstance(value, Decimal):
        normalized = value.normalize()
        return "0" if normalized == 0 else format(normalized, "f")
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (UUID, Enum)):
        return str(value.value if isinstance(value, Enum) else value)
    return value


def _payload_hash(payload):
    encoded = json.dumps(_canonical_scalar(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
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


def _cas_state_update(instance, *, tenant, expected_status, expected_version, **changes):
    queryset = type(instance).objects.filter(
        pk=instance.pk,
        tenant=tenant,
        status=expected_status,
        version=expected_version,
    )
    updated = QuerySet.update(queryset, **changes)
    if updated != 1:
        raise ValidationError({"version": "Workflow record was changed by another request."}, code="conflict")
    instance.refresh_from_db()


def _pk(value):
    return getattr(value, "pk", value)


def _locked_influencer(user, influencer_id):
    try:
        return Influencer.objects.select_for_update().get(pk=influencer_id, tenant=user.tenant)
    except Influencer.DoesNotExist as exc:
        raise ValidationError({"influencer": "Influencer does not exist in the current tenant."}) from exc


def _locked_store(user, store_id):
    try:
        return StoreMaster.objects.select_for_update().get(pk=store_id, tenant=user.tenant)
    except StoreMaster.DoesNotExist as exc:
        raise ValidationError({"store": "Store does not exist in the current tenant."}) from exc


def _locked_task(user, task_id):
    try:
        return OutreachTask.objects.select_for_update().get(pk=task_id, tenant=user.tenant)
    except OutreachTask.DoesNotExist as exc:
        raise ValidationError({"outreach_task": "Outreach task does not exist in the current tenant."}) from exc


def _lock_task_relations(user, *, task_id, influencer_id, store_id):
    """Lock and validate all task relations before a fulfillment can be created."""
    influencer = _locked_influencer(user, influencer_id)
    store = _locked_store(user, store_id)
    task = _locked_task(user, task_id)
    if task.influencer_id != influencer.pk:
        raise ValidationError({"influencer": "Influencer must match the outreach task."})
    if task.store_id != store.pk:
        raise ValidationError({"store": "Store must match the outreach task."})
    return task, influencer, store


def _normalize_item_payloads(item_payloads):
    normalized = []
    for payload in item_payloads:
        item = dict(payload)
        requested_sku = item.get("requested_sku")
        item["requested_sku"] = str(requested_sku).strip() or None if requested_sku is not None else None
        normalized.append(item)
    return normalized


@transaction.atomic
def create_outreach_task(*, user, validated_data):
    validated_data = dict(validated_data)
    validated_data["influencer"] = _locked_influencer(user, _pk(validated_data["influencer"]))
    validated_data["store"] = _locked_store(user, _pk(validated_data["store"]))
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
    changes = {"status": status, "version": task.version + 1, "updated_at": now}
    if status == OutreachTask.Status.IN_PROGRESS and task.started_at is None:
        changes["started_at"] = now
    if status in {OutreachTask.Status.COMPLETED, OutreachTask.Status.CANCELLED}:
        changes["finalized_at"] = now
    _cas_state_update(
        task,
        tenant=user.tenant,
        expected_status=before["status"],
        expected_version=before["version"],
        **changes,
    )
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
    validated_data = dict(validated_data)
    item_payloads = _normalize_item_payloads(item_payloads)
    request_hash = _payload_hash({"fulfillment": validated_data, "items": item_payloads})
    existing = SampleFulfillment.objects.select_for_update().filter(tenant=user.tenant, request_key=request_key).first()
    if existing:
        if existing.request_hash != request_hash:
            raise ValidationError({"idempotency_key": "Key was already used with a different payload."}, code="conflict")
        return existing, False

    outreach_task, influencer, store = _lock_task_relations(
        user,
        task_id=_pk(validated_data["outreach_task"]),
        influencer_id=_pk(validated_data["influencer"]),
        store_id=_pk(validated_data["store"]),
    )
    validated_data["outreach_task"] = outreach_task
    validated_data["influencer"] = influencer
    validated_data["store"] = store
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
    except IntegrityError as exc:
        existing = SampleFulfillment.objects.select_for_update().filter(tenant=user.tenant, request_key=request_key).first()
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ValidationError({"idempotency_key": "Key was already used with a different payload."}, code="conflict") from exc
            return existing, False
        competing_number = SampleFulfillment.objects.select_for_update().filter(
            tenant=user.tenant,
            fulfillment_no=fulfillment.fulfillment_no,
        ).first()
        if competing_number is not None:
            raise ValidationError({"fulfillment_no": "Fulfillment number already exists."}, code="conflict") from exc
        raise

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
    changes = {"status": status, "version": fulfillment.version + 1, "updated_at": timezone.now()}
    if status in {SampleFulfillment.Status.COMPLETED, SampleFulfillment.Status.CANCELLED}:
        changes["finalized_at"] = timezone.now()
    _cas_state_update(
        fulfillment,
        tenant=user.tenant,
        expected_status=before_status,
        expected_version=expected_version,
        **changes,
    )
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
