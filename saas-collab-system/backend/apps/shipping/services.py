"""Audited loose-cargo shipment domain actions.

No HTTP or third-party integration lives here.  Every transfer and dispatch
is performed inside a deterministic transaction and delegates box-consumer
state changes to the existing packing domain service.
"""

from __future__ import annotations

import hashlib
import json
from functools import wraps

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, OperationalError, transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import CustomUser
from apps.common.exceptions import (
    BusinessRuleViolation,
    IdempotencyConflict,
    ScopedResourceNotFound,
    StateConflict,
    VersionConflict,
)
from apps.consolidation.models import (
    ConsolidationBoxAllocation,
    ConsolidationEvent,
    LooseCargoConsolidation,
    _consolidation_domain_write_context,
)
from apps.consolidation.services import transfer_consolidation_allocation_to_shipment
from apps.packing.models import PackingBoxConsumption
from apps.packing.services import commit_box_consumption

from .models import (
    LooseCargoShipment,
    ShipmentBoxAllocation,
    ShipmentEvent,
    _shipping_domain_write_context,
)


MYSQL_RETRYABLE_ERROR_CODES = {1205, 1213}


def _database_error_code(exc):
    for candidate in (getattr(exc, "__cause__", None), exc):
        args = getattr(candidate, "args", ())
        if args and isinstance(args[0], int):
            return args[0]
    return None


