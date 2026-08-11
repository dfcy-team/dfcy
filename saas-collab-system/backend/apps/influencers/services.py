import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from uuid import UUID

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Model, QuerySet
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.audit.services import write_operation_log
from apps.masterdata.models import StoreMaster
from apps.products.models import ProductSPU

from .models import (
    FulfillmentStatusEvent,
    Influencer,
    InfluencerRestriction,
    OutreachTarget,
    OutreachTask,
    SampleFulfillment,
    SampleItem,
    SkuPriceSnapshot,
    StoreProductListing,
)


TERMINAL_OUTREACH_TASK_STATUSES = frozenset(
    {OutreachTask.Status.COMPLETED, OutreachTask.Status.CANCELLED}
)
OUTREACH_RESULT_TRANSITIONS = {
    OutreachTarget.OutreachResult.PENDING: frozenset(
        {
            OutreachTarget.OutreachResult.SUCCESS,
            OutreachTarget.OutreachResult.REJECTED,
            OutreachTarget.OutreachResult.NO_RESPONSE,
            OutreachTarget.OutreachResult.BLOCKED,
        }
    ),
    OutreachTarget.OutreachResult.SUCCESS: frozenset(),
    OutreachTarget.OutreachResult.REJECTED: frozenset(),
    OutreachTarget.OutreachResult.NO_RESPONSE: frozenset(),
    OutreachTarget.OutreachResult.BLOCKED: frozenset(),
}


def _assert_task_accepts_target(task):
    if task.status in TERMINAL_OUTREACH_TASK_STATUSES:
        raise ValidationError(
            {"outreach_task": "Completed or cancelled outreach tasks cannot change targets or samples."},
            code="conflict",
        )


def _canonical_scalar(value):
    """Reduce request data to deterministic JSON scalars and relation primary keys."""
    if isinstance(value, Model):
        return _canonical_scalar(value.pk)
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_scalar(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_scalar(item) for item in value]
    if isinstance(value, set):
        return sorted(
            (_canonical_scalar(item) for item in value),
            key=lambda item: json.dumps(item, sort_keys=True, default=str),
        )
    if isinstance(value, Decimal):
        normalized = value.normalize()
        return "0" if normalized == 0 else format(normalized, "f")
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (UUID, Enum)):
        return str(value.value if isinstance(value, Enum) else value)
    return value


