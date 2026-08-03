import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.audit.services import write_operation_log
from apps.common.exceptions import ScopedResourceNotFound, StateConflict

from .models import (
    SupplyProductionProgress,
    SupplyPurchaseOrder,
    SupplyPurchaseOrderEvent,
    _supply_action_write_context,
)
from .supply_serializers import (
    SupplierSupplyPurchaseOrderSerializer,
    SupplyPurchaseOrderDetailSerializer,
)


ACTION_TRANSITIONS = {
    SupplyPurchaseOrderEvent.Action.ACCEPT: (
        SupplyPurchaseOrder.Status.PENDING,
        SupplyPurchaseOrder.Status.ACCEPTED,
    ),
    SupplyPurchaseOrderEvent.Action.START_PRODUCTION: (
        SupplyPurchaseOrder.Status.ACCEPTED,
        SupplyPurchaseOrder.Status.IN_PRODUCTION,
    ),
    SupplyPurchaseOrderEvent.Action.UPDATE_PROGRESS: (
        SupplyPurchaseOrder.Status.IN_PRODUCTION,
        SupplyPurchaseOrder.Status.IN_PRODUCTION,
    ),
    SupplyPurchaseOrderEvent.Action.COMPLETE_PRODUCTION: (
        SupplyPurchaseOrder.Status.IN_PRODUCTION,
        SupplyPurchaseOrder.Status.PRODUCTION_COMPLETED,
    ),
}


def _total_quantity(order):
    return order.lines.aggregate(total=Sum("quantity"))["total"] or 0