def shipping_domain_action(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        try:
            with _shipping_domain_write_context():
                return func(*args, **kwargs)
        except OperationalError as exc:
            if _database_error_code(exc) in MYSQL_RETRYABLE_ERROR_CODES:
                raise StateConflict(
                    "Shipment transaction hit a retryable database conflict; retry with the same idempotency key."
                ) from exc
            raise

    return wrapped


def _canonical_hash(payload):
    value = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_idempotency_key(value):
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ValidationError({"idempotency_key": "A valid Idempotency-Key is required."})
    if any(ord(char) < 0x21 or ord(char) > 0x7E for char in value):
        raise ValidationError({"idempotency_key": "Idempotency-Key must contain printable ASCII only."})


def _validate_actor(actor):
    if not actor or not getattr(actor, "is_authenticated", False) or not actor.is_active:
        raise PermissionDenied("An active authenticated actor is required.")
    if actor.user_type != CustomUser.UserType.INTERNAL or not actor.tenant_id:
        raise PermissionDenied("Only tenant-bound internal shipment actors are allowed.")
    return actor


def _is_unique_validation_error(exc):
    if not isinstance(exc, DjangoValidationError):
        return False
    errors = list(getattr(exc, "error_list", ()) or ())
    for field_errors in (getattr(exc, "error_dict", {}) or {}).values():
        errors.extend(field_errors)
    return any(getattr(error, "code", None) in {"unique", "unique_together"} for error in errors)


def _normalize_ids(values, *, field="allocation_ids"):
    if values is None:
        return None
    try:
        normalized = sorted({int(value) for value in values})
    except (TypeError, ValueError) as exc:
        raise ValidationError({field: "Positive integer IDs are required."}) from exc
    if not normalized or normalized[0] <= 0:
        raise ValidationError({field: "At least one positive ID is required."})
    return normalized


def _shipment_snapshot(shipment):
    return {
        "id": int(shipment.id),
        "shipment_no": shipment.shipment_no,
        "route_type": shipment.route_type,
        "region_code": shipment.region_code,
        "origin_site_id": shipment.origin_site_id_snapshot,
        "destination_country_code": shipment.destination_country_code,
        "destination_port_code": shipment.destination_port_code,
        "destination_warehouse_code": shipment.destination_warehouse_code,
        "status": shipment.status,
        "version": int(shipment.version),
        "customs_reference": shipment.customs_reference,
        "forwarder_reference": shipment.forwarder_reference,
        "groupage_reference": shipment.groupage_reference,
        "container_reference": shipment.container_reference,
        "transport_reference": shipment.transport_reference,
    }


def _allocation_snapshot(allocation):
    return {
        "id": int(allocation.id),
        "shipment_id": int(allocation.shipment_id),
        "consolidation_id": int(allocation.consolidation_id),
        "consolidation_allocation_id": int(allocation.consolidation_allocation_id),
        "box_id": int(allocation.box_id),
        "box_no": allocation.box_no_snapshot,
        "state": allocation.state,
        "quantity": int(allocation.quantity_snapshot),
        "supplier_id": allocation.supplier_id_snapshot,
        "order_ids": list(allocation.order_ids_snapshot or []),
        "order_nos": list(allocation.order_nos_snapshot or []),
        "batch_id": allocation.batch_id_snapshot,
        "version": int(allocation.version),
    }


def _event_replay(*, tenant, key, action, request_hash, actor):
    event = ShipmentEvent.objects.select_for_update().filter(tenant=tenant, idempotency_key=key).first()
    if event is None:
        return None
    if event.action != action or event.actor_id != actor.id or event.actor_type != str(actor.user_type):
        raise IdempotencyConflict("The shipment idempotency key belongs to another action or actor.")
    if event.request_hash != request_hash:
        raise IdempotencyConflict("The shipment idempotency key was reused with another payload.")
    return event


def _event(*, tenant, action, actor, key, request_hash, before=None, after=None, reason="", shipment=None,
           allocation=None, box=None, expected_version=None, source_version=None, external_reference="", channel="internal"):
    event = ShipmentEvent(
        tenant=tenant,
        shipment=shipment,
        allocation=allocation,
        box=box,
        action=action,
        actor_type=str(actor.user_type),
        actor_id=int(actor.id),
        channel=str(channel or "internal"),
        expected_version=expected_version,
        source_version=source_version,
        before=before or {},
        after=after or {},
        external_reference=str(external_reference or ""),
        reason=str(reason or ""),
        idempotency_key=key,
        request_hash=request_hash,
        occurred_at=timezone.now(),
    )
    try:
        with transaction.atomic():
            event.save()
    except (IntegrityError, DjangoValidationError) as exc:
        if isinstance(exc, DjangoValidationError) and not _is_unique_validation_error(exc):
            raise
        existing = ShipmentEvent.objects.select_for_update().filter(tenant=tenant, idempotency_key=key).first()
        if existing is None:
            raise
        if existing.action != action or existing.actor_id != actor.id or existing.request_hash != request_hash:
            raise IdempotencyConflict("The shipment idempotency key was reused with another payload.")
        return existing, True
    return event, False


def _lock_shipment(shipment_id, actor):
    shipment = LooseCargoShipment.objects.select_for_update().filter(
        pk=shipment_id, tenant=actor.tenant,
    ).first()
    if shipment is None:
        raise ScopedResourceNotFound("Shipment is not available in this tenant.")
    return shipment


def _expected(shipment, expected_version):
    try:
        expected = int(expected_version)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"expected_version": "A positive expected version is required."}) from exc
    if expected != shipment.version:
        raise VersionConflict("Shipment version is stale; reload before retrying.")


def _save_shipment(shipment, fields):
    shipment.save(update_fields=list(fields) + ["updated_at"])


def _source_release_version(consolidation):
    event = ConsolidationEvent.objects.filter(
        tenant=consolidation.tenant,
        consolidation=consolidation,
        action=ConsolidationEvent.Action.RELEASE,
    ).order_by("-source_version", "-created_at", "-id").first()
    if event is None or not event.source_version:
        raise StateConflict("The source consolidation has no verifiable release version.")
    return int(event.source_version)