def _payload_hash(payload):
    encoded = json.dumps(
        _canonical_scalar(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
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
        raise ValidationError(
            exc.message_dict if hasattr(exc, "message_dict") else exc.messages
        ) from exc


def _cas_state_update(instance, *, tenant, expected_status, expected_version, **changes):
    queryset = type(instance).objects.filter(
        pk=instance.pk,
        tenant=tenant,
        status=expected_status,
        version=expected_version,
    )
    updated = QuerySet.update(queryset, **changes)
    if updated != 1:
        raise ValidationError(
            {"version": "Workflow record was changed by another request."},
            code="conflict",
        )
    instance.refresh_from_db()


def _pk(value):
    return getattr(value, "pk", value)


def _locked_influencer(user, influencer_id):
    try:
        return Influencer.objects.select_for_update().get(
            pk=influencer_id, tenant=user.tenant
        )
    except Influencer.DoesNotExist as exc:
        raise ValidationError(
            {"influencer": "Influencer does not exist in the current tenant."}
        ) from exc


def _locked_store(user, store_id):
    try:
        return StoreMaster.objects.select_for_update().get(pk=store_id, tenant=user.tenant)
    except StoreMaster.DoesNotExist as exc:
        raise ValidationError(
            {"store": "Store does not exist in the current tenant."}
        ) from exc


def _locked_user(user, user_id, field="owner"):
    if user_id is None:
        raise ValidationError({field: f"{field.capitalize()} is required."})
    try:
        return get_user_model().objects.select_for_update().get(
            pk=user_id, tenant=user.tenant
        )
    except get_user_model().DoesNotExist as exc:
        raise ValidationError(
            {field: f"{field.capitalize()} does not exist in the current tenant."}
        ) from exc


def _locked_spu(user, spu_id):
    if spu_id is None:
        return None
    try:
        return ProductSPU.objects.select_for_update().get(pk=spu_id, tenant=user.tenant)
    except ProductSPU.DoesNotExist as exc:
        raise ValidationError(
            {"spu": "Product does not exist in the current tenant."}
        ) from exc


def _locked_task(user, task_id):
    try:
        return OutreachTask.objects.select_for_update().get(
            pk=task_id, tenant=user.tenant
        )
    except OutreachTask.DoesNotExist as exc:
        raise ValidationError(
            {"outreach_task": "Outreach task does not exist in the current tenant."}
        ) from exc


def _locked_target(user, target_id):
    try:
        return OutreachTarget.objects.select_for_update().get(
            pk=target_id, tenant=user.tenant
        )
    except OutreachTarget.DoesNotExist as exc:
        raise ValidationError(
            {"outreach_target": "Outreach target does not exist in the current tenant."}
        ) from exc


def _lock_task_relations(
    user,
    *,
    task_id,
    target_id,
    influencer_id=None,
    store_id=None,
    owner_id=None,
    external_product_id=None,
):
    """Lock and validate task-owned relations before creating a fulfillment."""
    task = _locked_task(user, task_id)
    if task.is_deleted:
        raise ValidationError({"outreach_task": "Deleted outreach tasks cannot receive samples."})
    _assert_task_accepts_target(task)

    influencer = None
    if target_id is not None:
        target = _locked_target(user, target_id)
        if target.task_id != task.pk:
            raise ValidationError({"outreach_target": "Target must belong to the outreach task."})
        if target.is_deleted:
            raise ValidationError({"outreach_target": "Deleted outreach targets cannot receive samples."})
        influencer = _locked_influencer(user, target.influencer_id)
    else:
        inferred_influencer_id = _pk(influencer_id) if influencer_id is not None else task.influencer_id
        if inferred_influencer_id is None:
            raise ValidationError({"outreach_target": "A target is required for this sample."})
        influencer = _locked_influencer(user, inferred_influencer_id)
        target = OutreachTarget.objects.select_for_update().filter(
            tenant=user.tenant,
            task=task,
            influencer=influencer,
            is_deleted=False,
        ).first()
        if target is None:
            target, _ = add_outreach_target(user=user, task=task, influencer=influencer)

    if influencer_id is not None and _pk(influencer_id) != influencer.pk:
        raise ValidationError({"influencer": "Influencer must match the outreach target."})

    store = _locked_store(user, task.store_id)
    if store_id is not None and _pk(store_id) != store.pk:
        raise ValidationError({"store": "Store must match the outreach task."})

    owner = _locked_user(user, task.owner_id)
    if owner_id is not None and _pk(owner_id) != owner.pk:
        raise ValidationError({"owner": "Owner must match the outreach task."})

    task_product_id = (task.external_product_id or "").strip()
    supplied_product_id = (str(external_product_id).strip() if external_product_id is not None else "")
    if supplied_product_id and supplied_product_id != task_product_id:
        raise ValidationError({"external_product_id": "Product must match the outreach task."})

    if task.spu_id:
        _locked_spu(user, task.spu_id)
    return task, target, influencer, store, owner


def _product_snapshot(user, task, store):
    product_id = (task.external_product_id or "").strip()
    product_name = ""
    if task.spu_id:
        product_name = (
            ProductSPU.objects.filter(pk=task.spu_id, tenant=user.tenant)
            .values_list("product_name", flat=True)
            .first()
            or ""
        )
    if not product_name and product_id:
        product_name = (
            StoreProductListing.objects.filter(
                tenant=user.tenant,
                store_id=store.pk,
                external_product_id=product_id,
            )
            .order_by("-source_updated_at", "-id")
            .values_list("product_name", flat=True)
            .first()
            or ""
        )
    return product_id, product_name


def _normalize_item_payloads(item_payloads):
    normalized = []
    for payload in item_payloads:
        item = dict(payload)
        requested_sku = item.get("requested_sku")
        item["requested_sku"] = (
            str(requested_sku).strip() or None if requested_sku is not None else None
        )
        site_code = str(item.get("site_code") or "").strip()
        if not site_code:
            raise ValidationError({"items": "Each sample item requires site_code."})
        item["site_code"] = site_code
        try:
            quantity = int(item.get("quantity") or 0)
        except (TypeError, ValueError) as exc:
            raise ValidationError({"items": "Each sample item quantity must be a positive integer."}) from exc
        if quantity < 1:
            raise ValidationError({"items": "Each sample item quantity must be positive."})
        item["quantity"] = quantity
        normalized.append(item)
    return normalized


def _inherit_item_product(payload, *, product_id, product_name):
    item = dict(payload)
    supplied_product_id = str(item.get("external_product_id") or "").strip()
    if product_id and supplied_product_id and supplied_product_id != product_id:
        raise ValidationError({"items": "Item product must match the outreach task."})
    item["external_product_id"] = supplied_product_id or product_id
    if not str(item.get("product_name") or "").strip() and product_name:
        item["product_name"] = product_name
    return item


def _price_for_item(tenant, store_id, payload):
    sku = str(payload.get("requested_sku") or "").strip()
    product_id = str(payload.get("external_product_id") or "").strip()
    site_code = str(payload.get("site_code") or "").strip()
    if not sku:
        return None
    queryset = SkuPriceSnapshot.objects.select_related("listing").filter(
        tenant=tenant,
        listing__tenant=tenant,
        listing__store_id=store_id,
        listing__site_code=site_code,
        external_sku__iexact=sku,
    )
    if product_id:
        queryset = queryset.filter(listing__external_product_id=product_id)
    return queryset.order_by("-source_updated_at", "-imported_at", "-id").first()


@transaction.atomic
def create_outreach_task(*, user, validated_data):
    data = dict(validated_data)
    owner_value = data.get("owner")
    if owner_value is None:
        raise ValidationError({"owner": "Owner is required."})
    owner = _locked_user(user, _pk(owner_value))
    store = _locked_store(user, _pk(data["store"]))
    influencer = None
    if "influencer" in data and data["influencer"] is not None:
        influencer = _locked_influencer(user, _pk(data["influencer"]))
    spu = _locked_spu(user, _pk(data["spu"])) if data.get("spu") is not None else None
    data["owner"] = owner
    data["store"] = store
    data["influencer"] = influencer
    data["spu"] = spu
    data["dispatcher"] = user
    data["external_id"] = data.get("external_id") or None
    data["external_product_id"] = str(data.get("external_product_id") or "").strip()
    data["sku_prefix"] = str(data.get("sku_prefix") or "").strip()
    data["dispatch_time"] = timezone.now()
    task = OutreachTask(tenant=user.tenant, **data)
    _save(task)
    if influencer is not None:
        add_outreach_target(user=user, task=task, influencer=influencer)
    _audit(
        user,
        "outreach_create",
        "outreach_task",
        task,
        after={
            "task_no": task.task_no,
            "status": task.status,
            "dispatcher_id": user.pk,
            "dispatch_time": task.dispatch_time.isoformat(),
        },
    )
    return task


@transaction.atomic
def add_outreach_target(
    *, user, task, influencer, notes="", first_linked_at=None, expected_version=None
):
    task = _locked_task(user, _pk(task))
    if task.is_deleted:
        raise ValidationError({"outreach_task": "Deleted outreach tasks cannot receive targets."})
    _assert_task_accepts_target(task)
    influencer = _locked_influencer(user, _pk(influencer))
    if InfluencerRestriction.objects.filter(
        tenant=user.tenant,
        influencer=influencer,
        is_blacklisted=True,
    ).exists():
        raise ValidationError(
            {"influencer": "Blacklisted influencers cannot be linked to outreach tasks."},
            code="conflict",
        )
    if task.target_count and OutreachTarget.objects.filter(
        tenant=user.tenant, task=task, is_deleted=False
    ).exclude(influencer=influencer).count() >= task.target_count:
        raise ValidationError({"target_count": "The outreach task has reached its target count."})
    now = timezone.now()
    target = (
        OutreachTarget.objects.select_for_update()
        .filter(tenant=user.tenant, task=task, influencer=influencer)
        .first()
    )
    created = target is None
    if target is None:
        target = OutreachTarget(
            tenant=user.tenant,
            task=task,
            influencer=influencer,
            first_linked_at=first_linked_at or now,
            notes=notes or "",
        )
        _save(target)
    elif target.is_deleted:
        if expected_version is None or target.version != expected_version:
            raise ValidationError(
                {"version": "The deleted outreach target version is required for restore."},
                code="conflict",
            )
        updated = QuerySet.update(
            OutreachTarget.objects.filter(
                pk=target.pk,
                tenant=user.tenant,
                version=expected_version,
            ),
            is_deleted=False,
            deleted_at=None,
            version=target.version + 1,
            notes=notes if notes is not None else target.notes,
            updated_at=now,
        )
        if updated != 1:
            raise ValidationError(
                {"version": "Outreach target was changed by another request."},
                code="conflict",
            )
        target.refresh_from_db()
    if task.outreach_at is None:
        QuerySet.update(
            OutreachTask.objects.filter(pk=task.pk, tenant=user.tenant),
            outreach_at=now,
            updated_at=now,
        )
        task.refresh_from_db()
    _audit(
        user,
        "outreach_target_add" if created else "outreach_target_restore",
        "outreach_target",
        target,
        after={"task_id": task.pk, "influencer_id": influencer.pk, "is_deleted": target.is_deleted},
    )
    return target, created


@transaction.atomic
def update_outreach_target(
    *, user, task, target, expected_version, outreach_result=None, notes=None
):
    task = _locked_task(user, _pk(task))
    if task.is_deleted:
        raise ValidationError({"outreach_task": "Deleted outreach tasks cannot be updated."})
    _assert_task_accepts_target(task)
    target = _locked_target(user, _pk(target))
    if target.task_id != task.pk:
        raise ValidationError({"outreach_target": "Target must belong to the outreach task."})
    if target.is_deleted:
        raise ValidationError({"outreach_target": "Deleted outreach targets cannot be updated."})
    if target.version != expected_version:
        raise ValidationError(
            {"version": "Outreach target was changed by another request."},
            code="conflict",
        )
    changes = {"version": target.version + 1, "updated_at": timezone.now()}
    before = {"outreach_result": target.outreach_result, "notes": target.notes}
    if outreach_result is not None:
        if outreach_result not in OutreachTarget.OutreachResult.values:
            raise ValidationError({"outreach_result": "Unsupported outreach result."})
        if (
            outreach_result != target.outreach_result
            and outreach_result not in OUTREACH_RESULT_TRANSITIONS[target.outreach_result]
        ):
            raise ValidationError(
                {"outreach_result": "This outreach result transition is not allowed."}
            )
        changes["outreach_result"] = outreach_result
    if notes is not None:
        changes["notes"] = notes
    updated = QuerySet.update(
        OutreachTarget.objects.filter(
            pk=target.pk,
            tenant=user.tenant,
            version=expected_version,
        ),
        **changes,
    )
    if updated != 1:
        raise ValidationError(
            {"version": "Outreach target was changed by another request."},
            code="conflict",
        )
    target.refresh_from_db()
    _maybe_auto_complete_outreach_task(user, task)
    _audit(
        user,
        "outreach_target_update",
        "outreach_target",
        target,
        before=before,
        after={"outreach_result": target.outreach_result, "notes": target.notes},
    )
    return target


def _maybe_auto_complete_outreach_task(user, task):
    if task.status not in {OutreachTask.Status.PENDING, OutreachTask.Status.IN_PROGRESS}:
        return task
    rows = list(
        OutreachTarget.objects.filter(
            tenant=user.tenant, task=task, is_deleted=False
        ).values_list("outreach_result", flat=True)
    )
    if not rows or OutreachTarget.OutreachResult.PENDING in rows:
        return task
    if task.target_count and len(rows) < task.target_count:
        return task
    now = timezone.now()
    changes = {
        "status": OutreachTask.Status.COMPLETED,
        "version": task.version + 1,
        "finalized_at": now,
        "outreach_at": task.outreach_at or now,
        "updated_at": now,
    }
    if task.started_at is None:
        changes["started_at"] = now
    updated = QuerySet.update(
        OutreachTask.objects.filter(
            pk=task.pk,
            tenant=user.tenant,
            status=task.status,
            version=task.version,
        ),
        **changes,
    )
    if updated:
        task.refresh_from_db()
        _audit(
            user,
            "outreach_auto_complete",
            "outreach_task",
            task,
            after={"status": task.status, "version": task.version},
        )
    return task


@transaction.atomic
def soft_delete_outreach_target(*, user, task, target, expected_version):
    task = _locked_task(user, _pk(task))
    _assert_task_accepts_target(task)
    if task.is_deleted:
        raise ValidationError({"outreach_task": "Deleted outreach tasks cannot be changed."})
    target = _locked_target(user, _pk(target))
    if target.task_id != task.pk:
        raise ValidationError({"outreach_target": "Target must belong to the outreach task."})
    if target.is_deleted:
        return target
    if target.version != expected_version:
        raise ValidationError(
            {"version": "Outreach target was changed by another request."},
            code="conflict",
        )
    now = timezone.now()
    updated = QuerySet.update(
        OutreachTarget.objects.filter(
            pk=target.pk,
            tenant=user.tenant,
            version=expected_version,
        ),
        is_deleted=True,
        deleted_at=now,
        version=target.version + 1,
        updated_at=now,
    )
    if updated != 1:
        raise ValidationError(
            {"version": "Outreach target was changed by another request."},
            code="conflict",
        )
    target.refresh_from_db()
    _audit(user, "outreach_target_delete", "outreach_target", target, after={"is_deleted": True})
    return target


@transaction.atomic
def soft_delete_outreach_task(*, user, task):
    task = _locked_task(user, _pk(task))
    if task.is_deleted:
        return task
    now = timezone.now()
    QuerySet.update(
        OutreachTask.objects.filter(pk=task.pk, tenant=user.tenant),
        is_deleted=True,
        deleted_at=now,
        updated_at=now,
    )
    task.refresh_from_db()
    _audit(user, "outreach_delete", "outreach_task", task, after={"is_deleted": True})
    return task


def outreach_task_progress(*, user, task):
    task = OutreachTask.objects.filter(
        pk=_pk(task), tenant=user.tenant, is_deleted=False
    ).first()
    if task is None:
        raise ValidationError({"outreach_task": "Outreach task does not exist in the current tenant."})
    result_counts = {result: 0 for result in OutreachTarget.OutreachResult.values}
    for result in OutreachTarget.objects.filter(
        tenant=user.tenant, task=task, is_deleted=False
    ).values_list("outreach_result", flat=True):
        result_counts[result] = result_counts.get(result, 0) + 1
    linked_count = sum(result_counts.values())
    terminal_count = linked_count - result_counts.get(OutreachTarget.OutreachResult.PENDING, 0)
    return {
        "task_id": task.pk,
        "target_count": task.target_count,
        "linked_count": linked_count,
        "remaining_count": max(task.target_count - linked_count, 0),
        "terminal_count": terminal_count,
        "pending_count": result_counts.get(OutreachTarget.OutreachResult.PENDING, 0),
        "result_counts": result_counts,
        "status": task.status,
        "is_complete": task.status == OutreachTask.Status.COMPLETED,
    }


@transaction.atomic
def transition_outreach_task(*, user, task, status, expected_version):
    task = OutreachTask.objects.select_for_update().get(pk=task.pk, tenant=user.tenant)
    if task.is_deleted:
        raise ValidationError({"outreach_task": "Deleted outreach tasks cannot transition."})
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
    changes = {"status": status, "version": task.version + 1, "updated_at": now}
    if status == OutreachTask.Status.IN_PROGRESS:
        changes["started_at"] = task.started_at or now
        changes["outreach_at"] = task.outreach_at or now
    if status in {OutreachTask.Status.COMPLETED, OutreachTask.Status.CANCELLED}:
        changes["finalized_at"] = now
    _cas_state_update(
        task,
        tenant=user.tenant,
        expected_status=before["status"],
        expected_version=before["version"],
        **changes,
    )
    _audit(
        user,
        "outreach_status",
        "outreach_task",
        task,
        before=before,
        after={"status": task.status, "version": task.version},
    )
    return task


@transaction.atomic
def create_sample_fulfillment(*, user, request_key, validated_data, item_payloads):
    if not request_key or len(request_key) > 128:
        raise ValidationError({"idempotency_key": "Idempotency-Key must be 1-128 characters."})
    data = dict(validated_data)
    item_payloads = _normalize_item_payloads(item_payloads)
    request_hash = _payload_hash({"fulfillment": data, "items": item_payloads})
    existing = SampleFulfillment.objects.select_for_update().filter(
        tenant=user.tenant, request_key=request_key
    ).first()
    if existing:
        if existing.request_hash != request_hash:
            raise ValidationError(
                {"idempotency_key": "Key was already used with a different payload."},
                code="conflict",
            )
        return existing, False

    if "store" in data and data["store"] is None:
        raise ValidationError({"store": "Store must match the outreach task."})
    if "influencer" in data and data["influencer"] is None:
        raise ValidationError({"influencer": "Influencer must match the outreach target."})
    if "owner" in data and data["owner"] is None:
        raise ValidationError({"owner": "Owner must match the outreach task."})

    task, target, influencer, store, owner = _lock_task_relations(
        user,
        task_id=_pk(data["outreach_task"]),
        target_id=_pk(data["outreach_target"]) if data.get("outreach_target") is not None else None,
        influencer_id=data.get("influencer"),
        store_id=data.get("store"),
        owner_id=data.get("owner"),
        external_product_id=data.get("external_product_id"),
    )
    if InfluencerRestriction.objects.filter(
        tenant=user.tenant,
        influencer=influencer,
        is_blacklisted=True,
    ).exists():
        raise ValidationError(
            {"influencer": "Blacklisted influencers cannot receive samples."}
        )
    product_id, product_name = _product_snapshot(user, task, store)
    supplied_product_name = str(data.get("product_name_snapshot") or "").strip()
    if supplied_product_name and product_name and supplied_product_name != product_name:
        raise ValidationError({"product_name_snapshot": "Product name must match the outreach task."})

    fulfillment_data = dict(data)
    has_sample_order = bool(str(data.get("sample_order_no") or "").strip())
    initial_status = SampleFulfillment.Status.PENDING
    initial_shipped_at = timezone.now() if has_sample_order else None
    fulfillment_data.update(
        {
            "outreach_task": task,
            "outreach_target": target,
            "influencer": influencer,
            "store": store,
            "owner": owner,
            "product_name_snapshot": product_name,
            "external_product_id": product_id,
            "request_key": request_key,
            "request_hash": request_hash,
            "status": initial_status,
            "sample_sent_at": timezone.now(),
            "shipped_at": None,
        }
    )
    fulfillment_data.pop("items", None)
    fulfillment_data.pop("product_name_snapshot", None)
    fulfillment_data["product_name_snapshot"] = product_name
    fulfillment_data.pop("request_key", None)
    fulfillment_data["request_key"] = request_key
    fulfillment_data.pop("request_hash", None)
    fulfillment_data["request_hash"] = request_hash

    fulfillment = SampleFulfillment(tenant=user.tenant, **fulfillment_data)
    try:
        with transaction.atomic():
            _save(fulfillment)
    except IntegrityError as exc:
        existing = SampleFulfillment.objects.select_for_update().filter(
            tenant=user.tenant, request_key=request_key
        ).first()
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ValidationError(
                    {"idempotency_key": "Key was already used with a different payload."},
                    code="conflict",
                ) from exc
            return existing, False
        competing_number = SampleFulfillment.objects.select_for_update().filter(
            tenant=user.tenant, fulfillment_no=fulfillment.fulfillment_no
        ).first()
        if competing_number is not None:
            raise ValidationError(
                {"fulfillment_no": "Fulfillment number already exists."}, code="conflict"
            ) from exc
        raise

    if has_sample_order:
        QuerySet.update(
            SampleFulfillment.objects.filter(
                pk=fulfillment.pk,
                tenant=user.tenant,
                status=SampleFulfillment.Status.PENDING,
            ),
            status=SampleFulfillment.Status.SHIPPED,
            shipped_at=initial_shipped_at,
            updated_at=timezone.now(),
        )
        fulfillment.refresh_from_db()

    for payload in item_payloads:
        payload = _inherit_item_product(payload, product_id=product_id, product_name=product_name)
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
    _audit(
        user,
        "sample_create",
        "sample_fulfillment",
        fulfillment,
        after={
            "fulfillment_no": fulfillment.fulfillment_no,
            "status": fulfillment.status,
            "outreach_target_id": target.pk,
        },
    )
    return fulfillment, True


@transaction.atomic
def transition_sample_fulfillment(*, user, fulfillment, status, expected_version, reason=""):
    fulfillment = SampleFulfillment.objects.select_for_update().get(
        pk=fulfillment.pk, tenant=user.tenant
    )
    if fulfillment.version != expected_version:
        raise ValidationError(
            {"version": "Fulfillment was changed by another request."}, code="conflict"
        )
    if status not in SampleFulfillment.Status.values:
        raise ValidationError({"status": "Unsupported fulfillment status."})
    allowed = {
        SampleFulfillment.Status.PENDING: {
            SampleFulfillment.Status.PROCESSING,
            SampleFulfillment.Status.CREATING,
            SampleFulfillment.Status.BLANK,
            SampleFulfillment.Status.CANCELLED,
        },
        SampleFulfillment.Status.CREATING: {
            SampleFulfillment.Status.PUBLISHED,
            SampleFulfillment.Status.BLANK,
            SampleFulfillment.Status.CANCELLED,
        },
        SampleFulfillment.Status.PUBLISHED: {
            SampleFulfillment.Status.LIVE_CREATOR,
            SampleFulfillment.Status.OVERDUE,
            SampleFulfillment.Status.CANCELLED,
        },
        SampleFulfillment.Status.LIVE_CREATOR: {
            SampleFulfillment.Status.OVERDUE,
            SampleFulfillment.Status.COMPLETED,
            SampleFulfillment.Status.CANCELLED,
        },
        SampleFulfillment.Status.OVERDUE: {
            SampleFulfillment.Status.COMPLETED,
            SampleFulfillment.Status.CANCELLED,
        },
        SampleFulfillment.Status.BLANK: {
            SampleFulfillment.Status.CREATING,
            SampleFulfillment.Status.CANCELLED,
        },
        SampleFulfillment.Status.PROCESSING: {
            SampleFulfillment.Status.SHIPPED,
            SampleFulfillment.Status.CANCELLED,
        },
        SampleFulfillment.Status.SHIPPED: {
            SampleFulfillment.Status.DELIVERED,
            SampleFulfillment.Status.CANCELLED,
        },
        SampleFulfillment.Status.DELIVERED: {
            SampleFulfillment.Status.COMPLETED,
            SampleFulfillment.Status.CANCELLED,
        },
        SampleFulfillment.Status.COMPLETED: set(),
        SampleFulfillment.Status.CANCELLED: set(),
    }
    if status not in allowed[fulfillment.status]:
        raise ValidationError(
            {"status": f"Transition from {fulfillment.status} to {status} is not allowed."}
        )
    before_status = fulfillment.status
    now = timezone.now()
    changes = {
        "status": status,
        "version": fulfillment.version + 1,
        "updated_at": now,
    }
    if status == SampleFulfillment.Status.PROCESSING and fulfillment.sample_sent_at is None:
        changes["sample_sent_at"] = now
    if status == SampleFulfillment.Status.SHIPPED and fulfillment.shipped_at is None:
        changes["shipped_at"] = now
    if status in {SampleFulfillment.Status.COMPLETED, SampleFulfillment.Status.CANCELLED}:
        changes["finalized_at"] = now
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
    _audit(
        user,
        "sample_status",
        "sample_fulfillment",
        fulfillment,
        before={"status": before_status},
        after={"status": status, "version": fulfillment.version},
    )
    return fulfillment