def _request_metadata(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip_address = forwarded.split(",", 1)[0].strip() if forwarded else request.META.get("REMOTE_ADDR")
    return {
        "ip_address": ip_address or None,
        "user_agent": request.META.get("HTTP_USER_AGENT", "")[:1000],
    }


def _action_request_hash(action, *, completed_quantity=None, note=""):
    payload = {"action": str(action)}
    if action == SupplyPurchaseOrderEvent.Action.UPDATE_PROGRESS:
        payload.update(
            {
                "completed_quantity": completed_quantity,
                "note": note,
            }
        )
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _snapshot_order_response(order_id, *, supplier):
    order = (
        SupplyPurchaseOrder.objects.select_related("tenant", "supplier", "created_by")
        .prefetch_related("lines", "lines__sku", "progress_entries", "events")
        .get(pk=order_id)
    )
    serializer_class = (
        SupplierSupplyPurchaseOrderSerializer
        if supplier
        else SupplyPurchaseOrderDetailSerializer
    )
    return json.loads(json.dumps(serializer_class(order).data))


@transaction.atomic
def perform_supply_order_action(
    *,
    order_id,
    actor,
    action,
    idempotency_key,
    request,
    supplier_id=None,
    completed_quantity=None,
    note="",
):
    if action not in ACTION_TRANSITIONS:
        raise ValidationError({"action": "Unsupported supply purchase order action."})
    if not idempotency_key or len(idempotency_key) > 128:
        raise ValidationError({"idempotency_key": "A valid Idempotency-Key header is required."})
    request_hash = _action_request_hash(
        action,
        completed_quantity=completed_quantity,
        note=note,
    )

    queryset = SupplyPurchaseOrder.objects.select_for_update().filter(
        pk=order_id,
        tenant=actor.tenant,
    )
    if supplier_id is not None:
        queryset = queryset.filter(supplier_id=supplier_id)
    order = queryset.first()
    if order is None:
        raise ScopedResourceNotFound("Supply purchase order is not available in the authorized scope.")

    existing_event = SupplyPurchaseOrderEvent.objects.filter(
        order=order,
        idempotency_key=idempotency_key,
    ).first()
    if existing_event:
        if existing_event.action != action:
            raise StateConflict("The idempotency key was already used for a different action.")
        if existing_event.actor_id != actor.id:
            raise StateConflict("The idempotency key belongs to a different actor.")
        if existing_event.request_hash and existing_event.request_hash != request_hash:
            raise StateConflict("The idempotency key was already used with a different action payload.")
        return order, existing_event, True

    expected_status, next_status = ACTION_TRANSITIONS[action]
    if order.status != expected_status:
        raise StateConflict(
            f"Action {action} requires status {expected_status}; current status is {order.status}."
        )

    total_quantity = _total_quantity(order)
    if total_quantity <= 0:
        raise StateConflict("A supply purchase order must contain at least one positive-quantity line.")

    before_status = order.status
    before_completed_quantity = order.completed_quantity
    payload = {}
    now = timezone.now()
    if action == SupplyPurchaseOrderEvent.Action.ACCEPT:
        order.accepted_at = now
    elif action == SupplyPurchaseOrderEvent.Action.START_PRODUCTION:
        order.production_started_at = now
    elif action == SupplyPurchaseOrderEvent.Action.UPDATE_PROGRESS:
        if completed_quantity is None:
            raise ValidationError({"completed_quantity": "Completed quantity is required."})
        if completed_quantity < order.completed_quantity:
            raise StateConflict("Completed quantity cannot move backwards.")
        if completed_quantity > total_quantity:
            raise StateConflict("Completed quantity cannot exceed the order total quantity.")
        order.completed_quantity = completed_quantity
        percent = (
            Decimal(completed_quantity) * Decimal("100") / Decimal(total_quantity)
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        SupplyProductionProgress.objects.create(
            tenant=order.tenant,
            order=order,
            completed_quantity=completed_quantity,
            progress_percent=percent,
            note=note,
            actor=actor,
            request_id=idempotency_key,
        )
        payload = {
            "completed_quantity": completed_quantity,
            "progress_percent": str(percent),
            "note": note,
        }
    elif action == SupplyPurchaseOrderEvent.Action.COMPLETE_PRODUCTION:
        if order.completed_quantity != total_quantity:
            raise StateConflict("Production can only complete when completed quantity equals total quantity.")
        order.production_completed_at = now

    order.status = next_status
    order.version += 1
    with _supply_action_write_context():
        order.save(
            update_fields=[
                "status",
                "accepted_at",
                "production_started_at",
                "production_completed_at",
                "completed_quantity",
                "version",
                "updated_at",
            ]
        )

    actor_type = (
        SupplyPurchaseOrderEvent.ActorType.INTERNAL
        if actor.user_type == "internal"
        else SupplyPurchaseOrderEvent.ActorType.SUPPLIER
    )
    with _supply_action_write_context():
        event = SupplyPurchaseOrderEvent.objects.create(
            tenant=order.tenant,
            order=order,
            action=action,
            idempotency_key=idempotency_key,
            actor=actor,
            actor_type=actor_type,
            before_status=before_status,
            after_status=order.status,
            payload=payload,
            request_hash=request_hash,
        )
    metadata = _request_metadata(request)
    write_operation_log(
        tenant=order.tenant,
        user=actor,
        module="supply_chain",
        action=f"purchase_order.{action}",
        object_type="SupplyPurchaseOrder",
        object_id=order.id,
        before_data={
            "status": before_status,
            "completed_quantity": before_completed_quantity,
        },
        after_data={
            "status": order.status,
            "completed_quantity": order.completed_quantity,
            "version": order.version,
            "idempotency_key": idempotency_key,
        },
        **metadata,
    )
    event.response_snapshot = _snapshot_order_response(
        order.id,
        supplier=actor_type == SupplyPurchaseOrderEvent.ActorType.SUPPLIER,
    )
    with _supply_action_write_context():
        event.save(update_fields=["response_snapshot"])
    return order, event, False


@transaction.atomic
def perform_shipping_route_action(
    *,
    order_id,
    actor,
    action,
    idempotency_key,
    expected_version,
    shipping_route,
    reason,
    request,
):
    allowed_actions = {
        SupplyPurchaseOrderEvent.Action.ASSIGN_SHIPPING_ROUTE,
        SupplyPurchaseOrderEvent.Action.CHANGE_SHIPPING_ROUTE,
    }
    if action not in allowed_actions:
        raise ValidationError({"action": "Unsupported shipping-route action."})
    if not idempotency_key or len(idempotency_key) > 128:
        raise ValidationError({"idempotency_key": "A valid Idempotency-Key header is required."})
    if actor.user_type != "internal":
        raise PermissionDenied("Only an internal purchasing user may assign a shipping route.")

    reason = (reason or "").strip()
    if action == SupplyPurchaseOrderEvent.Action.CHANGE_SHIPPING_ROUTE and not reason:
        raise ValidationError({"reason": "A reason is required when changing a shipping route."})
    request_hash = hashlib.sha256(
        json.dumps(
            {
                "action": str(action),
                "expected_version": expected_version,
                "shipping_route": shipping_route,
                "reason": reason,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    order = (
        SupplyPurchaseOrder.objects.select_for_update()
        .filter(pk=order_id, tenant=actor.tenant)
        .first()
    )
    if order is None:
        raise ScopedResourceNotFound("Supply purchase order is not available in the authorized scope.")

    existing_event = SupplyPurchaseOrderEvent.objects.filter(
        order=order,
        idempotency_key=idempotency_key,
    ).first()
    if existing_event:
        if existing_event.action != action:
            raise StateConflict("The idempotency key was already used for a different action.")
        if existing_event.actor_id != actor.id:
            raise StateConflict("The idempotency key belongs to a different actor.")
        if existing_event.request_hash != request_hash:
            raise StateConflict("The idempotency key was already used with a different action payload.")
        return order, existing_event, True

    if order.version != expected_version:
        raise StateConflict("The supply purchase order version is stale.")
    if order.status != SupplyPurchaseOrder.Status.PRODUCTION_COMPLETED:
        raise StateConflict("Shipping route can only be assigned after production completion.")
    if shipping_route not in {
        SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO,
        SupplyPurchaseOrder.ShippingRoute.CONTAINER_CARGO,
    }:
        raise ValidationError({"shipping_route": "Unsupported shipping route."})

    if action == SupplyPurchaseOrderEvent.Action.ASSIGN_SHIPPING_ROUTE:
        if order.shipping_route != SupplyPurchaseOrder.ShippingRoute.UNDECIDED:
            raise StateConflict("The shipping route was already assigned.")
    else:
        if order.shipping_route == SupplyPurchaseOrder.ShippingRoute.UNDECIDED:
            raise StateConflict("An undecided shipping route must use the initial assignment action.")
        if order.shipping_route == shipping_route:
            raise StateConflict("The replacement shipping route must differ from the current route.")
        from apps.packing.models import PackingBatchOrder

        if PackingBatchOrder.objects.select_for_update().filter(
            order=order,
            active_guard=True,
        ).exists():
            raise StateConflict("Shipping route cannot change after a downstream packing batch exists.")

    before_route = order.shipping_route
    before_version = order.version
    now = timezone.now()
    order.shipping_route = shipping_route
    order.shipping_route_decided_at = now
    order.shipping_route_decided_by = actor
    order.version += 1
    with _supply_action_write_context():
        order.save(
            update_fields=[
                "shipping_route",
                "shipping_route_decided_at",
                "shipping_route_decided_by",
                "version",
                "updated_at",
            ]
        )

    with _supply_action_write_context():
        event = SupplyPurchaseOrderEvent.objects.create(
            tenant=order.tenant,
            order=order,
            action=action,
            idempotency_key=idempotency_key,
            actor=actor,
            actor_type=SupplyPurchaseOrderEvent.ActorType.INTERNAL,
            before_status=order.status,
            after_status=order.status,
            before_shipping_route=before_route,
            after_shipping_route=order.shipping_route,
            payload={
                "expected_version": expected_version,
                "shipping_route": order.shipping_route,
                "reason": reason,
            },
            request_hash=request_hash,
        )
    metadata = _request_metadata(request)
    write_operation_log(
        tenant=order.tenant,
        user=actor,
        module="supply_chain",
        action=f"purchase_order.{action}",
        object_type="SupplyPurchaseOrder",
        object_id=order.id,
        before_data={
            "status": order.status,
            "shipping_route": before_route,
            "version": before_version,
        },
        after_data={
            "status": order.status,
            "shipping_route": order.shipping_route,
            "version": order.version,
            "idempotency_key": idempotency_key,
        },
        **metadata,
    )
    event.response_snapshot = _snapshot_order_response(order.id, supplier=False)
    with _supply_action_write_context():
        event.save(update_fields=["response_snapshot"])
    return order, event, False