@shipping_domain_action
def create_shipment(*, actor, shipment_no, region_code, idempotency_key, origin_site_id=None,
                    origin_site_snapshot=None, destination_country_code="", destination_port_code="",
                    destination_warehouse_code="", note="", planned_dispatch_at=None,
                    forwarder_reference="", groupage_reference="", container_reference="",
                    transport_reference="", channel="internal"):
    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    shipment_no = str(shipment_no or "").strip()
    region_code = str(region_code or "").strip()
    if not shipment_no or not region_code:
        raise ValidationError({"shipment_no": "Shipment number and region are required."})
    payload = {
        "shipment_no": shipment_no, "region_code": region_code, "origin_site_id": origin_site_id,
        "origin_site_snapshot": origin_site_snapshot or {},
        "destination_country_code": destination_country_code,
        "destination_port_code": destination_port_code,
        "destination_warehouse_code": destination_warehouse_code,
        "note": note, "planned_dispatch_at": planned_dispatch_at,
        "forwarder_reference": forwarder_reference, "groupage_reference": groupage_reference,
        "container_reference": container_reference, "transport_reference": transport_reference,
        "channel": channel,
    }
    request_hash = _canonical_hash(payload)
    with transaction.atomic():
        replay = _event_replay(tenant=actor.tenant, key=idempotency_key,
                               action=ShipmentEvent.Action.CREATE, request_hash=request_hash, actor=actor)
        if replay:
            return LooseCargoShipment.objects.get(pk=replay.shipment_id), replay, True
        shipment = LooseCargoShipment(
            tenant=actor.tenant,
            shipment_no=shipment_no,
            region_code=region_code,
            origin_site_id_snapshot=origin_site_id,
            origin_site_snapshot=origin_site_snapshot or {},
            destination_country_code=str(destination_country_code or ""),
            destination_port_code=str(destination_port_code or ""),
            destination_warehouse_code=str(destination_warehouse_code or ""),
            note=str(note or ""),
            planned_dispatch_at=planned_dispatch_at,
            forwarder_reference=str(forwarder_reference or ""),
            groupage_reference=str(groupage_reference or ""),
            container_reference=str(container_reference or ""),
            transport_reference=str(transport_reference or ""),
            created_by=actor,
            updated_by=actor,
        )
        try:
            # Keep the uniqueness race inside a savepoint.  A concurrent
            # request with the same tenant/key may win the shipment-number
            # insert before its append-only event becomes visible; after the
            # savepoint rolls back we can resolve that winner through the
            # global idempotency ledger instead of reporting a false conflict.
            with transaction.atomic():
                shipment.save()
        except (IntegrityError, DjangoValidationError) as exc:
            if isinstance(exc, DjangoValidationError) and not _is_unique_validation_error(exc):
                raise
            raced_event = _event_replay(
                tenant=actor.tenant,
                key=idempotency_key,
                action=ShipmentEvent.Action.CREATE,
                request_hash=request_hash,
                actor=actor,
            )
            if raced_event is not None:
                return LooseCargoShipment.objects.get(pk=raced_event.shipment_id), raced_event, True
            existing = LooseCargoShipment.objects.filter(tenant=actor.tenant, shipment_no=shipment_no).first()
            if existing is not None:
                raise IdempotencyConflict("Shipment number is already used by another request.") from exc
            raise
        event, replayed = _event(
            tenant=actor.tenant, action=ShipmentEvent.Action.CREATE, actor=actor,
            key=idempotency_key, request_hash=request_hash, after=_shipment_snapshot(shipment),
            shipment=shipment, source_version=shipment.version, channel=channel,
        )
        return shipment, event, replayed


@shipping_domain_action
def update_shipment(*, shipment_id, actor, expected_version, idempotency_key, updates=None, reason="", channel="internal", **changes):
    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    merged = dict(updates or {})
    merged.update(changes)
    allowed = {
        "region_code", "origin_site_id_snapshot", "origin_site_snapshot", "destination_country_code",
        "destination_port_code", "destination_warehouse_code", "note", "planned_dispatch_at",
        "forwarder_reference", "groupage_reference", "container_reference", "transport_reference",
    }
    if set(merged) - allowed:
        raise ValidationError({"updates": "Only draft shipment fields may be updated."})
    request_hash = _canonical_hash({"shipment_id": shipment_id, "expected_version": expected_version, "updates": merged, "reason": reason, "channel": channel})
    with transaction.atomic():
        shipment = _lock_shipment(shipment_id, actor)
        replay = _event_replay(tenant=actor.tenant, key=idempotency_key, action=ShipmentEvent.Action.UPDATE,
                               request_hash=request_hash, actor=actor)
        if replay:
            return shipment, replay, True
        _expected(shipment, expected_version)
        if shipment.status != LooseCargoShipment.Status.DRAFT:
            raise StateConflict("Only a draft shipment can be updated.")
        before = _shipment_snapshot(shipment)
        for field, value in merged.items():
            setattr(shipment, field, value)
        shipment.updated_by = actor
        shipment.version += 1
        _save_shipment(shipment, [*merged.keys(), "updated_by", "version"])
        event, replayed = _event(tenant=actor.tenant, action=ShipmentEvent.Action.UPDATE, actor=actor,
                                 key=idempotency_key, request_hash=request_hash, before=before,
                                 after=_shipment_snapshot(shipment), reason=reason, shipment=shipment,
                                 expected_version=expected_version, source_version=shipment.version, channel=channel)
        return shipment, event, replayed


