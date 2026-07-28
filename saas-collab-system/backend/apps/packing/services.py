import hashlib
import json
import uuid
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import wraps

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Max, Sum
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import CustomUser
from apps.audit.services import write_operation_log
from apps.common.exceptions import BusinessRuleViolation, ScopedResourceNotFound, StateConflict
from apps.masterdata.models import StatusChoices, SupplierMaster
from apps.purchasing.models import SupplyPurchaseOrder, SupplyPurchaseOrderLine

from .models import (
    PackingBatch,
    PackingBatchOrder,
    PackingBox,
    PackingBoxItem,
    PackingChangeRequest,
    PackingEvent,
    PackingStandardVersion,
    PackingSupplierCapability,
    _packing_domain_write_context,
)


DEFAULT_STANDARD_CODE = "packing-v1"
MYSQL_RETRYABLE_ERROR_CODES = {1205, 1213}


@dataclass(frozen=True)
class PackingReplayReference:
    id: int
    snapshot: dict


def _database_error_code(exc):
    candidates = [getattr(exc, "__cause__", None), exc]
    for candidate in candidates:
        args = getattr(candidate, "args", ())
        if args and isinstance(args[0], int):
            return args[0]
    return None


def packing_domain_action(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        try:
            with _packing_domain_write_context():
                return func(*args, **kwargs)
        except OperationalError as exc:
            if _database_error_code(exc) in MYSQL_RETRYABLE_ERROR_CODES:
                raise StateConflict(
                    "Packing transaction hit a retryable database conflict; "
                    "retry with the same idempotency key."
                ) from exc
            raise

    return wrapped


def _canonical_hash(payload):
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_idempotency_key(value):
    if not value or not isinstance(value, str) or len(value) > 128:
        raise ValidationError({"idempotency_key": "A valid Idempotency-Key is required."})


def _validate_actor(actor):
    if not actor or not actor.is_authenticated or not actor.is_active:
        raise PermissionDenied("An active authenticated actor is required.")
    if actor.user_type not in {
        CustomUser.UserType.INTERNAL,
        CustomUser.UserType.EXTERNAL,
    }:
        raise PermissionDenied("This actor type cannot perform packing actions.")


def _actor_type(actor):
    if actor.user_type == CustomUser.UserType.INTERNAL:
        return PackingEvent.ActorType.INTERNAL
    return PackingEvent.ActorType.SUPPLIER


def _supplier_id_for_external_actor(actor):
    profile = getattr(actor, "external_profile", None)
    if not profile or profile.tenant_id != actor.tenant_id or not profile.supplier_id:
        raise PermissionDenied("The supplier account is not bound to a supplier master record.")
    active = SupplierMaster.objects.filter(
        pk=profile.supplier_id,
        tenant=actor.tenant,
        status=StatusChoices.ACTIVE,
    ).exists()
    if not active:
        raise PermissionDenied("The supplier account is not bound to an active supplier.")
    return profile.supplier_id


def _require_supplier_capability(actor, supplier_id, *, mixed_orders=False):
    if actor.user_type == CustomUser.UserType.INTERNAL:
        return
    if _supplier_id_for_external_actor(actor) != supplier_id:
        raise PermissionDenied("The packing batch is outside the current supplier account.")
    capability = PackingSupplierCapability.objects.filter(
        tenant=actor.tenant,
        supplier_id=supplier_id,
    ).first()
    if not capability or not capability.can_self_pack:
        raise PermissionDenied("Supplier self-packing is not enabled.")
    if mixed_orders and not capability.can_mix_order_packing:
        raise PermissionDenied("Supplier mixed-order packing is not enabled.")


def _default_standard():
    standard = PackingStandardVersion.objects.filter(
        code=DEFAULT_STANDARD_CODE,
        is_active=True,
    ).order_by("-version").first()
    if standard is None:
        raise StateConflict("The frozen packing standard is not installed.")
    return standard


def _set_domain_fields(instance, **fields):
    for field, value in fields.items():
        setattr(instance, field, value)
    instance.save(update_fields=[*fields, "updated_at"] if hasattr(instance, "updated_at") else list(fields))


def _batch_snapshot(batch):
    boxes = []
    for box in batch.boxes.prefetch_related("items").order_by("sequence"):
        boxes.append(
            {
                "id": box.id,
                "box_no": box.box_no,
                "sequence": box.sequence,
                "weight": str(box.weight) if box.weight is not None else None,
                "volume": str(box.volume) if box.volume is not None else None,
                "items": [
                    {
                        "order_line_id": item.order_line_id,
                        "quantity": item.quantity,
                        "order_no": item.order_no_snapshot,
                        "sku_code": item.sku_code_snapshot,
                    }
                    for item in box.items.order_by("id")
                ],
            }
        )
    return {
        "id": batch.id,
        "batch_no": batch.batch_no,
        "supplier_id": batch.supplier_id,
        "status": batch.status,
        "version": batch.version,
        "order_ids": list(
            batch.batch_orders.filter(active_guard=True)
            .order_by("order_id")
            .values_list("order_id", flat=True)
        ),
        "boxes": boxes,
    }


def _finish_event(event, snapshot):
    event.response_snapshot = snapshot
    event.save(update_fields=["response_snapshot"])


def _write_log(*, batch, actor, action, before, after):
    write_operation_log(
        tenant=batch.tenant,
        user=actor,
        module="supply_chain",
        action=f"packing.{action}",
        object_type="PackingBatch",
        object_id=batch.id,
        before_data=before,
        after_data=after,
    )


def _event_replay(batch, *, action, idempotency_key, request_hash, actor):
    event = PackingEvent.objects.select_for_update().filter(
        batch=batch,
        idempotency_key=idempotency_key,
    ).first()
    if event is None:
        return None
    if event.action != action:
        raise StateConflict("The idempotency key was already used for another packing action.")
    if event.actor_id != actor.id:
        raise StateConflict("The idempotency key belongs to another actor.")
    if event.request_hash != request_hash:
        raise StateConflict("The idempotency key was already used with another payload.")
    return event


def _replay_reference(event, id_key="id"):
    snapshot = event.response_snapshot
    object_id = snapshot.get(id_key)
    if not object_id:
        raise StateConflict("The stored packing idempotency response is incomplete.")
    return PackingReplayReference(id=object_id, snapshot=snapshot)


def _creation_replay_reference(batch, idempotency_key):
    event = PackingEvent.objects.filter(
        batch=batch,
        action=PackingEvent.Action.CREATE_BATCH,
        idempotency_key=idempotency_key,
    ).first()
    if event is None:
        raise StateConflict("The packing creation audit response is missing.")
    return _replay_reference(event)


def _create_event(
    *,
    batch,
    action,
    idempotency_key,
    request_hash,
    actor,
    before_status,
    payload=None,
):
    return PackingEvent.objects.create(
        tenant=batch.tenant,
        batch=batch,
        action=action,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        actor=actor,
        actor_type=_actor_type(actor),
        before_status=before_status,
        after_status=batch.status,
        batch_version=batch.version,
        payload=payload or {},
    )


def _decimal_or_none(value, field):
    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError({field: "A valid decimal value is required."}) from exc
    if parsed <= 0:
        raise BusinessRuleViolation(f"{field} must be greater than zero.")
    return parsed


def _normalize_items(items):
    if not isinstance(items, list) or not items:
        raise BusinessRuleViolation("A packing box must contain at least one item.")
    merged = defaultdict(int)
    for raw in items:
        try:
            line_id = int(raw["order_line_id"])
            quantity = int(raw["quantity"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationError({"items": "Each item requires integer order_line_id and quantity."}) from exc
        if line_id <= 0 or quantity <= 0:
            raise BusinessRuleViolation("Packing item quantity and order line ID must be positive.")
        merged[line_id] += quantity
    return [
        {"order_line_id": line_id, "quantity": merged[line_id]}
        for line_id in sorted(merged)
    ]


def _normalize_boxes(boxes):
    if not isinstance(boxes, list) or not boxes:
        raise BusinessRuleViolation("A completed packing layout must contain at least one box.")
    normalized = []
    for raw in boxes:
        normalized.append(
            {
                "weight": str(_decimal_or_none(raw.get("weight"), "weight"))
                if raw.get("weight") not in (None, "")
                else None,
                "volume": str(_decimal_or_none(raw.get("volume"), "volume"))
                if raw.get("volume") not in (None, "")
                else None,
                "note": str(raw.get("note") or ""),
                "items": _normalize_items(raw.get("items")),
            }
        )
    return normalized


def _locked_batch(*, batch_id, actor):
    _validate_actor(actor)
    batch = (
        PackingBatch.objects.select_for_update()
        .select_related("tenant", "supplier")
        .filter(pk=batch_id, tenant=actor.tenant)
        .first()
    )
    if batch is None:
        raise ScopedResourceNotFound("Packing batch is not available in the authorized tenant.")
    _require_supplier_capability(actor, batch.supplier_id)
    return batch


def _active_order_ids(batch):
    return list(
        PackingBatchOrder.objects.filter(batch=batch, active_guard=True)
        .order_by("order_id")
        .values_list("order_id", flat=True)
    )


def _lock_linked_lines(batch):
    order_ids = _active_order_ids(batch)
    list(
        SupplyPurchaseOrder.objects.select_for_update()
        .filter(pk__in=order_ids, tenant=batch.tenant)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    lines = list(
        SupplyPurchaseOrderLine.objects.select_for_update()
        .select_related("order", "sku", "sku__spu")
        .filter(order_id__in=order_ids, tenant=batch.tenant)
        .order_by("pk")
    )
    return {line.id: line for line in lines}


def _validate_quantities(batch, normalized_items, lines, *, excluded_box_id=None, require_exact=False):
    requested = {item["order_line_id"]: item["quantity"] for item in normalized_items}
    unknown = sorted(set(requested) - set(lines))
    if unknown:
        raise BusinessRuleViolation(f"Order lines are not linked to this packing batch: {unknown}")

    packed_query = PackingBoxItem.objects.filter(box__batch=batch)
    if excluded_box_id is not None:
        packed_query = packed_query.exclude(box_id=excluded_box_id)
    packed = {
        row["order_line_id"]: row["total"]
        for row in packed_query.values("order_line_id").annotate(total=Sum("quantity"))
    }
    for line_id, quantity in requested.items():
        if packed.get(line_id, 0) + quantity > lines[line_id].quantity:
            raise StateConflict(
                f"Packing quantity for order line {line_id} exceeds the purchase quantity."
            )

    if require_exact:
        final = dict(packed)
        for line_id, quantity in requested.items():
            final[line_id] = final.get(line_id, 0) + quantity
        mismatched = [
            line.id
            for line in lines.values()
            if final.get(line.id, 0) != line.quantity
        ]
        if mismatched:
            raise BusinessRuleViolation(
                f"Packing must exactly cover every linked purchase-order line: {sorted(mismatched)}"
            )


def _create_box_records(batch, *, sequence, items, lines, weight=None, volume=None, note=""):
    box = PackingBox.objects.create(
        tenant=batch.tenant,
        batch=batch,
        sequence=sequence,
        box_no=f"{batch.batch_no}-B{sequence:03d}",
        weight=_decimal_or_none(weight, "weight"),
        volume=_decimal_or_none(volume, "volume"),
        note=note,
    )
    for item in items:
        line = lines[item["order_line_id"]]
        PackingBoxItem.objects.create(
            tenant=batch.tenant,
            box=box,
            order_line=line,
            quantity=item["quantity"],
            order_no_snapshot=line.order.order_no,
            sku_code_snapshot=line.sku_code_snapshot,
            product_name_snapshot=line.product_name_snapshot,
        )
    return box


@packing_domain_action
def set_supplier_packing_capability(
    *,
    supplier_id,
    actor,
    can_self_pack,
    can_mix_order_packing=False,
):
    _validate_actor(actor)
    if actor.user_type != CustomUser.UserType.INTERNAL:
        raise PermissionDenied("Only internal actors can configure supplier packing capability.")
    supplier = SupplierMaster.objects.filter(
        pk=supplier_id,
        tenant=actor.tenant,
        status=StatusChoices.ACTIVE,
    ).first()
    if supplier is None:
        raise ScopedResourceNotFound("Supplier is not available in the authorized tenant.")
    with transaction.atomic():
        capability = PackingSupplierCapability.objects.select_for_update().filter(
            tenant=actor.tenant,
            supplier=supplier,
        ).first()
        if capability is None:
            before = {}
            capability = PackingSupplierCapability.objects.create(
                tenant=actor.tenant,
                supplier=supplier,
                can_self_pack=bool(can_self_pack),
                can_mix_order_packing=bool(can_mix_order_packing),
                updated_by=actor,
            )
        else:
            before = {
                "supplier_id": capability.supplier_id,
                "can_self_pack": capability.can_self_pack,
                "can_mix_order_packing": capability.can_mix_order_packing,
            }
            _set_domain_fields(
                capability,
                can_self_pack=bool(can_self_pack),
                can_mix_order_packing=bool(can_mix_order_packing),
                updated_by=actor,
            )
        after = {
            "supplier_id": capability.supplier_id,
            "can_self_pack": capability.can_self_pack,
            "can_mix_order_packing": capability.can_mix_order_packing,
        }
        write_operation_log(
            tenant=actor.tenant,
            user=actor,
            module="supply_chain",
            action="packing.capability.update",
            object_type="PackingSupplierCapability",
            object_id=capability.id,
            before_data=before,
            after_data=after,
        )
        return capability


@packing_domain_action
def create_packing_batch(
    *,
    order_ids,
    actor,
    idempotency_key,
    note="",
    source=None,
):
    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    try:
        normalized_ids = sorted({int(value) for value in order_ids})
    except (TypeError, ValueError) as exc:
        raise ValidationError({"order_ids": "Positive integer order IDs are required."}) from exc
    if not normalized_ids or normalized_ids[0] <= 0:
        raise BusinessRuleViolation("At least one purchase order is required.")
    source = source or {}
    request_payload = {
        "order_ids": normalized_ids,
        "note": note,
        "source": source,
    }
    request_hash = _canonical_hash(request_payload)

    def perform():
        with transaction.atomic():
            existing = PackingBatch.objects.filter(
                tenant=actor.tenant,
                creation_idempotency_key=idempotency_key,
            ).first()
            if existing:
                if existing.created_by_id != actor.id or existing.creation_request_hash != request_hash:
                    raise StateConflict("The creation idempotency key was used with another payload or actor.")
                return _creation_replay_reference(existing, idempotency_key), True

            orders = list(
                SupplyPurchaseOrder.objects.select_for_update()
                .select_related("supplier")
                .filter(pk__in=normalized_ids, tenant=actor.tenant)
                .order_by("pk")
            )
            if len(orders) != len(normalized_ids):
                raise ScopedResourceNotFound("One or more purchase orders are outside the authorized tenant.")
            supplier_ids = {order.supplier_id for order in orders}
            if len(supplier_ids) != 1:
                raise BusinessRuleViolation("A packing batch cannot mix suppliers.")
            supplier_id = supplier_ids.pop()
            if any(order.supplier.status != StatusChoices.ACTIVE for order in orders):
                raise StateConflict("Packing requires an active supplier master record.")
            _require_supplier_capability(
                actor,
                supplier_id,
                mixed_orders=len(orders) > 1,
            )
            invalid_states = [
                order.id
                for order in orders
                if order.status != SupplyPurchaseOrder.Status.PRODUCTION_COMPLETED
            ]
            if invalid_states:
                raise StateConflict(
                    f"Purchase orders must be production_completed before packing: {invalid_states}"
                )
            active_link = PackingBatchOrder.objects.select_for_update().select_related(
                "batch"
            ).filter(
                order_id__in=normalized_ids,
                active_guard=True,
            ).first()
            if active_link:
                active_batch = active_link.batch
                if (
                    active_batch.creation_idempotency_key == idempotency_key
                    and active_batch.created_by_id == actor.id
                    and active_batch.creation_request_hash == request_hash
                ):
                    return _creation_replay_reference(active_batch, idempotency_key), True
                raise StateConflict("A purchase order already belongs to an active packing batch.")

            source_values = (
                source.get("source_system"),
                source.get("source_table"),
                source.get("source_record_id"),
            )
            if any(source_values) and not all(source_values):
                raise ValidationError(
                    {"source": "Source system, table, and record ID must be supplied together."}
                )
            batch = PackingBatch.objects.create(
                tenant=actor.tenant,
                supplier_id=supplier_id,
                standard_version=_default_standard(),
                batch_no=(
                    f"PKG-{timezone.localdate():%Y%m%d}-"
                    f"{supplier_id}-{uuid.uuid4().hex[:8].upper()}"
                ),
                note=note,
                creation_idempotency_key=idempotency_key,
                creation_request_hash=request_hash,
                source_system=source.get("source_system"),
                source_table=source.get("source_table"),
                source_record_id=source.get("source_record_id"),
                source_updated_at=source.get("source_updated_at"),
                source_payload_hash=source.get("source_payload_hash", ""),
                created_by=actor,
            )
            for order in orders:
                PackingBatchOrder.objects.create(
                    tenant=actor.tenant,
                    batch=batch,
                    order=order,
                )
            event = _create_event(
                batch=batch,
                action=PackingEvent.Action.CREATE_BATCH,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                actor=actor,
                before_status=PackingBatch.Status.DRAFT,
                payload={"order_ids": normalized_ids},
            )
            snapshot = _batch_snapshot(batch)
            _finish_event(event, snapshot)
            _write_log(
                batch=batch,
                actor=actor,
                action=PackingEvent.Action.CREATE_BATCH,
                before={},
                after=snapshot,
            )
            return batch, False

    try:
        return perform()
    except IntegrityError:
        existing = PackingBatch.objects.filter(
            tenant=actor.tenant,
            creation_idempotency_key=idempotency_key,
        ).first()
        if (
            existing
            and existing.created_by_id == actor.id
            and existing.creation_request_hash == request_hash
        ):
            return _creation_replay_reference(existing, idempotency_key), True
        active_batch = PackingBatch.objects.filter(
            batch_orders__order_id__in=normalized_ids,
            batch_orders__active_guard=True,
        ).distinct().first()
        if (
            active_batch
            and active_batch.creation_idempotency_key == idempotency_key
            and active_batch.created_by_id == actor.id
            and active_batch.creation_request_hash == request_hash
        ):
            return _creation_replay_reference(active_batch, idempotency_key), True
        if active_batch or PackingBatchOrder.objects.filter(
            order_id__in=normalized_ids,
            active_guard=True,
        ).exists():
            raise StateConflict(
                "A purchase order already belongs to an active packing batch."
            )
        raise


@packing_domain_action
def add_packing_box(
    *,
    batch_id,
    actor,
    idempotency_key,
    expected_version,
    items,
    weight=None,
    volume=None,
    note="",
):
    _validate_idempotency_key(idempotency_key)
    normalized = _normalize_items(items)
    request_hash = _canonical_hash(
        {
            "expected_version": expected_version,
            "items": normalized,
            "weight": weight,
            "volume": volume,
            "note": note,
        }
    )
    with transaction.atomic():
        batch = _locked_batch(batch_id=batch_id, actor=actor)
        replay = _event_replay(
            batch,
            action=PackingEvent.Action.ADD_BOX,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            actor=actor,
        )
        if replay:
            return _replay_reference(replay, "box_id"), replay, True
        if batch.version != expected_version:
            raise StateConflict("Packing batch version is stale.")
        if batch.status not in {PackingBatch.Status.DRAFT, PackingBatch.Status.IN_PROGRESS}:
            raise StateConflict("Boxes can only be added to an unfinished packing batch.")
        lines = _lock_linked_lines(batch)
        _validate_quantities(batch, normalized, lines)
        sequence = (
            PackingBox.objects.filter(batch=batch).aggregate(value=Max("sequence"))["value"]
            or 0
        ) + 1
        before = _batch_snapshot(batch)
        box = _create_box_records(
            batch,
            sequence=sequence,
            items=normalized,
            lines=lines,
            weight=weight,
            volume=volume,
            note=note,
        )
        _set_domain_fields(
            batch,
            status=PackingBatch.Status.IN_PROGRESS,
            version=batch.version + 1,
        )
        event = _create_event(
            batch=batch,
            action=PackingEvent.Action.ADD_BOX,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            actor=actor,
            before_status=before["status"],
            payload={"box_id": box.id, "items": normalized},
        )
        snapshot = {"box_id": box.id, "batch": _batch_snapshot(batch)}
        _finish_event(event, snapshot)
        _write_log(
            batch=batch,
            actor=actor,
            action=PackingEvent.Action.ADD_BOX,
            before=before,
            after=snapshot["batch"],
        )
        return box, event, False


@packing_domain_action
def replace_packing_box(
    *,
    batch_id,
    box_id,
    actor,
    idempotency_key,
    expected_version,
    items,
    weight=None,
    volume=None,
    note="",
):
    _validate_idempotency_key(idempotency_key)
    normalized = _normalize_items(items)
    request_hash = _canonical_hash(
        {
            "box_id": box_id,
            "expected_version": expected_version,
            "items": normalized,
            "weight": weight,
            "volume": volume,
            "note": note,
        }
    )
    with transaction.atomic():
        batch = _locked_batch(batch_id=batch_id, actor=actor)
        replay = _event_replay(
            batch,
            action=PackingEvent.Action.UPDATE_BOX,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            actor=actor,
        )
        if replay:
            return _replay_reference(replay, "box_id"), replay, True
        if batch.version != expected_version:
            raise StateConflict("Packing batch version is stale.")
        if batch.status != PackingBatch.Status.IN_PROGRESS:
            raise StateConflict("Only in-progress packing batches can be changed.")
        box = PackingBox.objects.select_for_update().filter(
            pk=box_id,
            batch=batch,
        ).first()
        if box is None:
            raise ScopedResourceNotFound("Packing box is not available in this batch.")
        lines = _lock_linked_lines(batch)
        _validate_quantities(batch, normalized, lines, excluded_box_id=box.id)
        before = _batch_snapshot(batch)
        for item in list(box.items.all()):
            item.delete()
        _set_domain_fields(
            box,
            weight=_decimal_or_none(weight, "weight"),
            volume=_decimal_or_none(volume, "volume"),
            note=note,
        )
        for item in normalized:
            line = lines[item["order_line_id"]]
            PackingBoxItem.objects.create(
                tenant=batch.tenant,
                box=box,
                order_line=line,
                quantity=item["quantity"],
                order_no_snapshot=line.order.order_no,
                sku_code_snapshot=line.sku_code_snapshot,
                product_name_snapshot=line.product_name_snapshot,
            )
        _set_domain_fields(batch, version=batch.version + 1)
        event = _create_event(
            batch=batch,
            action=PackingEvent.Action.UPDATE_BOX,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            actor=actor,
            before_status=before["status"],
            payload={"box_id": box.id, "items": normalized},
        )
        snapshot = {"box_id": box.id, "batch": _batch_snapshot(batch)}
        _finish_event(event, snapshot)
        _write_log(
            batch=batch,
            actor=actor,
            action=PackingEvent.Action.UPDATE_BOX,
            before=before,
            after=snapshot["batch"],
        )
        return box, event, False


@packing_domain_action
def remove_packing_box(
    *,
    batch_id,
    box_id,
    actor,
    idempotency_key,
    expected_version,
):
    _validate_idempotency_key(idempotency_key)
    request_hash = _canonical_hash(
        {"box_id": box_id, "expected_version": expected_version}
    )
    with transaction.atomic():
        batch = _locked_batch(batch_id=batch_id, actor=actor)
        replay = _event_replay(
            batch,
            action=PackingEvent.Action.REMOVE_BOX,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            actor=actor,
        )
        if replay:
            return replay, True
        if batch.version != expected_version:
            raise StateConflict("Packing batch version is stale.")
        if batch.status != PackingBatch.Status.IN_PROGRESS:
            raise StateConflict("Only in-progress packing batches can be changed.")
        box = PackingBox.objects.select_for_update().filter(pk=box_id, batch=batch).first()
        if box is None:
            raise ScopedResourceNotFound("Packing box is not available in this batch.")
        before = _batch_snapshot(batch)
        for item in list(box.items.all()):
            item.delete()
        box.delete()
        remaining = PackingBox.objects.filter(batch=batch).exists()
        _set_domain_fields(
            batch,
            status=PackingBatch.Status.IN_PROGRESS if remaining else PackingBatch.Status.DRAFT,
            version=batch.version + 1,
        )
        event = _create_event(
            batch=batch,
            action=PackingEvent.Action.REMOVE_BOX,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            actor=actor,
            before_status=before["status"],
            payload={"box_id": box_id},
        )
        snapshot = _batch_snapshot(batch)
        _finish_event(event, snapshot)
        _write_log(
            batch=batch,
            actor=actor,
            action=PackingEvent.Action.REMOVE_BOX,
            before=before,
            after=snapshot,
        )
        return event, False


@packing_domain_action
def complete_packing_batch(
    *,
    batch_id,
    actor,
    idempotency_key,
    expected_version,
):
    _validate_idempotency_key(idempotency_key)
    request_hash = _canonical_hash({"expected_version": expected_version})
    with transaction.atomic():
        batch = _locked_batch(batch_id=batch_id, actor=actor)
        replay = _event_replay(
            batch,
            action=PackingEvent.Action.COMPLETE_BATCH,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            actor=actor,
        )
        if replay:
            return _replay_reference(replay), replay, True
        if batch.version != expected_version:
            raise StateConflict("Packing batch version is stale.")
        if batch.status != PackingBatch.Status.IN_PROGRESS:
            raise StateConflict("Only an in-progress packing batch can be completed.")
        lines = _lock_linked_lines(batch)
        if not PackingBox.objects.filter(batch=batch).exists():
            raise BusinessRuleViolation("A packing batch cannot complete without boxes.")
        _validate_quantities(batch, [], lines, require_exact=True)
        before = _batch_snapshot(batch)
        _set_domain_fields(
            batch,
            status=PackingBatch.Status.COMPLETED,
            version=batch.version + 1,
            completed_at=timezone.now(),
        )
        event = _create_event(
            batch=batch,
            action=PackingEvent.Action.COMPLETE_BATCH,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            actor=actor,
            before_status=before["status"],
        )
        snapshot = _batch_snapshot(batch)
        _finish_event(event, snapshot)
        _write_log(
            batch=batch,
            actor=actor,
            action=PackingEvent.Action.COMPLETE_BATCH,
            before=before,
            after=snapshot,
        )
        return batch, event, False


@packing_domain_action
def cancel_packing_batch(
    *,
    batch_id,
    actor,
    idempotency_key,
    expected_version,
):
    _validate_idempotency_key(idempotency_key)
    request_hash = _canonical_hash({"expected_version": expected_version})
    with transaction.atomic():
        batch = _locked_batch(batch_id=batch_id, actor=actor)
        replay = _event_replay(
            batch,
            action=PackingEvent.Action.CANCEL_BATCH,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            actor=actor,
        )
        if replay:
            return _replay_reference(replay), replay, True
        if batch.version != expected_version:
            raise StateConflict("Packing batch version is stale.")
        if batch.status not in {PackingBatch.Status.DRAFT, PackingBatch.Status.IN_PROGRESS}:
            raise StateConflict("Only unfinished packing batches can be cancelled.")
        before = _batch_snapshot(batch)
        for link in PackingBatchOrder.objects.select_for_update().filter(
            batch=batch,
            active_guard=True,
        ):
            link.active_guard = None
            link.save(update_fields=["active_guard"])
        _set_domain_fields(
            batch,
            status=PackingBatch.Status.CANCELLED,
            version=batch.version + 1,
            cancelled_at=timezone.now(),
        )
        event = _create_event(
            batch=batch,
            action=PackingEvent.Action.CANCEL_BATCH,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            actor=actor,
            before_status=before["status"],
        )
        snapshot = _batch_snapshot(batch)
        _finish_event(event, snapshot)
        _write_log(
            batch=batch,
            actor=actor,
            action=PackingEvent.Action.CANCEL_BATCH,
            before=before,
            after=snapshot,
        )
        return batch, event, False


@packing_domain_action
def submit_packing_change(
    *,
    batch_id,
    actor,
    idempotency_key,
    expected_version,
    reason,
    proposed_boxes,
):
    _validate_idempotency_key(idempotency_key)
    normalized = _normalize_boxes(proposed_boxes)
    if not str(reason).strip():
        raise ValidationError({"reason": "A packing change reason is required."})
    request_hash = _canonical_hash(
        {
            "expected_version": expected_version,
            "reason": reason,
            "proposed_boxes": normalized,
        }
    )
    with transaction.atomic():
        batch = _locked_batch(batch_id=batch_id, actor=actor)
        replay = _event_replay(
            batch,
            action=PackingEvent.Action.SUBMIT_CHANGE,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            actor=actor,
        )
        if replay:
            return _replay_reference(replay, "change_request_id"), replay, True
        if batch.status != PackingBatch.Status.COMPLETED:
            raise StateConflict("Only completed packing batches accept change requests.")
        if batch.version != expected_version:
            raise StateConflict("Packing batch version is stale.")
        change = PackingChangeRequest.objects.create(
            tenant=batch.tenant,
            batch=batch,
            expected_version=expected_version,
            reason=str(reason).strip(),
            proposed_boxes=normalized,
            request_hash=request_hash,
            submitted_by=actor,
        )
        event = _create_event(
            batch=batch,
            action=PackingEvent.Action.SUBMIT_CHANGE,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            actor=actor,
            before_status=batch.status,
            payload={"change_request_id": change.id},
        )
        snapshot = {
            "change_request_id": change.id,
            "status": change.status,
            "batch_version": batch.version,
        }
        _finish_event(event, snapshot)
        _write_log(
            batch=batch,
            actor=actor,
            action=PackingEvent.Action.SUBMIT_CHANGE,
            before={"version": batch.version},
            after=snapshot,
        )
        return change, event, False


def _replace_completed_layout(batch, boxes):
    lines = _lock_linked_lines(batch)
    flattened = []
    for box in boxes:
        flattened.extend(box["items"])
    merged = defaultdict(int)
    for item in flattened:
        merged[item["order_line_id"]] += item["quantity"]
    unknown = sorted(set(merged) - set(lines))
    if unknown:
        raise BusinessRuleViolation(
            f"Order lines are not linked to this packing batch: {unknown}"
        )
    mismatched = [
        line.id
        for line in lines.values()
        if merged.get(line.id, 0) != line.quantity
    ]
    if mismatched:
        raise BusinessRuleViolation(
            f"Packing must exactly cover every linked purchase-order line: {sorted(mismatched)}"
        )

    for old_box in list(batch.boxes.prefetch_related("items").all()):
        for item in list(old_box.items.all()):
            item.delete()
        old_box.delete()
    for sequence, box in enumerate(boxes, start=1):
        _create_box_records(
            batch,
            sequence=sequence,
            items=box["items"],
            lines=lines,
            weight=box["weight"],
            volume=box["volume"],
            note=box["note"],
        )


@packing_domain_action
def approve_packing_change(
    *,
    change_request_id,
    reviewer,
    idempotency_key,
    review_note="",
):
    _validate_actor(reviewer)
    _validate_idempotency_key(idempotency_key)
    if reviewer.user_type != CustomUser.UserType.INTERNAL:
        raise PermissionDenied("Only internal actors can review packing changes.")
    request_hash = _canonical_hash(
        {
            "change_request_id": change_request_id,
            "review_note": review_note,
        }
    )
    with transaction.atomic():
        change = (
            PackingChangeRequest.objects.select_for_update()
            .select_related("batch", "submitted_by")
            .filter(pk=change_request_id, tenant=reviewer.tenant)
            .first()
        )
        if change is None:
            raise ScopedResourceNotFound("Packing change request is not available in this tenant.")
        batch = _locked_batch(batch_id=change.batch_id, actor=reviewer)
        replay = _event_replay(
            batch,
            action=PackingEvent.Action.APPROVE_CHANGE,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            actor=reviewer,
        )
        if replay:
            return _replay_reference(replay, "change_request_id"), replay, True
        if change.submitted_by_id == reviewer.id:
            raise PermissionDenied("Packing changes require a different reviewer.")
        if change.status != PackingChangeRequest.Status.PENDING:
            raise StateConflict("Packing change request is no longer pending.")
        if batch.status != PackingBatch.Status.COMPLETED:
            raise StateConflict("Packing change target must remain completed.")
        if batch.version != change.expected_version:
            raise StateConflict("Packing batch changed after this request was submitted.")
        before = _batch_snapshot(batch)
        _replace_completed_layout(batch, change.proposed_boxes)
        _set_domain_fields(batch, version=batch.version + 1)
        change.status = PackingChangeRequest.Status.APPROVED
        change.reviewed_by = reviewer
        change.review_note = review_note
        change.reviewed_at = timezone.now()
        change.applied_version = batch.version
        change.save(
            update_fields=[
                "status",
                "reviewed_by",
                "review_note",
                "reviewed_at",
                "applied_version",
            ]
        )
        event = _create_event(
            batch=batch,
            action=PackingEvent.Action.APPROVE_CHANGE,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            actor=reviewer,
            before_status=batch.status,
            payload={"change_request_id": change.id},
        )
        snapshot = {
            "change_request_id": change.id,
            "status": change.status,
            "batch": _batch_snapshot(batch),
        }
        _finish_event(event, snapshot)
        apply_event = _create_event(
            batch=batch,
            action=PackingEvent.Action.APPLY_CHANGE,
            idempotency_key=f"apply:{hashlib.sha256(idempotency_key.encode('utf-8')).hexdigest()}",
            request_hash=request_hash,
            actor=reviewer,
            before_status=batch.status,
            payload={"change_request_id": change.id},
        )
        _finish_event(apply_event, snapshot)
        _write_log(
            batch=batch,
            actor=reviewer,
            action=PackingEvent.Action.APPLY_CHANGE,
            before=before,
            after=snapshot["batch"],
        )
        return change, event, False


@packing_domain_action
def reject_packing_change(
    *,
    change_request_id,
    reviewer,
    idempotency_key,
    review_note,
):
    _validate_actor(reviewer)
    _validate_idempotency_key(idempotency_key)
    if reviewer.user_type != CustomUser.UserType.INTERNAL:
        raise PermissionDenied("Only internal actors can review packing changes.")
    if not str(review_note).strip():
        raise ValidationError({"review_note": "A rejection reason is required."})
    request_hash = _canonical_hash(
        {
            "change_request_id": change_request_id,
            "review_note": review_note,
        }
    )
    with transaction.atomic():
        change = (
            PackingChangeRequest.objects.select_for_update()
            .select_related("batch", "submitted_by")
            .filter(pk=change_request_id, tenant=reviewer.tenant)
            .first()
        )
        if change is None:
            raise ScopedResourceNotFound("Packing change request is not available in this tenant.")
        batch = _locked_batch(batch_id=change.batch_id, actor=reviewer)
        replay = _event_replay(
            batch,
            action=PackingEvent.Action.REJECT_CHANGE,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            actor=reviewer,
        )
        if replay:
            return _replay_reference(replay, "change_request_id"), replay, True
        if change.submitted_by_id == reviewer.id:
            raise PermissionDenied("Packing changes require a different reviewer.")
        if change.status != PackingChangeRequest.Status.PENDING:
            raise StateConflict("Packing change request is no longer pending.")
        change.status = PackingChangeRequest.Status.REJECTED
        change.reviewed_by = reviewer
        change.review_note = str(review_note).strip()
        change.reviewed_at = timezone.now()
        change.save(
            update_fields=["status", "reviewed_by", "review_note", "reviewed_at"]
        )
        event = _create_event(
            batch=batch,
            action=PackingEvent.Action.REJECT_CHANGE,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            actor=reviewer,
            before_status=batch.status,
            payload={"change_request_id": change.id},
        )
        snapshot = {
            "change_request_id": change.id,
            "status": change.status,
            "batch_version": batch.version,
        }
        _finish_event(event, snapshot)
        _write_log(
            batch=batch,
            actor=reviewer,
            action=PackingEvent.Action.REJECT_CHANGE,
            before={"status": PackingChangeRequest.Status.PENDING},
            after=snapshot,
        )
        return change, event, False
