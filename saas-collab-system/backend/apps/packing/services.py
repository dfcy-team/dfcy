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
from apps.common.exceptions import (
    BusinessRuleViolation,
    ScopedResourceNotFound,
    StateConflict,
    VersionConflict,
)
from apps.masterdata.models import StatusChoices, SupplierMaster
from apps.purchasing.models import (
    SupplyFulfillmentEvent,
    SupplyOrderLineFulfillment,
    SupplyPurchaseOrder,
    SupplyPurchaseOrderLine,
    _supply_action_write_context,
)

from .models import (
    PackingBatch,
    PackingBatchOrder,
    PackingBatchLineAllocation,
    PackingBox,
    PackingBoxConsumption,
    PackingBoxConsumptionAction,
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


def find_current_packing_standard():
    return PackingStandardVersion.objects.filter(
        code=DEFAULT_STANDARD_CODE,
        is_active=True,
    ).order_by("-version").first()


def _require_current_packing_standard():
    standard = find_current_packing_standard()
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
        # Historical order links remain part of the audit/data-scope identity
        # after cancellation.  ``active_guard`` is retained only as a
        # compatibility marker and is intentionally not used for snapshots.
        "order_ids": list(
            batch.batch_orders.order_by("order_id").values_list("order_id", flat=True)
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
        PackingBatchOrder.objects.filter(batch=batch)
        .order_by("order_id")
        .values_list("order_id", flat=True)
    )


def _lock_linked_lines(batch):
    # Lock order -> line -> projection in a stable primary-key order.  The
    # active marker is not an authorization/data-scope filter; canceled links
    # are still valid historical line identities.
    order_ids = list(
        PackingBatchOrder.objects.filter(batch=batch)
        .order_by("order_id")
        .values_list("order_id", flat=True)
    )
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
    if lines:
        _ensure_line_projections(lines)
    return {line.id: line for line in lines}


def _ensure_line_projections(lines):
    """Ensure a projection exists for every locked line and lock it."""

    projections = []
    with _supply_action_write_context():
        for line in lines:
            projection, _ = SupplyOrderLineFulfillment.objects.get_or_create(
                order_line=line,
                defaults={
                    "tenant": line.tenant,
                    "order": line.order,
                    "ordered_quantity": line.quantity,
                    "production_completed_quantity": (
                        line.quantity
                        if line.order.completed_quantity >= line.order.total_quantity
                        else 0
                    ),
                    "migration_classification": (
                        SupplyOrderLineFulfillment.MigrationClassification.LEGACY_FULL_ORDER
                        if line.order.completed_quantity >= line.order.total_quantity
                        else SupplyOrderLineFulfillment.MigrationClassification.LEGACY_ZERO
                    ),
                    "needs_manual_allocation": (
                        0 < line.order.completed_quantity < line.order.total_quantity
                    ),
                },
            )
            projections.append(projection)
    # Projection rows are selected after get_or_create so callers always hold
    # row locks before quantity arithmetic.
    locked = list(
        SupplyOrderLineFulfillment.objects.select_for_update()
        .filter(pk__in=[projection.pk for projection in projections])
        .order_by("pk")
    )
    return {projection.order_line_id: projection for projection in locked}


def _projection_snapshot(projection):
    return {
        "production_completed_quantity": int(projection.production_completed_quantity),
        "packing_reserved_quantity": int(projection.packing_reserved_quantity),
        "packed_quantity": int(projection.packed_quantity),
        "shipped_quantity": int(projection.shipped_quantity),
        "warehouse_received_quantity": int(projection.warehouse_received_quantity),
        "warehouse_cleared_quantity": int(projection.warehouse_cleared_quantity),
        "version": int(projection.version),
    }


def _write_fulfillment_event(
    *,
    projection,
    actor,
    action,
    delta_quantity,
    source_type,
    source_id,
    source_version,
    idempotency_key,
    before,
    after,
    reason="",
    reverse_of=None,
    channel="internal",
):
    if not delta_quantity:
        return None
    # A single packing action can touch multiple lines.  The deterministic
    # per-line suffix preserves the global tenant/idempotency uniqueness while
    # keeping replay keys stable.
    # Derive a globally unique, deterministic key for every line/action pair.
    # One packing request can touch multiple lines and the same source action
    # can be emitted again by a later, independent request; including the
    # action keeps those events distinct while preserving idempotent replay.
    event_key = (
        f"{idempotency_key}:line:{projection.order_line_id}:action:{str(action)}"
    )
    try:
        with _supply_action_write_context():
            return SupplyFulfillmentEvent.objects.create(
                tenant=projection.tenant,
                order=projection.order,
                order_line=projection.order_line,
                stage=SupplyFulfillmentEvent.Stage.PACKING,
                delta_quantity=int(delta_quantity),
                source_type=source_type,
                source_id=str(source_id),
                source_version=int(source_version),
                action=action,
                actor=actor,
                channel=channel,
                reason=reason,
                idempotency_key=event_key,
                before_snapshot=before,
                after_snapshot=after,
                reverse_of=reverse_of,
                occurred_at=timezone.now(),
            )
    except IntegrityError:
        existing = SupplyFulfillmentEvent.objects.filter(
            tenant=projection.tenant,
            idempotency_key=event_key,
        ).first()
        if existing and existing.after_snapshot == after:
            return existing
        raise


def _allocation_totals(batch):
    return {
        row["order_line_id"]: int(row["total"] or 0)
        for row in PackingBoxItem.objects.filter(box__batch=batch)
        .values("order_line_id")
        .annotate(total=Sum("quantity"))
    }


def _refresh_batch_reservations(batch, lines, *, actor, idempotency_key):
    """Synchronize allocation rows and projection reserved quantities.

    ``batch`` is locked by the caller and ``lines``/projections are locked by
    ``_lock_linked_lines``.  The helper therefore performs no unordered
    queries and is safe for competing box mutations.
    """

    projections = _ensure_line_projections(list(lines.values()))
    desired = _allocation_totals(batch)
    now = timezone.now()
    for line_id, line in sorted(lines.items()):
        quantity = desired.get(line_id, 0)
        allocation = (
            PackingBatchLineAllocation.objects.select_for_update()
            .filter(batch=batch, order_line_id=line_id)
            .first()
        )
        if quantity <= 0:
            if allocation and allocation.state == PackingBatchLineAllocation.State.RESERVED:
                # A draft allocation has no useful history until it is frozen;
                # remove the zero row so the DB positive-quantity invariant is
                # preserved.  Cancellation uses the dedicated release helper.
                old_quantity = int(allocation.quantity)
                allocation.delete()
                if old_quantity:
                    projection = projections[line_id]
                    before = _projection_snapshot(projection)
                    if projection.packing_reserved_quantity < old_quantity:
                        raise StateConflict(
                            "Packing reservation projection is inconsistent with box removal."
                        )
                    projection.packing_reserved_quantity -= old_quantity
                    projection.version += 1
                    with _supply_action_write_context():
                        projection.save(
                            update_fields=[
                                "packing_reserved_quantity",
                                "version",
                                "updated_at",
                            ]
                        )
                    _write_fulfillment_event(
                        projection=projection,
                        actor=actor,
                        action=SupplyFulfillmentEvent.Action.RELEASE_PACKING,
                        delta_quantity=-old_quantity,
                        source_type="packing_batch",
                        source_id=str(batch.id),
                        source_version=batch.version + 1,
                        idempotency_key=f"{idempotency_key}:reserve",
                        before=before,
                        after=_projection_snapshot(projection),
                    )
            continue
        before_quantity = int(allocation.quantity) if allocation and allocation.state == PackingBatchLineAllocation.State.RESERVED else 0
        if allocation is None:
            allocation = PackingBatchLineAllocation(
                tenant=batch.tenant,
                batch=batch,
                order_line=line,
                quantity=quantity,
                state=PackingBatchLineAllocation.State.RESERVED,
                allocation_version=batch.version + 1,
                created_by=actor,
            )
            allocation.save()
        else:
            if allocation.state != PackingBatchLineAllocation.State.RESERVED:
                raise StateConflict("A frozen or released allocation cannot be edited.")
            allocation.quantity = quantity
            allocation.allocation_version += 1
            allocation.save(update_fields=["quantity", "allocation_version"])
        delta = quantity - before_quantity
        if delta:
            projection = projections[line_id]
            before = _projection_snapshot(projection)
            projection.packing_reserved_quantity += delta
            if projection.packing_reserved_quantity + projection.packed_quantity > projection.production_completed_quantity:
                raise StateConflict(
                    f"Packing reservation for order line {line_id} exceeds production quantity."
                )
            projection.version += 1
            with _supply_action_write_context():
                projection.save(update_fields=["packing_reserved_quantity", "version", "updated_at"])
            _write_fulfillment_event(
                projection=projection,
                actor=actor,
                action=(
                    SupplyFulfillmentEvent.Action.RESERVE_PACKING
                    if delta > 0
                    else SupplyFulfillmentEvent.Action.RELEASE_PACKING
                ),
                delta_quantity=delta,
                source_type="packing_batch",
                source_id=str(batch.id),
                source_version=batch.version + 1,
                idempotency_key=f"{idempotency_key}:reserve",
                before=before,
                after=_projection_snapshot(projection),
            )
    return projections


def _freeze_batch_allocations(batch, lines, *, actor, idempotency_key):
    """Convert this batch's reservations into immutable packed quantity."""

    projections = _ensure_line_projections(list(lines.values()))
    now = timezone.now()
    allocations = list(
        PackingBatchLineAllocation.objects.select_for_update()
        .filter(batch=batch, state=PackingBatchLineAllocation.State.RESERVED)
        .order_by("pk")
    )
    if not allocations:
        raise BusinessRuleViolation("A packing batch must contain at least one allocated quantity.")
    for allocation in allocations:
        projection = projections[allocation.order_line_id]
        quantity = int(allocation.quantity)
        before = _projection_snapshot(projection)
        if projection.packing_reserved_quantity < quantity:
            raise StateConflict("Packing reservation projection is inconsistent with the batch allocation.")
        projection.packing_reserved_quantity -= quantity
        projection.packed_quantity += quantity
        if projection.packing_reserved_quantity + projection.packed_quantity > projection.production_completed_quantity:
            raise StateConflict("Packed quantity exceeds production completed quantity.")
        projection.version += 1
        with _supply_action_write_context():
            projection.save(
                update_fields=[
                    "packing_reserved_quantity",
                    "packed_quantity",
                    "version",
                    "updated_at",
                ]
            )
        allocation.state = PackingBatchLineAllocation.State.FROZEN
        allocation.frozen_at = now
        allocation.allocation_version += 1
        allocation.save(update_fields=["state", "frozen_at", "allocation_version"])
        _write_fulfillment_event(
            projection=projection,
            actor=actor,
            action=SupplyFulfillmentEvent.Action.FREEZE_PACKING,
            delta_quantity=quantity,
            source_type="packing_batch",
            source_id=str(batch.id),
            source_version=batch.version + 1,
            idempotency_key=f"{idempotency_key}:freeze",
            before=before,
            after=_projection_snapshot(projection),
        )
    return allocations


def _validate_quantities(batch, normalized_items, lines, *, excluded_box_id=None, require_exact=False):
    requested = {item["order_line_id"]: item["quantity"] for item in normalized_items}
    unknown = sorted(set(requested) - set(lines))
    if unknown:
        raise BusinessRuleViolation(f"Order lines are not linked to this packing batch: {unknown}")

    packed_query = PackingBoxItem.objects.filter(box__batch=batch)
    excluded_packed = {}
    if excluded_box_id is not None:
        excluded_packed = {
            row["order_line_id"]: int(row["total"] or 0)
            for row in PackingBoxItem.objects.filter(box_id=excluded_box_id)
            .values("order_line_id")
            .annotate(total=Sum("quantity"))
        }
    if excluded_box_id is not None:
        packed_query = packed_query.exclude(box_id=excluded_box_id)
    packed = {
        row["order_line_id"]: row["total"]
        for row in packed_query.values("order_line_id").annotate(total=Sum("quantity"))
    }
    projections = _ensure_line_projections(list(lines.values())) if lines else {}
    for line_id, quantity in requested.items():
        projection = projections.get(line_id)
        if projection is None:
            raise BusinessRuleViolation(f"No fulfillment projection exists for order line {line_id}.")
        if projection.needs_manual_allocation:
            raise StateConflict(
                f"Production quantity for order line {line_id} requires manual legacy allocation before packing."
            )
        # ``packing_reserved_quantity`` includes boxes in this batch and all
        # concurrent batches.  Replacing a box excludes its old quantity from
        # the projection before applying the new request.
        reserved_total = int(projection.packing_reserved_quantity)
        if excluded_box_id is not None:
            reserved_total -= int(excluded_packed.get(line_id, 0))
        if reserved_total + int(projection.packed_quantity) + quantity > int(projection.production_completed_quantity):
            raise StateConflict(
                f"Packing quantity for order line {line_id} exceeds production completed quantity."
            )

    if require_exact and normalized_items:
        final = dict(packed)
        for line_id, quantity in requested.items():
            final[line_id] = final.get(line_id, 0) + quantity
        # A completed batch is a partial fulfillment projection.  ``require_exact``
        # is retained for callers from the pre-MULTI API but is no longer an
        # order-wide equality requirement; only positive box contents are
        # checked below by the completion action.
        mismatched = [line.id for line in lines.values() if final.get(line.id, 0) <= 0]
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
            partially_migrated = [
                order.id
                for order in orders
                if int(order.completed_quantity or 0) < int(order.total_quantity)
            ]
            if partially_migrated:
                raise StateConflict(
                    "Legacy partial production orders require manual line allocation before packing: "
                    f"{partially_migrated}"
                )
            undecided_routes = [
                order.id
                for order in orders
                if order.shipping_route == SupplyPurchaseOrder.ShippingRoute.UNDECIDED
            ]
            if undecided_routes:
                raise StateConflict(
                    f"Purchase orders require a purchasing shipping-route decision before packing: {undecided_routes}"
                )
            shipping_routes = {order.shipping_route for order in orders}
            if len(shipping_routes) != 1:
                raise BusinessRuleViolation(
                    "A packing batch cannot mix loose-cargo and container-cargo purchase orders."
                )
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
                standard_version=_require_current_packing_standard(),
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
            # Materialize one projection per order line at the point where a
            # batch first references the order.  Creation itself reserves no
            # quantity; box actions add the explicit line reservations.
            _lock_linked_lines(batch)
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
    except (IntegrityError, DjangoValidationError):
        # On MySQL a concurrent insert may wait for the winner's unique-key
        # lock and then fail during ``Model.full_clean(validate_unique=True)``
        # before the database emits IntegrityError.  Resolve both paths to
        # the same deterministic idempotent replay when the committed row
        # belongs to this actor and carries the same request hash; unrelated
        # validation/conflict errors still propagate unchanged.
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
            raise VersionConflict("Packing batch version is stale.")
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
        _refresh_batch_reservations(
            batch,
            lines,
            actor=actor,
            idempotency_key=idempotency_key,
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
            raise VersionConflict("Packing batch version is stale.")
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
        _refresh_batch_reservations(
            batch,
            lines,
            actor=actor,
            idempotency_key=idempotency_key,
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
            raise VersionConflict("Packing batch version is stale.")
        if batch.status != PackingBatch.Status.IN_PROGRESS:
            raise StateConflict("Only in-progress packing batches can be changed.")
        box = PackingBox.objects.select_for_update().filter(pk=box_id, batch=batch).first()
        if box is None:
            raise ScopedResourceNotFound("Packing box is not available in this batch.")
        lines = _lock_linked_lines(batch)
        before = _batch_snapshot(batch)
        for item in list(box.items.all()):
            item.delete()
        box.delete()
        _refresh_batch_reservations(
            batch,
            lines,
            actor=actor,
            idempotency_key=idempotency_key,
        )
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
            raise VersionConflict("Packing batch version is stale.")
        if batch.status not in {PackingBatch.Status.DRAFT, PackingBatch.Status.IN_PROGRESS}:
            raise StateConflict("Only an unfinished packing batch can be completed.")
        lines = _lock_linked_lines(batch)
        boxes = list(
            PackingBox.objects.select_for_update()
            .filter(batch=batch)
            .prefetch_related("items")
            .order_by("pk")
        )
        if not boxes:
            raise BusinessRuleViolation("A packing batch cannot complete without boxes.")
        if any(not list(box.items.all()) for box in boxes):
            raise BusinessRuleViolation("A packing batch cannot complete with an empty box.")
        # Verify every current allocation against the locked production
        # projection; unlike the legacy service this intentionally allows a
        # partial batch and freezes only the quantities in its boxes.
        projections = _ensure_line_projections(list(lines.values()))
        for line_id, quantity in _allocation_totals(batch).items():
            projection = projections[line_id]
            if projection.needs_manual_allocation:
                raise StateConflict(
                    f"Production quantity for order line {line_id} requires manual legacy allocation before packing."
                )
            if projection.packing_reserved_quantity + projection.packed_quantity > projection.production_completed_quantity:
                raise StateConflict(
                    f"Packing quantity for order line {line_id} exceeds production quantity."
                )
        _refresh_batch_reservations(
            batch,
            lines,
            actor=actor,
            idempotency_key=idempotency_key,
        )
        before = _batch_snapshot(batch)
        _freeze_batch_allocations(
            batch,
            lines,
            actor=actor,
            idempotency_key=idempotency_key,
        )
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
            raise VersionConflict("Packing batch version is stale.")
        if batch.status not in {PackingBatch.Status.DRAFT, PackingBatch.Status.IN_PROGRESS}:
            raise StateConflict("Only unfinished packing batches can be cancelled.")
        lines = _lock_linked_lines(batch)
        projections = _ensure_line_projections(list(lines.values()))
        before = _batch_snapshot(batch)
        now = timezone.now()
        for allocation in list(
            PackingBatchLineAllocation.objects.select_for_update()
            .filter(batch=batch, state=PackingBatchLineAllocation.State.RESERVED)
            .order_by("pk")
        ):
            projection = projections[allocation.order_line_id]
            quantity = int(allocation.quantity)
            projection_before = _projection_snapshot(projection)
            if projection.packing_reserved_quantity < quantity:
                raise StateConflict("Packing reservation projection is inconsistent with cancellation.")
            projection.packing_reserved_quantity -= quantity
            projection.version += 1
            with _supply_action_write_context():
                projection.save(
                    update_fields=["packing_reserved_quantity", "version", "updated_at"]
                )
            allocation.state = PackingBatchLineAllocation.State.RELEASED
            allocation.released_at = now
            allocation.allocation_version += 1
            allocation.save(update_fields=["state", "released_at", "allocation_version"])
            _write_fulfillment_event(
                projection=projection,
                actor=actor,
                action=SupplyFulfillmentEvent.Action.RELEASE_PACKING,
                delta_quantity=-quantity,
                source_type="packing_batch",
                source_id=str(batch.id),
                source_version=batch.version + 1,
                idempotency_key=f"{idempotency_key}:release",
                before=projection_before,
                after=_projection_snapshot(projection),
            )
        for link in PackingBatchOrder.objects.select_for_update().filter(
            batch=batch,
        ):
            if link.active_guard is not None:
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
            raise VersionConflict("Packing batch version is stale.")
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


def _replace_completed_layout(batch, boxes, *, actor, idempotency_key):
    if PackingBoxConsumption.objects.filter(
        box__batch=batch,
        state__in=[
            PackingBoxConsumption.State.RESERVED,
            PackingBoxConsumption.State.COMMITTED,
        ],
        active_guard=True,
    ).exists():
        raise StateConflict("A completed layout cannot change after a box has been consumed downstream.")
    lines = _lock_linked_lines(batch)
    projections = _ensure_line_projections(list(lines.values()))
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
    if any(quantity <= 0 for quantity in merged.values()):
        raise BusinessRuleViolation("Completed layout quantities must be positive.")

    old_totals = _allocation_totals(batch)
    for line_id, quantity in merged.items():
        if line_id not in lines:
            raise BusinessRuleViolation(f"Order lines are not linked to this packing batch: {[line_id]}")
        projection = projections[line_id]
        # Remove this batch's old packed quantity from the projection before
        # checking the replacement.  No route/consumer mutation is allowed in
        # this operation, and shipped rows are therefore a hard boundary.
        available = (
            int(projection.production_completed_quantity)
            - int(projection.packing_reserved_quantity)
            - int(projection.packed_quantity)
            + int(old_totals.get(line_id, 0))
        )
        if int(quantity) > available:
            raise StateConflict(
                f"Replacement quantity for order line {line_id} exceeds production quantity."
            )
    omitted = set(old_totals) - set(merged)
    if omitted:
        # A zero-quantity replacement would remove frozen packed quantity. It
        # is valid only when no downstream consumer exists (checked above).
        pass

    now = timezone.now()
    for line_id, old_quantity in sorted(old_totals.items()):
        projection = projections[line_id]
        new_quantity = int(merged.get(line_id, 0))
        delta = new_quantity - int(old_quantity)
        if delta:
            before = _projection_snapshot(projection)
            if projection.packed_quantity < int(old_quantity):
                raise StateConflict("Packed projection is inconsistent with the completed layout.")
            projection.packed_quantity += delta
            if projection.packed_quantity < 0:
                raise StateConflict("A completed layout cannot reverse below zero packed quantity.")
            projection.version += 1
            with _supply_action_write_context():
                projection.save(update_fields=["packed_quantity", "version", "updated_at"])
            original = SupplyFulfillmentEvent.objects.filter(
                tenant=projection.tenant,
                order_line=projection.order_line,
                source_type="packing_batch",
                source_id=str(batch.id),
                action=SupplyFulfillmentEvent.Action.FREEZE_PACKING,
            ).order_by("-created_at", "-id").first()
            _write_fulfillment_event(
                projection=projection,
                actor=actor,
                action=(
                    SupplyFulfillmentEvent.Action.FREEZE_PACKING
                    if delta > 0
                    else SupplyFulfillmentEvent.Action.REVERSE_PACKING
                ),
                delta_quantity=delta,
                source_type="packing_change",
                source_id=str(batch.id),
                source_version=batch.version + 1,
                idempotency_key=f"{idempotency_key}:change",
                before=before,
                after=_projection_snapshot(projection),
                reason="Approved completed packing layout correction",
                reverse_of=original if delta < 0 else None,
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
    # Keep one allocation identity per batch/line.  Existing frozen rows are
    # updated to the new quantity; removed lines are marked reversed while
    # retaining their historical positive quantity.
    for line_id, old_quantity in sorted(old_totals.items()):
        allocation = PackingBatchLineAllocation.objects.select_for_update().filter(
            batch=batch, order_line_id=line_id
        ).first()
        if allocation is None:
            allocation = PackingBatchLineAllocation(
                tenant=batch.tenant,
                batch=batch,
                order_line=lines[line_id],
                quantity=int(old_quantity),
                state=PackingBatchLineAllocation.State.FROZEN,
                allocation_version=batch.version,
                created_by=actor,
                frozen_at=batch.completed_at or now,
            )
            allocation.save()
        new_quantity = int(merged.get(line_id, 0))
        allocation.allocation_version += 1
        if new_quantity:
            allocation.quantity = new_quantity
            allocation.state = PackingBatchLineAllocation.State.FROZEN
            allocation.frozen_at = now
            allocation.released_at = None
            allocation.save(
                update_fields=[
                    "quantity",
                    "state",
                    "frozen_at",
                    "released_at",
                    "allocation_version",
                ]
            )
        else:
            allocation.state = PackingBatchLineAllocation.State.REVERSED
            allocation.released_at = now
            allocation.save(update_fields=["state", "released_at", "allocation_version"])
    for line_id, new_quantity in sorted(merged.items()):
        if line_id in old_totals:
            continue
        allocation = PackingBatchLineAllocation(
            tenant=batch.tenant,
            batch=batch,
            order_line=lines[line_id],
            quantity=int(new_quantity),
            state=PackingBatchLineAllocation.State.FROZEN,
            allocation_version=batch.version + 1,
            created_by=actor,
            frozen_at=now,
        )
        allocation.save()


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
            raise VersionConflict("Packing batch changed after this request was submitted.")
        before = _batch_snapshot(batch)
        _replace_completed_layout(
            batch,
            change.proposed_boxes,
            actor=reviewer,
            idempotency_key=idempotency_key,
        )
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


def _validate_consumer_identity(consumer_type, consumer_id, consumer_version):
    if consumer_type not in PackingBoxConsumption.ConsumerType.values:
        raise ValidationError({"consumer_type": "Unsupported box consumer type."})
    if isinstance(consumer_id, bool) or int(consumer_id) <= 0:
        raise ValidationError({"consumer_id": "A positive consumer ID is required."})
    if isinstance(consumer_version, bool) or int(consumer_version) <= 0:
        raise ValidationError({"consumer_version": "A positive consumer version is required."})


def _consumption_replay(existing, *, actor, action, request_hash):
    if existing is None:
        return None
    if existing.actor_id != actor.id:
        raise StateConflict("The box consumption idempotency key belongs to another actor.")
    if existing.request_hash != request_hash:
        # ``reason`` is intentionally not exposed as a request hash in API
        # DTOs; this internal field comparison protects same-key conflicts.
        raise StateConflict("The box consumption idempotency key was reused with another payload.")
    if action == "reserve":
        return existing, True
    return existing, True


def _consumption_state_snapshot(consumption):
    """Small immutable snapshot stored with a downstream action result."""

    return {
        "id": int(consumption.id),
        "box_id": int(consumption.box_id),
        "consumer_type": str(consumption.consumer_type),
        "consumer_id": int(consumption.consumer_id),
        "consumer_version": int(consumption.consumer_version),
        "state": str(consumption.state),
        "active_guard": consumption.active_guard,
        "transferred_from_id": (
            int(consumption.transferred_from_id)
            if consumption.transferred_from_id
            else None
        ),
    }


def _load_consumption_action(*, tenant, idempotency_key, action, actor, request_hash):
    """Return a replay result or raise a same-key conflict.

    Action rows are locked before inspecting them so concurrent retries either
    observe the committed result or wait for the original transaction.
    """

    record = (
        PackingBoxConsumptionAction.objects.select_for_update()
        .filter(tenant=tenant, idempotency_key=idempotency_key)
        .first()
    )
    if record is None:
        return None
    if record.action != action or record.actor_id != actor.id:
        raise StateConflict("The box consumption action idempotency key belongs to another action or actor.")
    if record.request_hash != request_hash:
        raise StateConflict("The box consumption action idempotency key was reused with another payload.")
    result_id = record.result_consumption_id or record.consumption_id
    result = PackingBoxConsumption.objects.select_for_update().get(pk=result_id)
    return result, True


def _append_consumption_action(
    *,
    tenant,
    consumption,
    action,
    idempotency_key,
    request_hash,
    actor,
    before,
    after,
    result_consumption=None,
):
    """Append the action result, tolerating a concurrent identical insert."""

    try:
        with _packing_domain_write_context():
            return PackingBoxConsumptionAction.objects.create(
                tenant=tenant,
                consumption=consumption,
                action=action,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                actor=actor,
                result_consumption=result_consumption or consumption,
                before_state=before,
                after_state=after,
            )
    except IntegrityError:
        existing = (
            PackingBoxConsumptionAction.objects.select_for_update()
            .filter(tenant=tenant, idempotency_key=idempotency_key)
            .first()
        )
        if existing is None:
            raise
        if (
            existing.action != action
            or existing.actor_id != actor.id
            or existing.request_hash != request_hash
        ):
            raise StateConflict("The box consumption action idempotency key was reused with another payload.")
        return existing


@packing_domain_action
def reserve_box_consumption(
    *,
    box_id,
    consumer_type,
    consumer_id,
    actor,
    idempotency_key,
    consumer_version=1,
    reason="",
):
    """Reserve the only active downstream consumer slot for a completed box."""

    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    _validate_consumer_identity(consumer_type, consumer_id, consumer_version)
    request_hash = _canonical_hash(
        {
            "box_id": int(box_id),
            "consumer_type": consumer_type,
            "consumer_id": int(consumer_id),
            "consumer_version": int(consumer_version),
            "reason": str(reason or ""),
        }
    )
    with transaction.atomic():
        existing = PackingBoxConsumption.objects.select_for_update().filter(
            tenant=actor.tenant,
            idempotency_key=idempotency_key,
        ).first()
        if existing:
            if existing.request_hash != request_hash or existing.actor_id != actor.id:
                raise StateConflict("The box consumption idempotency key was reused with another payload.")
            return existing, True
        box_ref = PackingBox.objects.select_related("batch").filter(
            pk=box_id, tenant=actor.tenant
        ).first()
        if box_ref is None:
            raise ScopedResourceNotFound("Packing box is not available in the authorized tenant.")
        batch = _locked_batch(batch_id=box_ref.batch_id, actor=actor)
        box = PackingBox.objects.select_for_update().filter(
            pk=box_id, tenant=actor.tenant, batch_id=batch.id
        ).first()
        if box is None:
            raise ScopedResourceNotFound("Packing box is not available in the authorized tenant.")
        if batch.status != PackingBatch.Status.COMPLETED:
            raise StateConflict("Only completed boxes can be consumed downstream.")
        active = PackingBoxConsumption.objects.select_for_update().filter(
            box=box,
            active_guard=True,
        ).first()
        if active:
            raise StateConflict("The packing box already has an active downstream consumer.")
        consumption = PackingBoxConsumption(
            tenant=actor.tenant,
            box=box,
            consumer_type=consumer_type,
            consumer_id=int(consumer_id),
            consumer_version=int(consumer_version),
            state=PackingBoxConsumption.State.RESERVED,
            active_guard=True,
            idempotency_key=idempotency_key,
            actor=actor,
            reason=str(reason or ""),
            request_hash=request_hash,
        )
        consumption.save()
        return consumption, False


@packing_domain_action
def commit_box_consumption(*, consumption_id, actor, idempotency_key, reason=""):
    """Commit a reserved box consumer and advance shipped quantities once.

    Consolidation confirmation is deliberately distinct from shipment: only
    a shipment consumer commit advances the shipped projection.
    """

    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    request_hash = _canonical_hash(
        {"consumption_id": int(consumption_id), "reason": str(reason or "")}
    )
    with transaction.atomic():
        replay = _load_consumption_action(
            tenant=actor.tenant,
            idempotency_key=idempotency_key,
            action=PackingBoxConsumptionAction.Action.COMMIT,
            actor=actor,
            request_hash=request_hash,
        )
        if replay is not None:
            return replay
        existing = PackingBoxConsumption.objects.select_for_update().filter(
            tenant=actor.tenant,
            idempotency_key=idempotency_key,
        ).first()
        if existing:
            if existing.request_hash != request_hash or existing.actor_id != actor.id:
                raise StateConflict("The box consumption idempotency key was reused with another payload.")
            return existing, True
        consumption_ref = PackingBoxConsumption.objects.filter(
            pk=consumption_id, tenant=actor.tenant
        ).first()
        if consumption_ref is None:
            raise ScopedResourceNotFound("Box consumption is not available in the authorized tenant.")
        batch = _locked_batch(batch_id=consumption_ref.box.batch_id, actor=actor)
        consumption = PackingBoxConsumption.objects.select_for_update().filter(
            pk=consumption_id, tenant=actor.tenant
        ).first()
        if consumption is None:
            raise ScopedResourceNotFound("Box consumption is not available in the authorized tenant.")
        consumption.box = PackingBox.objects.select_for_update().get(pk=consumption.box_id)
        if consumption.state != PackingBoxConsumption.State.RESERVED:
            raise StateConflict("Only a reserved box consumer can be committed.")
        before_consumption = _consumption_state_snapshot(consumption)
        lines = _lock_linked_lines(batch)
        projections = _ensure_line_projections(list(lines.values()))
        if consumption.consumer_type == PackingBoxConsumption.ConsumerType.SHIPMENT:
            for item in PackingBoxItem.objects.select_for_update().filter(box=consumption.box).order_by("pk"):
                projection = projections[item.order_line_id]
                if projection.shipped_quantity + item.quantity > projection.packed_quantity:
                    raise StateConflict("Shipped quantity cannot exceed packed quantity.")
                before = _projection_snapshot(projection)
                projection.shipped_quantity += item.quantity
                projection.version += 1
                with _supply_action_write_context():
                    projection.save(update_fields=["shipped_quantity", "version", "updated_at"])
                _write_fulfillment_event(
                    projection=projection,
                    actor=actor,
                    action=SupplyFulfillmentEvent.Action.SHIP,
                    delta_quantity=item.quantity,
                    source_type="packing_box_consumption",
                    source_id=str(consumption.id),
                    source_version=consumption.consumer_version,
                    idempotency_key=f"{idempotency_key}:ship",
                    before=before,
                    after=_projection_snapshot(projection),
                    reason=str(reason or ""),
                )
        consumption.state = PackingBoxConsumption.State.COMMITTED
        consumption.committed_at = timezone.now()
        consumption.reason = str(reason or "")
        consumption.request_hash = request_hash
        consumption.save(update_fields=["state", "committed_at", "reason", "request_hash"])
        _append_consumption_action(
            tenant=actor.tenant,
            consumption=consumption,
            action=PackingBoxConsumptionAction.Action.COMMIT,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            actor=actor,
            before=before_consumption,
            after=_consumption_state_snapshot(consumption),
            result_consumption=consumption,
        )
        return consumption, False


@packing_domain_action
def release_box_consumption(*, consumption_id, actor, idempotency_key, reason=""):
    """Release an uncommitted consumer slot without changing packed quantity."""

    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    request_hash = _canonical_hash(
        {"consumption_id": int(consumption_id), "reason": str(reason or "")}
    )
    with transaction.atomic():
        replay = _load_consumption_action(
            tenant=actor.tenant,
            idempotency_key=idempotency_key,
            action=PackingBoxConsumptionAction.Action.RELEASE,
            actor=actor,
            request_hash=request_hash,
        )
        if replay is not None:
            return replay
        existing = PackingBoxConsumption.objects.select_for_update().filter(
            tenant=actor.tenant,
            idempotency_key=idempotency_key,
        ).first()
        if existing:
            if existing.request_hash != request_hash or existing.actor_id != actor.id:
                raise StateConflict("The box consumption idempotency key was reused with another payload.")
            return existing, True
        consumption_ref = PackingBoxConsumption.objects.filter(
            pk=consumption_id,
            tenant=actor.tenant,
        ).first()
        if consumption_ref is None:
            raise ScopedResourceNotFound("Box consumption is not available in the authorized tenant.")
        _locked_batch(batch_id=consumption_ref.box.batch_id, actor=actor)
        consumption = PackingBoxConsumption.objects.select_for_update().filter(
            pk=consumption_id,
            tenant=actor.tenant,
        ).first()
        if consumption is None:
            raise ScopedResourceNotFound("Box consumption is not available in the authorized tenant.")
        consumption.box = PackingBox.objects.select_for_update().get(pk=consumption.box_id)
        if consumption.state != PackingBoxConsumption.State.RESERVED:
            raise StateConflict("Only a reserved box consumer can be released.")
        before_consumption = _consumption_state_snapshot(consumption)
        consumption.state = PackingBoxConsumption.State.RELEASED
        consumption.active_guard = None
        consumption.released_at = timezone.now()
        consumption.reason = str(reason or "")
        consumption.request_hash = request_hash
        consumption.save(update_fields=["state", "active_guard", "released_at", "reason", "request_hash"])
        _append_consumption_action(
            tenant=actor.tenant,
            consumption=consumption,
            action=PackingBoxConsumptionAction.Action.RELEASE,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            actor=actor,
            before=before_consumption,
            after=_consumption_state_snapshot(consumption),
            result_consumption=consumption,
        )
        return consumption, False


@packing_domain_action
def transfer_box_consumption(
    *,
    consumption_id,
    target_consumer_type,
    target_consumer_id,
    actor,
    idempotency_key,
    target_consumer_version=1,
    reason="",
):
    """Atomically transfer a reserved box from consolidation to shipment."""

    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    _validate_consumer_identity(
        target_consumer_type, target_consumer_id, target_consumer_version
    )
    request_hash = _canonical_hash(
        {
            "consumption_id": int(consumption_id),
            "target_consumer_type": target_consumer_type,
            "target_consumer_id": int(target_consumer_id),
            "target_consumer_version": int(target_consumer_version),
            "reason": str(reason or ""),
        }
    )
    with transaction.atomic():
        replay = _load_consumption_action(
            tenant=actor.tenant,
            idempotency_key=idempotency_key,
            action=PackingBoxConsumptionAction.Action.TRANSFER,
            actor=actor,
            request_hash=request_hash,
        )
        if replay is not None:
            return replay
        existing = PackingBoxConsumption.objects.select_for_update().filter(
            tenant=actor.tenant,
            idempotency_key=idempotency_key,
        ).first()
        if existing:
            if existing.request_hash != request_hash or existing.actor_id != actor.id:
                raise StateConflict("The box consumption idempotency key was reused with another payload.")
            return existing, True
        source_ref = PackingBoxConsumption.objects.filter(
            pk=consumption_id, tenant=actor.tenant
        ).first()
        if source_ref is None:
            raise ScopedResourceNotFound("Box consumption is not available in the authorized tenant.")
        _locked_batch(batch_id=source_ref.box.batch_id, actor=actor)
        source = PackingBoxConsumption.objects.select_for_update().filter(
            pk=consumption_id, tenant=actor.tenant
        ).first()
        if source is None:
            raise ScopedResourceNotFound("Box consumption is not available in the authorized tenant.")
        source.box = PackingBox.objects.select_for_update().get(pk=source.box_id)
        if source.consumer_type != PackingBoxConsumption.ConsumerType.CONSOLIDATION:
            raise StateConflict("Only a consolidation consumer can be transferred to shipment.")
        if target_consumer_type != PackingBoxConsumption.ConsumerType.SHIPMENT:
            raise StateConflict("A consolidation transfer target must be a shipment consumer.")
        if source.state not in {
            PackingBoxConsumption.State.RESERVED,
            PackingBoxConsumption.State.COMMITTED,
        } or source.active_guard is not True:
            raise StateConflict("Only an active reserved or committed consumer can be transferred.")
        before_source = _consumption_state_snapshot(source)
        # End the old slot first.  The nullable guard allows the new active
        # row to be inserted under MySQL's unique key without ever exposing
        # two active rows in a committed transaction.
        source.state = PackingBoxConsumption.State.RELEASED
        source.active_guard = None
        source.released_at = timezone.now()
        source.reason = str(reason or "")
        source.request_hash = request_hash
        source.save(update_fields=["state", "active_guard", "released_at", "reason", "request_hash"])
        target_key = idempotency_key
        target = PackingBoxConsumption(
            tenant=actor.tenant,
            box=source.box,
            consumer_type=target_consumer_type,
            consumer_id=int(target_consumer_id),
            consumer_version=int(target_consumer_version),
            state=PackingBoxConsumption.State.RESERVED,
            active_guard=True,
            idempotency_key=target_key,
            actor=actor,
            transferred_from=source,
            reason=str(reason or ""),
            request_hash=request_hash,
        )
        target.save()
        _append_consumption_action(
            tenant=actor.tenant,
            consumption=source,
            action=PackingBoxConsumptionAction.Action.TRANSFER,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            actor=actor,
            before=before_source,
            after=_consumption_state_snapshot(target),
            result_consumption=target,
        )
        return target, False


# Friendly aliases used by downstream consolidation/shipment work.  Keeping
# the names here avoids coupling this F2 core to concrete downstream models.
reserve_box = reserve_box_consumption
commit_box = commit_box_consumption
release_box = release_box_consumption
transfer_box = transfer_box_consumption
reserve_packing_box = reserve_box_consumption
commit_packing_box = commit_box_consumption
release_packing_box = release_box_consumption
transfer_packing_box = transfer_box_consumption
reserve_box_for_consumer = reserve_box_consumption
commit_box_for_consumer = commit_box_consumption
release_box_for_consumer = release_box_consumption
transfer_box_consumer = transfer_box_consumption