@shipping_domain_action
def allocate_shipment_boxes(*, shipment_id, consolidation_id, allocation_ids, actor, expected_version,
                            idempotency_key, reason="", channel="internal"):
    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    allocation_ids = _normalize_ids(allocation_ids)
    request_hash = _canonical_hash({"shipment_id": shipment_id, "consolidation_id": consolidation_id,
                                    "allocation_ids": allocation_ids, "expected_version": expected_version,
                                    "reason": reason, "channel": channel})
    with transaction.atomic():
        shipment = _lock_shipment(shipment_id, actor)
        replay = _event_replay(tenant=actor.tenant, key=idempotency_key, action=ShipmentEvent.Action.ALLOCATE,
                               request_hash=request_hash, actor=actor)
        if replay:
            return shipment, replay, True
        _expected(shipment, expected_version)
        if shipment.status not in {LooseCargoShipment.Status.DRAFT, LooseCargoShipment.Status.LOADING}:
            raise StateConflict("Only draft/loading shipments can receive transferred boxes.")
        consolidation = LooseCargoConsolidation.objects.select_for_update().filter(
            pk=consolidation_id, tenant=actor.tenant,
        ).first()
        if consolidation is None:
            raise ScopedResourceNotFound("Consolidation is not available in this tenant.")
        if consolidation.status != LooseCargoConsolidation.Status.READY_FOR_SHIPMENT:
            raise StateConflict("Only ready-for-shipment consolidations can be transferred.")
        if (
            shipment.origin_site_id_snapshot is not None
            and int(shipment.origin_site_id_snapshot) != int(consolidation.site_id)
        ):
            raise BusinessRuleViolation("Shipment origin site is incompatible with the consolidation site.")
        source = list(ConsolidationBoxAllocation.objects.select_for_update().select_related(
            "box", "packing_box_consumption", "consolidation",
        ).filter(tenant=actor.tenant, consolidation=consolidation, pk__in=allocation_ids).order_by("box_id", "id"))
        if len(source) != len(allocation_ids):
            raise ScopedResourceNotFound("One or more consolidation allocations are not available.")
        if any(item.state != ConsolidationBoxAllocation.State.RECEIVED for item in source):
            raise StateConflict("Only received consolidation allocations can be transferred.")
        if consolidation.region_code != shipment.region_code:
            raise BusinessRuleViolation("Consolidation and shipment regions are incompatible.")
        release_version = _source_release_version(consolidation)
        before = {
            "shipment": _shipment_snapshot(shipment),
            "allocations": [
                {
                    "id": int(item.id),
                    "box_id": int(item.box_id),
                    "state": item.state,
                    "version": int(item.version),
                    "quantity": int(item.quantity_snapshot),
                    "order_ids": list(item.order_ids_snapshot or []),
                    "order_nos": list(item.order_nos_snapshot or []),
                }
                for item in source
            ],
        }
        created = []
        for item in source:
            source_consolidation_version = int(consolidation.version)
            source_snapshot = {
                "supplier_id_snapshot": item.supplier_id_snapshot,
                "order_ids_snapshot": list(item.order_ids_snapshot or []),
                "order_nos_snapshot": list(item.order_nos_snapshot or []),
                "batch_id_snapshot": item.batch_id_snapshot,
                "batch_no_snapshot": item.batch_no_snapshot,
                "box_no_snapshot": item.box_no_snapshot,
                "quantity_snapshot": item.quantity_snapshot,
                "weight_snapshot": item.weight_snapshot,
                "volume_snapshot": item.volume_snapshot,
                "snapshot": dict(item.snapshot or {}),
            }
            _, _, _, target_consumption = transfer_consolidation_allocation_to_shipment(
                allocation_id=item.id,
                shipment=shipment,
                actor=actor,
                target_consumer_version=shipment.version,
                idempotency_key=f"{idempotency_key}:transfer:{item.box_id}",
                reason=reason or "Shipment box allocation",
                channel=channel,
            )
            allocation = ShipmentBoxAllocation(
                tenant=actor.tenant,
                shipment=shipment,
                consolidation=consolidation,
                consolidation_allocation=item,
                box=item.box,
                packing_box_consumption=target_consumption,
                source_consolidation_version=source_consolidation_version,
                source_release_version=release_version,
                created_by=actor,
                **source_snapshot,
            )
            allocation.save()
            created.append(allocation)
        shipment.status = LooseCargoShipment.Status.LOADING
        shipment.updated_by = actor
        shipment.version += 1
        _save_shipment(shipment, ["status", "updated_by", "version"])
        event, replayed = _event(tenant=actor.tenant, action=ShipmentEvent.Action.ALLOCATE, actor=actor,
                                 key=idempotency_key, request_hash=request_hash, before=before,
                                 after={"shipment": _shipment_snapshot(shipment),
                                        "allocations": [_allocation_snapshot(item) for item in created],
                                        "source_allocations": [
                                            {"id": int(item.id), "state": item.state, "version": int(item.version)}
                                            for item in source
                                        ]},
                                 reason=reason, shipment=shipment, expected_version=expected_version,
                                 source_version=shipment.version, channel=channel)
        return shipment, event, replayed


@shipping_domain_action
def customs_declare_shipment(*, shipment_id, actor, expected_version, idempotency_key, customs_reference,
                             reason="", channel="internal"):
    customs_reference = str(customs_reference or "").strip()
    if not customs_reference:
        raise ValidationError({"customs_reference": "A customs reference is required."})
    if len(customs_reference) > 128:
        raise ValidationError({"customs_reference": "The customs reference is too long."})
    return _set_shipment_status(
        shipment_id=shipment_id, actor=actor, expected_version=expected_version, idempotency_key=idempotency_key,
        target_status=LooseCargoShipment.Status.CUSTOMS_DECLARED, action=ShipmentEvent.Action.CUSTOMS_DECLARE,
        allowed_statuses={LooseCargoShipment.Status.LOADING}, fields={"customs_reference": str(customs_reference or "")},
        actor_field="customs_declared_by", time_field=None, external_reference=str(customs_reference or ""),
        reason=reason, channel=channel,
    )


def _set_shipment_status(*, shipment_id, actor, expected_version, idempotency_key, target_status, action,
                         allowed_statuses, fields=None, actor_field=None, time_field=None,
                         external_reference="", reason="", channel="internal"):
    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    fields = dict(fields or {})
    request_hash = _canonical_hash({"shipment_id": shipment_id, "expected_version": expected_version,
                                    "target_status": target_status, "fields": fields,
                                    "external_reference": external_reference, "reason": reason, "channel": channel})
    with transaction.atomic():
        shipment = _lock_shipment(shipment_id, actor)
        replay = _event_replay(tenant=actor.tenant, key=idempotency_key, action=action,
                               request_hash=request_hash, actor=actor)
        if replay:
            return shipment, replay, True
        _expected(shipment, expected_version)
        if shipment.status not in allowed_statuses:
            raise StateConflict("Shipment status does not permit this action.")
        allocations = list(ShipmentBoxAllocation.objects.select_for_update().filter(
            tenant=actor.tenant, shipment=shipment,
        ).order_by("box_id", "id"))
        if action == ShipmentEvent.Action.CUSTOMS_DECLARE and not allocations:
            raise BusinessRuleViolation("A shipment must contain at least one transferred box before customs declaration.")
        before = _shipment_snapshot(shipment)
        for field, value in fields.items():
            setattr(shipment, field, value)
        if actor_field:
            setattr(shipment, actor_field, actor)
            fields[actor_field] = actor
        if time_field:
            setattr(shipment, time_field, timezone.now())
            fields[time_field] = getattr(shipment, time_field)
        shipment.status = target_status
        shipment.updated_by = actor
        shipment.version += 1
        fields.update({"status": shipment.status, "updated_by": actor, "version": shipment.version})
        _save_shipment(shipment, list(fields))
        event, replayed = _event(tenant=actor.tenant, action=action, actor=actor, key=idempotency_key,
                                 request_hash=request_hash, before=before, after=_shipment_snapshot(shipment),
                                 reason=reason, shipment=shipment, expected_version=expected_version,
                                 source_version=shipment.version, external_reference=external_reference, channel=channel)
        return shipment, event, replayed


@shipping_domain_action
def dispatch_shipment(*, shipment_id, actor, expected_version, idempotency_key, allocation_ids=None,
                      reason="", channel="internal"):
    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    normalized_ids = _normalize_ids(allocation_ids) if allocation_ids is not None else None
    request_hash = _canonical_hash({"shipment_id": shipment_id, "expected_version": expected_version,
                                    "allocation_ids": normalized_ids, "reason": reason, "channel": channel})
    with transaction.atomic():
        shipment = _lock_shipment(shipment_id, actor)
        replay = _event_replay(tenant=actor.tenant, key=idempotency_key, action=ShipmentEvent.Action.DISPATCH,
                               request_hash=request_hash, actor=actor)
        if replay:
            return shipment, replay, True
        _expected(shipment, expected_version)
        if shipment.status not in {LooseCargoShipment.Status.CUSTOMS_DECLARED, LooseCargoShipment.Status.DISPATCHED}:
            raise StateConflict("Only a customs-declared shipment can be dispatched.")
        query = ShipmentBoxAllocation.objects.select_for_update().filter(
            tenant=actor.tenant, shipment=shipment,
        )
        if normalized_ids is not None:
            query = query.filter(pk__in=normalized_ids)
        allocations = list(query.order_by("box_id", "id"))
        if normalized_ids is not None and len(allocations) != len(normalized_ids):
            raise ScopedResourceNotFound("One or more shipment allocations are not available.")
        if normalized_ids is not None:
            # An explicit dispatch set is an all-or-nothing command.  Do not
            # silently drop an already-dispatched allocation while committing
            # the remainder of the caller's selection.
            if any(item.state != ShipmentBoxAllocation.State.TRANSFERRED for item in allocations):
                raise StateConflict("Every selected shipment box must still be transferred.")
        else:
            allocations = [item for item in allocations if item.state == ShipmentBoxAllocation.State.TRANSFERRED]
        if not allocations:
            raise StateConflict("No transferred shipment boxes remain to dispatch.")
        before = {"shipment": _shipment_snapshot(shipment), "allocations": [_allocation_snapshot(item) for item in allocations]}
        for allocation in allocations:
            consumption, _ = commit_box_consumption(
                consumption_id=allocation.packing_box_consumption_id,
                actor=actor,
                idempotency_key=f"{idempotency_key}:commit:{allocation.box_id}",
                reason=reason or "Shipment dispatch",
            )
            if consumption.state != PackingBoxConsumption.State.COMMITTED:
                raise StateConflict("Shipment box consumption did not commit.")
            allocation.state = ShipmentBoxAllocation.State.DISPATCHED
            allocation.dispatched_at = timezone.now()
            allocation.dispatched_by = actor
            allocation.version += 1
            allocation.save(update_fields=["state", "dispatched_at", "dispatched_by", "version", "updated_at"])
        shipment.status = LooseCargoShipment.Status.DISPATCHED
        shipment.actual_dispatch_at = timezone.now()
        shipment.dispatched_by = actor
        shipment.updated_by = actor
        shipment.version += 1
        _save_shipment(shipment, ["status", "actual_dispatch_at", "dispatched_by", "updated_by", "version"])
        event, replayed = _event(tenant=actor.tenant, action=ShipmentEvent.Action.DISPATCH, actor=actor,
                                 key=idempotency_key, request_hash=request_hash, before=before,
                                 after={"shipment": _shipment_snapshot(shipment), "allocations": [_allocation_snapshot(item) for item in allocations]},
                                 reason=reason, shipment=shipment, expected_version=expected_version,
                                 source_version=shipment.version, channel=channel)
        return shipment, event, replayed


def port_arrival_shipment(**kwargs):
    return _arrival_transition(target_status=LooseCargoShipment.Status.PORT_ARRIVED,
                               action=ShipmentEvent.Action.PORT_ARRIVAL, allowed_shipment_statuses={LooseCargoShipment.Status.DISPATCHED},
                               from_state=ShipmentBoxAllocation.State.DISPATCHED, to_state=ShipmentBoxAllocation.State.ARRIVED_PORT,
                               time_field="port_arrived_at", actor_field="port_arrived_by", **kwargs)


def warehouse_arrival_shipment(**kwargs):
    return _arrival_transition(target_status=LooseCargoShipment.Status.WAREHOUSE_ARRIVED,
                               action=ShipmentEvent.Action.WAREHOUSE_ARRIVAL, allowed_shipment_statuses={LooseCargoShipment.Status.PORT_ARRIVED},
                               from_state=ShipmentBoxAllocation.State.ARRIVED_PORT, to_state=ShipmentBoxAllocation.State.ARRIVED_WAREHOUSE,
                               time_field="warehouse_arrived_at", actor_field="warehouse_arrived_by", **kwargs)


def clear_shipment(**kwargs):
    return _arrival_transition(target_status=LooseCargoShipment.Status.WAREHOUSE_CLEARED,
                               action=ShipmentEvent.Action.CLEARANCE, allowed_shipment_statuses={LooseCargoShipment.Status.WAREHOUSE_ARRIVED},
                               from_state=ShipmentBoxAllocation.State.ARRIVED_WAREHOUSE, to_state=ShipmentBoxAllocation.State.CLEARED,
                               time_field="cleared_at", actor_field="cleared_by", **kwargs)


@shipping_domain_action
def _arrival_transition(*, shipment_id, actor, expected_version, idempotency_key, target_status,
                        action, allowed_shipment_statuses, from_state, to_state, time_field, actor_field,
                        reason="", channel="internal"):
    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    request_hash = _canonical_hash({"shipment_id": shipment_id, "expected_version": expected_version,
                                    "target_status": target_status, "reason": reason, "channel": channel})
    with transaction.atomic():
        shipment = _lock_shipment(shipment_id, actor)
        replay = _event_replay(tenant=actor.tenant, key=idempotency_key, action=action,
                               request_hash=request_hash, actor=actor)
        if replay:
            return shipment, replay, True
        _expected(shipment, expected_version)
        if shipment.status not in allowed_shipment_statuses:
            raise StateConflict("Shipment status does not permit this arrival action.")
        allocations = list(ShipmentBoxAllocation.objects.select_for_update().filter(
            tenant=actor.tenant, shipment=shipment,
        ).order_by("box_id", "id"))
        if not allocations or any(item.state != from_state for item in allocations):
            raise StateConflict("Every shipment box must reach the prior milestone first.")
        before = {"shipment": _shipment_snapshot(shipment), "allocations": [_allocation_snapshot(item) for item in allocations]}
        at = timezone.now()
        allocation_time_field = {
            "port_arrived_at": "arrived_port_at",
            "warehouse_arrived_at": "arrived_warehouse_at",
            "cleared_at": "cleared_at",
        }[time_field]
        for allocation in allocations:
            allocation.state = to_state
            setattr(allocation, allocation_time_field, at)
            allocation.version += 1
            allocation.save(update_fields=["state", allocation_time_field, "version", "updated_at"])
        setattr(shipment, time_field, at)
        setattr(shipment, actor_field, actor)
        shipment.status = target_status
        shipment.updated_by = actor
        shipment.version += 1
        _save_shipment(shipment, [time_field, actor_field, "status", "updated_by", "version"])
        event, replayed = _event(tenant=actor.tenant, action=action, actor=actor, key=idempotency_key,
                                 request_hash=request_hash, before=before,
                                 after={"shipment": _shipment_snapshot(shipment), "allocations": [_allocation_snapshot(item) for item in allocations]},
                                 reason=reason, shipment=shipment, expected_version=expected_version,
                                 source_version=shipment.version, channel=channel)
        return shipment, event, replayed


@shipping_domain_action
def cancel_shipment(*, shipment_id, actor, expected_version, idempotency_key, reason, channel="internal"):
    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    if not str(reason or "").strip():
        raise ValidationError({"reason": "A cancellation reason is required."})
    request_hash = _canonical_hash({"shipment_id": shipment_id, "expected_version": expected_version, "reason": reason, "channel": channel})
    with transaction.atomic():
        shipment = _lock_shipment(shipment_id, actor)
        replay = _event_replay(tenant=actor.tenant, key=idempotency_key, action=ShipmentEvent.Action.CANCEL,
                               request_hash=request_hash, actor=actor)
        if replay:
            return shipment, replay, True
        _expected(shipment, expected_version)
        if shipment.status != LooseCargoShipment.Status.DRAFT:
            raise StateConflict("Only a draft shipment without transferred boxes can be cancelled.")
        if ShipmentBoxAllocation.objects.filter(tenant=actor.tenant, shipment=shipment).exists():
            raise StateConflict("A shipment with transferred boxes cannot be cancelled in this wave.")
        before = _shipment_snapshot(shipment)
        shipment.status = LooseCargoShipment.Status.CANCELLED
        shipment.cancelled_by = actor
        shipment.cancelled_at = timezone.now()
        shipment.cancelled_reason = str(reason).strip()
        shipment.updated_by = actor
        shipment.version += 1
        _save_shipment(shipment, ["status", "cancelled_by", "cancelled_at", "cancelled_reason", "updated_by", "version"])
        event, replayed = _event(tenant=actor.tenant, action=ShipmentEvent.Action.CANCEL, actor=actor,
                                 key=idempotency_key, request_hash=request_hash, before=before,
                                 after=_shipment_snapshot(shipment), reason=reason, shipment=shipment,
                                 expected_version=expected_version, source_version=shipment.version, channel=channel)
        return shipment, event, replayed


@shipping_domain_action
def mark_shipment_exception(*, shipment_id, actor, expected_version, idempotency_key, reason, channel="internal"):
    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    if not str(reason or "").strip():
        raise ValidationError({"reason": "An exception reason is required."})
    request_hash = _canonical_hash({"shipment_id": shipment_id, "expected_version": expected_version, "reason": reason, "channel": channel})
    with transaction.atomic():
        shipment = _lock_shipment(shipment_id, actor)
        replay = _event_replay(tenant=actor.tenant, key=idempotency_key, action=ShipmentEvent.Action.EXCEPTION,
                               request_hash=request_hash, actor=actor)
        if replay:
            return shipment, replay, True
        _expected(shipment, expected_version)
        if shipment.status in {LooseCargoShipment.Status.CANCELLED, LooseCargoShipment.Status.WAREHOUSE_CLEARED}:
            raise StateConflict("This shipment cannot receive a new exception event.")
        before = _shipment_snapshot(shipment)
        shipment.version += 1
        shipment.updated_by = actor
        _save_shipment(shipment, ["updated_by", "version"])
        event, replayed = _event(tenant=actor.tenant, action=ShipmentEvent.Action.EXCEPTION, actor=actor,
                                 key=idempotency_key, request_hash=request_hash, before=before,
                                 after={**_shipment_snapshot(shipment), "exception_reason": str(reason).strip()},
                                 reason=reason, shipment=shipment, expected_version=expected_version,
                                 source_version=shipment.version, channel=channel)
        return shipment, event, replayed


# Friendly aliases used by future API adapters.
create = create_shipment
update = update_shipment
allocate_boxes = allocate_shipment_boxes
customs_declare = customs_declare_shipment
dispatch = dispatch_shipment
port_arrival = port_arrival_shipment
warehouse_arrival = warehouse_arrival_shipment
clearance = clear_shipment
cancel = cancel_shipment
exception = mark_shipment_exception
transfer_boxes = allocate_shipment_boxes
