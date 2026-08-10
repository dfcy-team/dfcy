"""Audited domain actions for loose-cargo consolidation."""

import hashlib
import json
from dataclasses import dataclass
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
from apps.packing.models import (
    PackingBatch,
    PackingBox,
    PackingBoxConsumption,
    PackingBoxItem,
)
from apps.packing.services import (
    commit_box_consumption,
    release_box_consumption,
    reserve_box_consumption,
    transfer_box_consumption,
)
from apps.purchasing.models import SupplyPurchaseOrder

from .models import (
    ConsolidationBoxAllocation,
    ConsolidationEvent,
    ConsolidationSite,
    ConsolidationSupplierCapability,
    LooseCargoConsolidation,
    _consolidation_domain_write_context,
)


MYSQL_RETRYABLE_ERROR_CODES = {1205, 1213}


@dataclass(frozen=True)
class ConsolidationReplayReference:
    id: int
    snapshot: dict


def _database_error_code(exc):
    for candidate in (getattr(exc, "__cause__", None), exc):
        args = getattr(candidate, "args", ())
        if args and isinstance(args[0], int):
            return args[0]
    return None


def consolidation_domain_action(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        try:
            with _consolidation_domain_write_context():
                return func(*args, **kwargs)
        except OperationalError as exc:
            if _database_error_code(exc) in MYSQL_RETRYABLE_ERROR_CODES:
                raise StateConflict(
                    "Consolidation transaction hit a retryable database conflict; retry with the same idempotency key."
                ) from exc
            raise

    return wrapped


def _canonical_hash(payload):
    value = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_idempotency_key(value):
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ValidationError({"idempotency_key": "A valid Idempotency-Key is required."})
    if any(ord(ch) < 0x21 or ord(ch) > 0x7E for ch in value):
        raise ValidationError({"idempotency_key": "Idempotency-Key must contain printable ASCII only."})


def _validate_actor(actor):
    if not actor or not getattr(actor, "is_authenticated", False) or not actor.is_active:
        raise PermissionDenied("An active authenticated actor is required.")
    if actor.user_type != CustomUser.UserType.INTERNAL or not actor.tenant_id:
        raise PermissionDenied("Only tenant-bound internal actors can perform consolidation actions.")


def _is_unique_validation_error(exc):
    """Return whether ``Model.full_clean()`` reported a unique collision.

    Django performs ``validate_unique`` before issuing an INSERT.  Under a
    concurrent MySQL create this can be the observable failure instead of an
    ``IntegrityError``.  We only translate that specific validation failure;
    malformed domain input must retain its normal validation response.
    """

    if not isinstance(exc, DjangoValidationError):
        return False
    errors = list(getattr(exc, "error_list", ()) or ())
    for field_errors in (getattr(exc, "error_dict", {}) or {}).values():
        errors.extend(field_errors)
    return any(getattr(error, "code", None) == "unique" for error in errors)


def _child_key(action, parent_key, *ids):
    raw = ":".join([action, parent_key, *(str(value) for value in ids)])
    return f"con:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"[:128]


def _site_snapshot(site):
    return {
        "id": int(site.id),
        "site_code": site.site_code,
        "name": site.name,
        "region_code": site.region_code,
        "country_code": site.country_code,
        "province_state": site.province_state,
        "city": site.city,
        "district": site.district,
        "address_line": site.address_line,
        "postal_code": site.postal_code,
        "timezone": site.timezone,
        "contact_name": site.contact_name,
        "contact_phone": site.contact_phone,
        "delivery_instructions": site.delivery_instructions,
        "is_active": bool(site.is_active),
        "effective_from": site.effective_from.isoformat() if site.effective_from else None,
        "effective_to": site.effective_to.isoformat() if site.effective_to else None,
        "version": int(site.version),
    }


def _site_fields(site):
    snap = _site_snapshot(site)
    return {
        "site_code_snapshot": snap["site_code"],
        "site_name_snapshot": snap["name"],
        "site_region_code_snapshot": snap["region_code"],
        "site_country_code_snapshot": snap["country_code"],
        "site_province_state_snapshot": snap["province_state"],
        "site_city_snapshot": snap["city"],
        "site_district_snapshot": snap["district"],
        "site_address_line_snapshot": snap["address_line"],
        "site_postal_code_snapshot": snap["postal_code"],
        "site_timezone_snapshot": snap["timezone"],
        "site_contact_name_snapshot": snap["contact_name"],
        "site_contact_phone_snapshot": snap["contact_phone"],
        "site_delivery_instructions_snapshot": snap["delivery_instructions"],
        "site_snapshot": snap,
    }


def _handover_capability_snapshot(capability):
    return {
        "id": int(capability.id),
        "supplier_id": int(capability.supplier_id),
        "can_submit_handover": bool(capability.can_submit_handover),
        "version": int(capability.version),
    }


def _require_handover_capability(actor, supplier_id):
    """Require an explicit, independently managed handover capability."""
    capability = ConsolidationSupplierCapability.objects.filter(
        tenant=actor.tenant, supplier_id=int(supplier_id), can_submit_handover=True,
    ).first()
    if capability is None:
        raise PermissionDenied("Supplier handover capability is not enabled.")
    return capability


def _consolidation_snapshot(item):
    return {
        "id": int(item.id),
        "consolidation_no": item.consolidation_no,
        "region_code": item.region_code,
        "site_id": int(item.site_id),
        "status": item.status,
        "version": int(item.version),
    }


def _allocation_snapshot(item):
    return {
        "id": int(item.id),
        "consolidation_id": int(item.consolidation_id),
        "box_id": int(item.box_id),
        "box_no": item.box_no_snapshot,
        "state": item.state,
        "quantity": int(item.quantity_snapshot),
        "supplier_id": item.supplier_id_snapshot,
        "order_id": item.order_id_snapshot,
        "order_ids": list(item.order_ids_snapshot or []),
        "order_nos": list(item.order_nos_snapshot or []),
        "batch_id": item.batch_id_snapshot,
        "box_snapshot": dict(item.snapshot or {}),
        "evidence_ids": list(item.evidence_ids or []),
        "handover_evidence_id": item.handover_evidence_id,
        "version": int(item.version),
    }


def _event_replay(*, tenant, key, action, request_hash, actor):
    event = ConsolidationEvent.objects.select_for_update().filter(tenant=tenant, idempotency_key=key).first()
    if event is None:
        return None
    if event.action != action or event.actor_id != actor.id:
        raise IdempotencyConflict("The consolidation idempotency key belongs to another action or actor.")
    if event.request_hash != request_hash:
        raise IdempotencyConflict("The consolidation idempotency key was reused with another payload.")
    return event


def _event(*, tenant, action, actor, key, request_hash, before=None, after=None, reason="", site=None,
           consolidation=None, allocation=None, box=None, expected_version=None, source_type="", source_id="",
           source_version=None):
    event = ConsolidationEvent(
        tenant=tenant,
        site=site,
        consolidation=consolidation,
        allocation=allocation,
        box=box,
        action=action,
        actor=actor,
        before=before or {},
        after=after or {},
        reason=str(reason or ""),
        idempotency_key=key,
        request_hash=request_hash,
        expected_version=expected_version,
        source_type=source_type,
        source_id=str(source_id or ""),
        source_version=source_version,
        occurred_at=timezone.now(),
    )
    try:
        # Keep an INSERT constraint failure inside a savepoint so the outer
        # domain transaction remains queryable while resolving a concurrent
        # request to its committed event.
        with transaction.atomic():
            event.save()
    except (IntegrityError, DjangoValidationError) as exc:
        if isinstance(exc, DjangoValidationError) and not _is_unique_validation_error(exc):
            raise
        existing = ConsolidationEvent.objects.select_for_update().filter(tenant=tenant, idempotency_key=key).first()
        if existing is None:
            raise
        if existing.action != action or existing.actor_id != actor.id or existing.request_hash != request_hash:
            raise IdempotencyConflict("The consolidation idempotency key was reused with another payload.")
        return existing, True
    return event, False


def _expected(instance, expected_version):
    if expected_version is None:
        raise ValidationError({"expected_version": "expected_version is required for this action."})
    if isinstance(expected_version, bool) or int(expected_version) != int(instance.version):
        raise VersionConflict("The supplied version is stale; reload and retry with the same key.")


def _lock_consolidation(consolidation_id, actor):
    item = LooseCargoConsolidation.objects.select_for_update().select_related("site").filter(
        pk=consolidation_id, tenant=actor.tenant
    ).first()
    if item is None:
        raise ScopedResourceNotFound("Consolidation is not available in this tenant.")
    return item


def _require_site(site, region, *, at=None, planned_times=()):
    """Validate site scope and its effective interval at a domain action.

    The release action additionally passes the planned cutoff/dispatch times;
    both must fall inside the same effective interval when supplied.  The
    half-open interval avoids accepting a site exactly at ``effective_to``.
    """

    at = at or timezone.now()
    if not site.is_active:
        raise BusinessRuleViolation("An inactive consolidation site cannot receive a new arrangement.")
    if region is not None and site.region_code != region:
        raise BusinessRuleViolation("Consolidation region must match the selected site region.")
    if site.effective_from and at < site.effective_from:
        raise BusinessRuleViolation("The consolidation site is not effective at this action time.")
    if site.effective_to and at >= site.effective_to:
        raise BusinessRuleViolation("The consolidation site has expired at this action time.")
    for planned in planned_times:
        if planned is None:
            continue
        if site.effective_from and planned < site.effective_from:
            raise BusinessRuleViolation("The planned consolidation time precedes the site effective interval.")
        if site.effective_to and planned >= site.effective_to:
            raise BusinessRuleViolation("The planned consolidation time exceeds the site effective interval.")


def _box_route_is_loose(box):
    order_ids = list(SupplyPurchaseOrder.objects.filter(
        tenant=box.tenant, packing_batch_links__batch_id=box.batch_id
    ).values_list("id", flat=True))
    return bool(order_ids) and not SupplyPurchaseOrder.objects.filter(
        tenant=box.tenant, pk__in=order_ids
    ).exclude(shipping_route=SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO).exists()


def _box_snapshot(box):
    items = list(PackingBoxItem.objects.filter(box=box).order_by("pk"))
    orders = list(SupplyPurchaseOrder.objects.filter(
        tenant=box.tenant, packing_batch_links__batch_id=box.batch_id
    ).order_by("pk"))
    order_ids = [int(order.id) for order in orders]
    order_nos = [order.order_no for order in orders]
    order = orders[0] if orders else None
    return {
        "supplier_id": box.batch.supplier_id,
        "order_id": order.id if order else None,
        "order_no": order.order_no if order else "",
        "order_ids": order_ids,
        "order_nos": order_nos,
        "batch_id": box.batch_id,
        "batch_no": box.batch.batch_no,
        "box_no": box.box_no,
        "quantity": sum(int(item.quantity) for item in items),
        "weight": str(box.weight) if box.weight is not None else None,
        "volume": str(box.volume) if box.volume is not None else None,
        "items": [
            {"order_line_id": item.order_line_id, "quantity": int(item.quantity),
             "order_no": item.order_no_snapshot, "sku_code": item.sku_code_snapshot,
             "product_name": item.product_name_snapshot}
            for item in items
        ],
    }


def _lock_boxes(actor, box_ids):
    incoming = list(box_ids)
    ids = sorted({int(value) for value in incoming})
    if not ids or len(ids) != len(incoming):
        raise ValidationError({"box_ids": "At least one unique box ID is required."})
    boxes = list(PackingBox.objects.select_related("batch").filter(pk__in=ids, tenant=actor.tenant).order_by("pk"))
    if len(boxes) != len(ids):
        raise ScopedResourceNotFound("One or more packing boxes are not available in this tenant.")
    batch_ids = sorted({box.batch_id for box in boxes})
    list(PackingBatch.objects.select_for_update().filter(pk__in=batch_ids, tenant=actor.tenant).order_by("pk"))
    return list(PackingBox.objects.select_for_update().select_related("batch").filter(
        pk__in=ids, tenant=actor.tenant
    ).order_by("pk"))


@consolidation_domain_action
def create_consolidation_site(*, actor, site_code=None, code=None, name, region_code, idempotency_key,
                              country_code="", province_state="", city="", district="", address_line="",
                              postal_code="", timezone_name="Asia/Shanghai", timezone=None, contact_name="",
                              contact_phone="", delivery_instructions="", effective_from=None, effective_to=None):
    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    site_code = site_code or code
    timezone_value = timezone if timezone is not None else timezone_name
    payload = {
        "site_code": site_code, "name": name, "region_code": region_code,
        "country_code": country_code, "province_state": province_state, "city": city,
        "district": district, "address_line": address_line, "postal_code": postal_code,
        "timezone": timezone_value, "contact_name": contact_name, "contact_phone": contact_phone,
        "delivery_instructions": delivery_instructions, "effective_from": effective_from,
        "effective_to": effective_to,
    }
    request_hash = _canonical_hash(payload)
    with transaction.atomic():
        replay = _event_replay(tenant=actor.tenant, key=idempotency_key,
                               action=ConsolidationEvent.Action.SITE_CREATE,
                               request_hash=request_hash, actor=actor)
        if replay:
            return ConsolidationSite.objects.get(pk=replay.site_id), replay, True
        site = ConsolidationSite(tenant=actor.tenant, site_code=str(site_code or "").strip(),
                                 name=str(name or "").strip(), region_code=str(region_code or "").strip(),
                                 country_code=country_code, province_state=province_state, city=city,
                                 district=district, address_line=address_line, postal_code=postal_code,
                                 timezone=timezone_value, contact_name=contact_name, contact_phone=contact_phone,
                                 delivery_instructions=delivery_instructions, effective_from=effective_from,
                                 effective_to=effective_to, created_by=actor, updated_by=actor)
        try:
            with transaction.atomic():
                site.save()
        except (IntegrityError, DjangoValidationError) as exc:
            if isinstance(exc, DjangoValidationError) and not _is_unique_validation_error(exc):
                raise
            replay = _event_replay(tenant=actor.tenant, key=idempotency_key,
                                   action=ConsolidationEvent.Action.SITE_CREATE,
                                   request_hash=request_hash, actor=actor)
            if replay:
                return ConsolidationSite.objects.get(pk=replay.site_id), replay, True
            # A concurrent caller using a different key must receive a
            # domain conflict instead of a backend-specific unique error.
            existing = ConsolidationSite.objects.filter(
                tenant=actor.tenant, site_code=site.site_code
            ).first()
            if existing is not None:
                raise StateConflict("The site code already exists; use a new code or the original idempotency key.") from exc
            raise
        event, replayed = _event(tenant=actor.tenant, action=ConsolidationEvent.Action.SITE_CREATE,
                                 actor=actor, key=idempotency_key, request_hash=request_hash,
                                 after=_site_snapshot(site), site=site, source_type="consolidation_site",
                                 source_id=site.id, source_version=site.version)
        return site, event, replayed


@consolidation_domain_action
def update_consolidation_site(*, site_id, actor, expected_version, idempotency_key, **changes):
    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    if "code" in changes and "site_code" not in changes:
        changes["site_code"] = changes.pop("code")
    allowed = {"site_code", "name", "region_code", "country_code", "province_state", "city",
               "district", "address_line", "postal_code", "timezone", "contact_name",
               "contact_phone", "delivery_instructions", "effective_from", "effective_to"}
    payload = {key: value for key, value in changes.items() if key in allowed}
    request_hash = _canonical_hash({"site_id": site_id, "expected_version": expected_version, **payload})
    with transaction.atomic():
        site = ConsolidationSite.objects.select_for_update().filter(pk=site_id, tenant=actor.tenant).first()
        if site is None:
            raise ScopedResourceNotFound("Consolidation site is not available in this tenant.")
        replay = _event_replay(tenant=actor.tenant, key=idempotency_key,
                               action=ConsolidationEvent.Action.SITE_UPDATE,
                               request_hash=request_hash, actor=actor)
        if replay:
            return site, replay, True
        _expected(site, expected_version)
        before = _site_snapshot(site)
        if "site_code" in payload:
            desired_code = str(payload["site_code"] or "").strip()
            if desired_code != site.site_code and LooseCargoConsolidation.objects.filter(site_id=site.id).exists():
                raise StateConflict("A site code cannot change after a consolidation has used the site.")
        for key, value in payload.items():
            setattr(site, key, value)
        site.version += 1
        site.updated_by = actor
        site.save(update_fields=list(payload) + ["version", "updated_by", "updated_at"])
        event, replayed = _event(tenant=actor.tenant, action=ConsolidationEvent.Action.SITE_UPDATE,
                                 actor=actor, key=idempotency_key, request_hash=request_hash, before=before,
                                 after=_site_snapshot(site), site=site, expected_version=expected_version,
                                 source_type="consolidation_site", source_id=site.id,
                                 source_version=site.version)
        return site, event, replayed


@consolidation_domain_action
def deactivate_consolidation_site(*, site_id, actor, expected_version, idempotency_key, reason=""):
    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    request_hash = _canonical_hash({"site_id": site_id, "expected_version": expected_version, "reason": reason})
    with transaction.atomic():
        site = ConsolidationSite.objects.select_for_update().filter(pk=site_id, tenant=actor.tenant).first()
        if site is None:
            raise ScopedResourceNotFound("Consolidation site is not available in this tenant.")
        replay = _event_replay(tenant=actor.tenant, key=idempotency_key,
                               action=ConsolidationEvent.Action.SITE_DEACTIVATE,
                               request_hash=request_hash, actor=actor)
        if replay:
            return site, replay, True
        _expected(site, expected_version)
        before = _site_snapshot(site)
        site.is_active = False
        site.version += 1
        site.updated_by = actor
        site.save(update_fields=["is_active", "version", "updated_by", "updated_at"])
        event, replayed = _event(tenant=actor.tenant, action=ConsolidationEvent.Action.SITE_DEACTIVATE,
                                 actor=actor, key=idempotency_key, request_hash=request_hash, before=before,
                                 after=_site_snapshot(site), site=site, reason=reason,
                                 expected_version=expected_version, source_type="consolidation_site",
                                 source_id=site.id, source_version=site.version)
        return site, event, replayed


@consolidation_domain_action
def set_consolidation_supplier_capability(*, supplier_id, can_submit_handover, actor,
                                           idempotency_key, expected_version=None, reason=""):
    """Create/update the explicit supplier handover capability.

    This is an internal, audited configuration action.  Missing rows default
    to ``False`` until an internal actor explicitly enables them.
    """
    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    try:
        supplier_id = int(supplier_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"supplier_id": "A positive supplier ID is required."}) from exc
    if supplier_id <= 0:
        raise ValidationError({"supplier_id": "A positive supplier ID is required."})
    from apps.masterdata.models import SupplierMaster
    supplier = SupplierMaster.objects.filter(tenant=actor.tenant, pk=supplier_id).first()
    if supplier is None:
        raise ScopedResourceNotFound("Supplier is not available in this tenant.")
    desired = bool(can_submit_handover)
    request_hash = _canonical_hash({
        "supplier_id": supplier_id,
        "can_submit_handover": desired,
        "expected_version": expected_version,
        "reason": str(reason or ""),
    })
    with transaction.atomic():
        replay = _event_replay(tenant=actor.tenant, key=idempotency_key,
                               action=ConsolidationEvent.Action.CAPABILITY_UPDATE,
                               request_hash=request_hash, actor=actor)
        if replay:
            capability = ConsolidationSupplierCapability.objects.get(pk=replay.source_id)
            return capability, replay, True
        capability = ConsolidationSupplierCapability.objects.select_for_update().filter(
            tenant=actor.tenant, supplier_id=supplier_id,
        ).first()
        if capability is None:
            if expected_version not in (None, 1):
                raise VersionConflict("A new capability starts at version 1.")
            capability = ConsolidationSupplierCapability(
                tenant=actor.tenant, supplier=supplier, can_submit_handover=desired,
                version=1, created_by=actor, updated_by=actor,
            )
            capability.save()
            before = {}
        else:
            if expected_version is not None:
                _expected(capability, expected_version)
            before = _handover_capability_snapshot(capability)
            capability.can_submit_handover = desired
            capability.version += 1
            capability.updated_by = actor
            capability.save(update_fields=["can_submit_handover", "version", "updated_by", "updated_at"])
        event, replayed = _event(
            tenant=actor.tenant,
            action=ConsolidationEvent.Action.CAPABILITY_UPDATE,
            actor=actor,
            key=idempotency_key,
            request_hash=request_hash,
            before=before,
            after=_handover_capability_snapshot(capability),
            reason=reason,
            source_type="consolidation_supplier_capability",
            source_id=capability.id,
            source_version=capability.version,
        )
        return capability, event, replayed


@consolidation_domain_action
def create_loose_cargo_consolidation(*, site_id, actor, idempotency_key, region_code=None,
                                     consolidation_no=None, collection_cutoff_at=None,
                                     expected_dispatch_at=None, note="", external_forwarder_ref="",
                                     external_groupage_ref=""):
    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    site = ConsolidationSite.objects.filter(pk=site_id, tenant=actor.tenant).first()
    if site is None:
        raise ScopedResourceNotFound("Consolidation site is not available in this tenant.")
    region_code = region_code or site.region_code
    # Auto-generated numbers are derived from the request key so a retry with
    # no client-supplied number has the same request hash and can replay.
    consolidation_no = consolidation_no or (
        f"LC-{hashlib.sha256(f'{actor.tenant_id}:{idempotency_key}'.encode('utf-8')).hexdigest()[:20].upper()}"
    )
    payload = {"site_id": site_id, "region_code": region_code, "consolidation_no": consolidation_no,
               "collection_cutoff_at": collection_cutoff_at, "expected_dispatch_at": expected_dispatch_at,
               "note": note, "external_forwarder_ref": external_forwarder_ref,
               "external_groupage_ref": external_groupage_ref}
    request_hash = _canonical_hash(payload)
    with transaction.atomic():
        replay = _event_replay(tenant=actor.tenant, key=idempotency_key,
                               action=ConsolidationEvent.Action.CREATE,
                               request_hash=request_hash, actor=actor)
        if replay:
            return LooseCargoConsolidation.objects.get(pk=replay.consolidation_id), replay, True
        site = ConsolidationSite.objects.select_for_update().get(pk=site.id)
        _require_site(site, region_code)
        consolidation = LooseCargoConsolidation(tenant=actor.tenant, consolidation_no=str(consolidation_no).strip(),
            region_code=str(region_code).strip(), site=site, collection_cutoff_at=collection_cutoff_at,
            expected_dispatch_at=expected_dispatch_at, note=note,
            external_forwarder_ref=external_forwarder_ref, external_groupage_ref=external_groupage_ref,
            created_by=actor)
        try:
            with transaction.atomic():
                consolidation.save()
        except (IntegrityError, DjangoValidationError) as exc:
            if isinstance(exc, DjangoValidationError) and not _is_unique_validation_error(exc):
                raise
            replay = _event_replay(tenant=actor.tenant, key=idempotency_key,
                                   action=ConsolidationEvent.Action.CREATE,
                                   request_hash=request_hash, actor=actor)
            if replay:
                return LooseCargoConsolidation.objects.get(pk=replay.consolidation_id), replay, True
            existing = LooseCargoConsolidation.objects.filter(
                tenant=actor.tenant, consolidation_no=consolidation.consolidation_no
            ).first()
            if existing is not None:
                raise StateConflict("The consolidation number already exists; use a new number or original key.") from exc
            raise
        event, replayed = _event(tenant=actor.tenant, action=ConsolidationEvent.Action.CREATE,
                                 actor=actor, key=idempotency_key, request_hash=request_hash,
                                 after=_consolidation_snapshot(consolidation), site=site,
                                 consolidation=consolidation, expected_version=1,
                                 source_type="loose_cargo_consolidation", source_id=consolidation.id,
                                 source_version=consolidation.version)
        return consolidation, event, replayed


@consolidation_domain_action
def update_loose_cargo_consolidation(*, consolidation_id, actor, expected_version, idempotency_key,
                                     site_id=None, region_code=None, collection_cutoff_at=None,
                                     expected_dispatch_at=None, note=None, external_forwarder_ref=None,
                                     external_groupage_ref=None):
    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    payload = {key: value for key, value in {
        "site_id": site_id, "region_code": region_code, "collection_cutoff_at": collection_cutoff_at,
        "expected_dispatch_at": expected_dispatch_at, "note": note,
        "external_forwarder_ref": external_forwarder_ref, "external_groupage_ref": external_groupage_ref,
    }.items() if value is not None}
    request_hash = _canonical_hash({"consolidation_id": consolidation_id,
                                    "expected_version": expected_version, **payload})
    with transaction.atomic():
        consolidation = _lock_consolidation(consolidation_id, actor)
        replay = _event_replay(tenant=actor.tenant, key=idempotency_key,
                               action=ConsolidationEvent.Action.UPDATE,
                               request_hash=request_hash, actor=actor)
        if replay:
            return consolidation, replay, True
        _expected(consolidation, expected_version)
        if consolidation.status != LooseCargoConsolidation.Status.DRAFT:
            raise StateConflict("Only a draft consolidation can be updated.")
        before = _consolidation_snapshot(consolidation)
        site = consolidation.site
        if site_id is not None and int(site_id) != site.id:
            site = ConsolidationSite.objects.select_for_update().filter(pk=site_id, tenant=actor.tenant).first()
            if site is None:
                raise ScopedResourceNotFound("Consolidation site is not available in this tenant.")
        desired_region = payload.get("region_code", consolidation.region_code)
        _require_site(site, desired_region)
        consolidation.site = site
        consolidation.region_code = desired_region
        for field in ("collection_cutoff_at", "expected_dispatch_at", "note", "external_forwarder_ref", "external_groupage_ref"):
            if field in payload:
                setattr(consolidation, field, payload[field])
        consolidation.version += 1
        consolidation.save(update_fields=["site", "region_code", "collection_cutoff_at", "expected_dispatch_at",
                                          "note", "external_forwarder_ref", "external_groupage_ref", "version", "updated_at"])
        event, replayed = _event(tenant=actor.tenant, action=ConsolidationEvent.Action.UPDATE,
                                 actor=actor, key=idempotency_key, request_hash=request_hash, before=before,
                                 after=_consolidation_snapshot(consolidation), site=site,
                                 consolidation=consolidation, expected_version=expected_version,
                                 source_type="loose_cargo_consolidation", source_id=consolidation.id,
                                 source_version=consolidation.version)
        return consolidation, event, replayed


def _allocation_values(box, consumption, actor):
    snap = _box_snapshot(box)
    return {
        "tenant": actor.tenant,
        "box": box,
        "packing_box_consumption": consumption,
        "supplier_id_snapshot": snap["supplier_id"],
        "order_id_snapshot": snap["order_id"],
        "order_no_snapshot": snap["order_no"],
        "order_ids_snapshot": snap["order_ids"],
        "order_nos_snapshot": snap["order_nos"],
        "batch_id_snapshot": snap["batch_id"],
        "batch_no_snapshot": snap["batch_no"],
        "box_no_snapshot": snap["box_no"],
        "quantity_snapshot": snap["quantity"],
        "weight_snapshot": snap["weight"],
        "volume_snapshot": snap["volume"],
        "snapshot": snap,
        "created_by": actor,
    }


@consolidation_domain_action
def allocate_consolidation_boxes(*, consolidation_id, box_ids, actor, expected_version,
                                 idempotency_key, reason=""):
    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    ids = [int(value) for value in box_ids]
    request_hash = _canonical_hash({"consolidation_id": consolidation_id, "box_ids": sorted(ids),
                                    "expected_version": expected_version, "reason": reason})
    with transaction.atomic():
        consolidation = _lock_consolidation(consolidation_id, actor)
        replay = _event_replay(tenant=actor.tenant, key=idempotency_key,
                               action=ConsolidationEvent.Action.ALLOCATE,
                               request_hash=request_hash, actor=actor)
        if replay:
            return consolidation, replay, True
        _expected(consolidation, expected_version)
        if consolidation.status != LooseCargoConsolidation.Status.DRAFT:
            raise StateConflict("Boxes can only be allocated while the consolidation is a draft.")
        boxes = _lock_boxes(actor, ids)
        allocations = []
        before = _consolidation_snapshot(consolidation)
        for box in boxes:
            if box.batch.status != PackingBatch.Status.COMPLETED:
                raise BusinessRuleViolation("Only completed packing boxes can be allocated.")
            if not _box_route_is_loose(box):
                raise BusinessRuleViolation("Only loose-cargo boxes can be allocated.")
            old = ConsolidationBoxAllocation.objects.select_for_update().filter(
                consolidation=consolidation, box=box
            ).first()
            if old and old.state != ConsolidationBoxAllocation.State.RELEASED:
                raise StateConflict("The box is already allocated to this consolidation.")
            child = _child_key("allocate", idempotency_key, consolidation.id, box.id)
            consumption, _ = reserve_box_consumption(
                box_id=box.id, consumer_type=PackingBoxConsumption.ConsumerType.CONSOLIDATION,
                consumer_id=consolidation.id, consumer_version=consolidation.version,
                actor=actor, idempotency_key=child, reason=reason,
            )
            if old:
                values = _allocation_values(box, consumption, actor)
                for field, value in values.items():
                    setattr(old, field, value)
                old.state = ConsolidationBoxAllocation.State.ALLOCATED
                old.released_at = None
                old.version += 1
                old.save()
                allocation = old
            else:
                allocation = ConsolidationBoxAllocation(
                    consolidation=consolidation,
                    **_allocation_values(box, consumption, actor),
                )
                allocation.save()
            allocations.append(allocation)
        consolidation.version += 1
        consolidation.save(update_fields=["version", "updated_at"])
        after = _consolidation_snapshot(consolidation)
        after["allocations"] = [_allocation_snapshot(item) for item in allocations]
        event, replayed = _event(tenant=actor.tenant, action=ConsolidationEvent.Action.ALLOCATE,
                                 actor=actor, key=idempotency_key, request_hash=request_hash,
                                 before=before, after=after, reason=reason,
                                 consolidation=consolidation, expected_version=expected_version,
                                 source_type="consolidation", source_id=consolidation.id,
                                 source_version=consolidation.version)
        return consolidation, event, replayed


def allocate_consolidation_box(**kwargs):
    if "box_id" in kwargs and "box_ids" not in kwargs:
        kwargs["box_ids"] = [kwargs.pop("box_id")]
    return allocate_consolidation_boxes(**kwargs)


@consolidation_domain_action
def remove_consolidation_box(*, consolidation_id, allocation_id, actor, expected_version,
                             idempotency_key, reason=""):
    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    request_hash = _canonical_hash({"consolidation_id": consolidation_id, "allocation_id": allocation_id,
                                    "expected_version": expected_version, "reason": reason})
    with transaction.atomic():
        consolidation = _lock_consolidation(consolidation_id, actor)
        replay = _event_replay(tenant=actor.tenant, key=idempotency_key,
                               action=ConsolidationEvent.Action.REMOVE,
                               request_hash=request_hash, actor=actor)
        if replay:
            return ConsolidationBoxAllocation.objects.get(pk=replay.allocation_id), replay, True
        _expected(consolidation, expected_version)
        if consolidation.status != LooseCargoConsolidation.Status.DRAFT:
            raise StateConflict("Boxes cannot be removed after release.")
        allocation = ConsolidationBoxAllocation.objects.select_for_update().filter(
            pk=allocation_id, tenant=actor.tenant, consolidation=consolidation
        ).first()
        if allocation is None:
            raise ScopedResourceNotFound("Consolidation allocation is not available in this tenant.")
        if allocation.state != ConsolidationBoxAllocation.State.ALLOCATED:
            raise StateConflict("Only an allocated box can be removed before release.")
        child = _child_key("remove", idempotency_key, allocation.id, allocation.packing_box_consumption_id)
        release_box_consumption(consumption_id=allocation.packing_box_consumption_id, actor=actor,
                                idempotency_key=child, reason=reason or "Removed before release")
        before = {"allocation": _allocation_snapshot(allocation), "consolidation": _consolidation_snapshot(consolidation)}
        allocation.state = ConsolidationBoxAllocation.State.RELEASED
        allocation.released_at = timezone.now()
        allocation.version += 1
        allocation.save(update_fields=["state", "released_at", "version", "updated_at"])
        consolidation.version += 1
        consolidation.save(update_fields=["version", "updated_at"])
        after = {"allocation": _allocation_snapshot(allocation), "consolidation": _consolidation_snapshot(consolidation)}
        event, replayed = _event(tenant=actor.tenant, action=ConsolidationEvent.Action.REMOVE,
                                 actor=actor, key=idempotency_key, request_hash=request_hash,
                                 before=before, after=after, reason=reason, consolidation=consolidation,
                                 allocation=allocation, box=allocation.box,
                                 expected_version=expected_version, source_type="consolidation_allocation",
                                 source_id=allocation.id, source_version=allocation.version)
        return allocation, event, replayed


@consolidation_domain_action
def release_consolidation(*, consolidation_id, actor, expected_version, idempotency_key, reason=""):
    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    request_hash = _canonical_hash({"consolidation_id": consolidation_id, "expected_version": expected_version,
                                    "reason": reason})
    with transaction.atomic():
        consolidation = _lock_consolidation(consolidation_id, actor)
        replay = _event_replay(tenant=actor.tenant, key=idempotency_key,
                               action=ConsolidationEvent.Action.RELEASE,
                               request_hash=request_hash, actor=actor)
        if replay:
            return consolidation, replay, True
        _expected(consolidation, expected_version)
        if consolidation.status != LooseCargoConsolidation.Status.DRAFT:
            raise StateConflict("Only a draft consolidation can be released.")
        site = ConsolidationSite.objects.select_for_update().get(pk=consolidation.site_id)
        _require_site(
            site,
            consolidation.region_code,
            at=timezone.now(),
            planned_times=(consolidation.collection_cutoff_at, consolidation.expected_dispatch_at),
        )
        allocations = list(ConsolidationBoxAllocation.objects.select_for_update().filter(
            tenant=actor.tenant, consolidation=consolidation
        ).order_by("box_id", "id"))
        active = [item for item in allocations if item.state != ConsolidationBoxAllocation.State.RELEASED]
        if not active:
            raise BusinessRuleViolation("A consolidation must contain at least one allocated box before release.")
        if any(item.state != ConsolidationBoxAllocation.State.ALLOCATED for item in active):
            raise StateConflict("Only allocated boxes can be frozen in the initial release.")
        before = _consolidation_snapshot(consolidation)
        consolidation.status = LooseCargoConsolidation.Status.RELEASED
        consolidation.released_by = actor
        consolidation.released_at = timezone.now()
        consolidation.release_site_snapshot = _site_snapshot(site)
        consolidation.release_allocation_snapshot = [_allocation_snapshot(item) for item in active]
        consolidation.version += 1
        consolidation.save(update_fields=["status", "released_by", "released_at", "release_site_snapshot",
                                          "release_allocation_snapshot", "version", "updated_at"])
        after = _consolidation_snapshot(consolidation)
        after["site_snapshot"] = consolidation.release_site_snapshot
        after["allocation_snapshot"] = consolidation.release_allocation_snapshot
        event, replayed = _event(tenant=actor.tenant, action=ConsolidationEvent.Action.RELEASE,
                                 actor=actor, key=idempotency_key, request_hash=request_hash,
                                 before=before, after=after, reason=reason, site=site,
                                 consolidation=consolidation, expected_version=expected_version,
                                 source_type="loose_cargo_consolidation", source_id=consolidation.id,
                                 source_version=consolidation.version)
        return consolidation, event, replayed


@consolidation_domain_action
def receive_consolidation_box(*, consolidation_id, allocation_id, actor, expected_version,
                              idempotency_key, reason=""):
    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    request_hash = _canonical_hash({"consolidation_id": consolidation_id, "allocation_id": allocation_id,
                                    "expected_version": expected_version, "reason": reason})
    with transaction.atomic():
        consolidation = _lock_consolidation(consolidation_id, actor)
        allocation = ConsolidationBoxAllocation.objects.select_for_update().select_related("box").filter(
            pk=allocation_id, tenant=actor.tenant, consolidation=consolidation
        ).first()
        if allocation is None:
            raise ScopedResourceNotFound("Consolidation allocation is not available in this tenant.")
        replay = _event_replay(tenant=actor.tenant, key=idempotency_key,
                               action=ConsolidationEvent.Action.RECEIVE,
                               request_hash=request_hash, actor=actor)
        if replay:
            return allocation, replay, True
        _expected(consolidation, expected_version)
        if consolidation.status not in {LooseCargoConsolidation.Status.RELEASED,
                                         LooseCargoConsolidation.Status.RECEIVING}:
            raise StateConflict("Consolidation is not accepting receipt confirmations.")
        if allocation.state == ConsolidationBoxAllocation.State.RECEIVED:
            raise StateConflict("The box has already been received; reuse its original key to replay.")
        if allocation.state not in {ConsolidationBoxAllocation.State.ALLOCATED,
                                    ConsolidationBoxAllocation.State.HANDOVER_SUBMITTED,
                                    ConsolidationBoxAllocation.State.EXCEPTION}:
            raise StateConflict("This allocation cannot be received in its current state.")
        child = _child_key("receive", idempotency_key, allocation.id, allocation.packing_box_consumption_id)
        consumption, _ = commit_box_consumption(consumption_id=allocation.packing_box_consumption_id,
                                                 actor=actor, idempotency_key=child,
                                                 reason=reason or "Internal consolidation receipt")
        before = {"allocation": _allocation_snapshot(allocation), "consolidation": _consolidation_snapshot(consolidation)}
        allocation.state = ConsolidationBoxAllocation.State.RECEIVED
        allocation.received_by = actor
        allocation.received_at = timezone.now()
        allocation.version += 1
        allocation.save(update_fields=["state", "received_by", "received_at", "version", "updated_at"])
        if consolidation.status == LooseCargoConsolidation.Status.RELEASED:
            consolidation.status = LooseCargoConsolidation.Status.RECEIVING
        consolidation.version += 1
        consolidation.save(update_fields=["status", "version", "updated_at"])
        after = {"allocation": _allocation_snapshot(allocation), "consolidation": _consolidation_snapshot(consolidation),
                 "consumption_id": consumption.id}
        event, replayed = _event(tenant=actor.tenant, action=ConsolidationEvent.Action.RECEIVE,
                                 actor=actor, key=idempotency_key, request_hash=request_hash,
                                 before=before, after=after, reason=reason, consolidation=consolidation,
                                 allocation=allocation, box=allocation.box,
                                 expected_version=expected_version, source_type="consolidation_allocation",
                                 source_id=allocation.id, source_version=allocation.version)
        return allocation, event, replayed


def receive_consolidation(**kwargs):
    return receive_consolidation_box(**kwargs)


@consolidation_domain_action
def mark_consolidation_exception(*, consolidation_id, allocation_id, actor, expected_version,
                                 idempotency_key, reason, exception_code=""):
    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    if not str(reason or "").strip():
        raise ValidationError({"reason": "An exception reason is required."})
    request_hash = _canonical_hash({"consolidation_id": consolidation_id, "allocation_id": allocation_id,
                                    "expected_version": expected_version, "reason": reason,
                                    "exception_code": exception_code})
    with transaction.atomic():
        consolidation = _lock_consolidation(consolidation_id, actor)
        allocation = ConsolidationBoxAllocation.objects.select_for_update().filter(
            pk=allocation_id, tenant=actor.tenant, consolidation=consolidation
        ).first()
        if allocation is None:
            raise ScopedResourceNotFound("Consolidation allocation is not available in this tenant.")
        replay = _event_replay(tenant=actor.tenant, key=idempotency_key,
                               action=ConsolidationEvent.Action.EXCEPTION,
                               request_hash=request_hash, actor=actor)
        if replay:
            return allocation, replay, True
        _expected(consolidation, expected_version)
        if consolidation.status not in {LooseCargoConsolidation.Status.RELEASED,
                                         LooseCargoConsolidation.Status.RECEIVING}:
            raise StateConflict("Exceptions can only be recorded after release and before transfer.")
        if allocation.state not in {
            ConsolidationBoxAllocation.State.ALLOCATED,
            ConsolidationBoxAllocation.State.HANDOVER_SUBMITTED,
        }:
            raise StateConflict("Only an allocated or handover-submitted box can be marked as an exception.")
        before = {"allocation": _allocation_snapshot(allocation), "consolidation": _consolidation_snapshot(consolidation)}
        allocation.state = ConsolidationBoxAllocation.State.EXCEPTION
        allocation.exception_code = str(exception_code or "")
        allocation.exception_note = str(reason).strip()
        allocation.version += 1
        allocation.save(update_fields=["state", "exception_code", "exception_note", "version", "updated_at"])
        if consolidation.status == LooseCargoConsolidation.Status.RELEASED:
            consolidation.status = LooseCargoConsolidation.Status.RECEIVING
        consolidation.version += 1
        consolidation.save(update_fields=["status", "version", "updated_at"])
        after = {"allocation": _allocation_snapshot(allocation), "consolidation": _consolidation_snapshot(consolidation)}
        event, replayed = _event(tenant=actor.tenant, action=ConsolidationEvent.Action.EXCEPTION,
                                 actor=actor, key=idempotency_key, request_hash=request_hash,
                                 before=before, after=after, reason=reason, consolidation=consolidation,
                                 allocation=allocation, box=allocation.box,
                                 expected_version=expected_version, source_type="consolidation_allocation",
                                 source_id=allocation.id, source_version=allocation.version)
        return allocation, event, replayed


def exception_consolidation(**kwargs):
    return mark_consolidation_exception(**kwargs)


@consolidation_domain_action
def controlled_release_consolidation_box(*, consolidation_id, allocation_id, actor, expected_version,
                                         idempotency_key, reason):
    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    if not str(reason or "").strip():
        raise ValidationError({"reason": "A controlled release reason is required."})
    request_hash = _canonical_hash({"consolidation_id": consolidation_id, "allocation_id": allocation_id,
                                    "expected_version": expected_version, "reason": reason})
    with transaction.atomic():
        consolidation = _lock_consolidation(consolidation_id, actor)
        allocation = ConsolidationBoxAllocation.objects.select_for_update().filter(
            pk=allocation_id, tenant=actor.tenant, consolidation=consolidation
        ).first()
        if allocation is None:
            raise ScopedResourceNotFound("Consolidation allocation is not available in this tenant.")
        replay = _event_replay(tenant=actor.tenant, key=idempotency_key,
                               action=ConsolidationEvent.Action.CONTROLLED_RELEASE,
                               request_hash=request_hash, actor=actor)
        if replay:
            return allocation, replay, True
        _expected(consolidation, expected_version)
        if allocation.state != ConsolidationBoxAllocation.State.EXCEPTION:
            raise StateConflict("Only an exception allocation can be controlled-released.")
        child = _child_key("controlled-release", idempotency_key, allocation.id, allocation.packing_box_consumption_id)
        release_box_consumption(consumption_id=allocation.packing_box_consumption_id, actor=actor,
                                idempotency_key=child, reason=reason)
        before = {"allocation": _allocation_snapshot(allocation), "consolidation": _consolidation_snapshot(consolidation)}
        allocation.state = ConsolidationBoxAllocation.State.RELEASED
        allocation.exception_note = str(reason).strip()
        allocation.released_at = timezone.now()
        allocation.version += 1
        allocation.save(update_fields=["state", "exception_note", "released_at", "version", "updated_at"])
        consolidation.version += 1
        consolidation.save(update_fields=["version", "updated_at"])
        after = {"allocation": _allocation_snapshot(allocation), "consolidation": _consolidation_snapshot(consolidation)}
        event, replayed = _event(tenant=actor.tenant, action=ConsolidationEvent.Action.CONTROLLED_RELEASE,
                                 actor=actor, key=idempotency_key, request_hash=request_hash,
                                 before=before, after=after, reason=reason, consolidation=consolidation,
                                 allocation=allocation, box=allocation.box,
                                 expected_version=expected_version, source_type="consolidation_allocation",
                                 source_id=allocation.id, source_version=allocation.version)
        return allocation, event, replayed


def release_consolidation_exception(**kwargs):
    return controlled_release_consolidation_box(**kwargs)


@consolidation_domain_action
def ready_consolidation(*, consolidation_id, actor, expected_version, idempotency_key, reason=""):
    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    request_hash = _canonical_hash({"consolidation_id": consolidation_id, "expected_version": expected_version,
                                    "reason": reason})
    with transaction.atomic():
        consolidation = _lock_consolidation(consolidation_id, actor)
        replay = _event_replay(tenant=actor.tenant, key=idempotency_key,
                               action=ConsolidationEvent.Action.READY,
                               request_hash=request_hash, actor=actor)
        if replay:
            return consolidation, replay, True
        _expected(consolidation, expected_version)
        if consolidation.status not in {LooseCargoConsolidation.Status.RELEASED,
                                         LooseCargoConsolidation.Status.RECEIVING}:
            raise StateConflict("Only a released/receiving consolidation can be marked ready.")
        allocations = list(ConsolidationBoxAllocation.objects.select_for_update().filter(
            tenant=actor.tenant, consolidation=consolidation
        ).order_by("box_id", "id"))
        active = [item for item in allocations if item.state != ConsolidationBoxAllocation.State.RELEASED]
        if not active:
            raise BusinessRuleViolation("A consolidation must have a valid allocation before ready.")
        # EXCEPTION is an intermediate hold, never a shipment-ready outcome:
        # it must be received (which commits the packing consumption) or
        # controlled-released (which removes the allocation) first.
        allowed = {ConsolidationBoxAllocation.State.RECEIVED}
        if any(item.state not in allowed for item in active):
            raise StateConflict("Every active box must be received or have a recorded exception before ready.")
        before = _consolidation_snapshot(consolidation)
        consolidation.status = LooseCargoConsolidation.Status.READY_FOR_SHIPMENT
        consolidation.ready_by = actor
        consolidation.ready_at = timezone.now()
        consolidation.version += 1
        consolidation.save(update_fields=["status", "ready_by", "ready_at", "version", "updated_at"])
        after = _consolidation_snapshot(consolidation)
        after["allocations"] = [_allocation_snapshot(item) for item in active]
        event, replayed = _event(tenant=actor.tenant, action=ConsolidationEvent.Action.READY,
                                 actor=actor, key=idempotency_key, request_hash=request_hash,
                                 before=before, after=after, reason=reason,
                                 consolidation=consolidation, expected_version=expected_version,
                                 source_type="loose_cargo_consolidation", source_id=consolidation.id,
                                 source_version=consolidation.version)
        return consolidation, event, replayed


@consolidation_domain_action
def transfer_consolidation_allocation_to_shipment(*, allocation_id, shipment, actor,
                                                  target_consumer_version=1,
                                                  idempotency_key, reason="", channel="internal"):
    """Typed handshake used by shipping to transfer one received box.

    The target is deliberately a ``LooseCargoShipment`` instance, never an
    arbitrary integer consumer ID.  The packing transfer and consolidation
    state/event updates share the caller's transaction, so a batch caller can
    roll back every box on the first conflict.
    """

    from apps.shipping.models import LooseCargoShipment

    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    if not isinstance(shipment, LooseCargoShipment) or shipment.tenant_id != actor.tenant_id:
        raise ScopedResourceNotFound("Shipment is not available in the authorized tenant.")
    request_hash = _canonical_hash({
        "allocation_id": int(allocation_id),
        "shipment_id": int(shipment.id),
        "target_consumer_version": int(target_consumer_version),
        "reason": reason,
        "channel": channel,
    })
    with transaction.atomic():
        target = LooseCargoShipment.objects.select_for_update().filter(
            pk=shipment.id, tenant=actor.tenant,
        ).first()
        if target is None:
            raise ScopedResourceNotFound("Shipment is not available in the authorized tenant.")
        consolidation_allocation = ConsolidationBoxAllocation.objects.select_for_update().select_related(
            "consolidation", "box", "packing_box_consumption",
        ).filter(pk=allocation_id, tenant=actor.tenant).first()
        if consolidation_allocation is None:
            raise ScopedResourceNotFound("Consolidation allocation is not available in this tenant.")
        consolidation = LooseCargoConsolidation.objects.select_for_update().filter(
            pk=consolidation_allocation.consolidation_id, tenant=actor.tenant,
        ).first()
        if consolidation is None:
            raise ScopedResourceNotFound("Consolidation is not available in this tenant.")
        replay = _event_replay(
            tenant=actor.tenant,
            key=idempotency_key,
            action=ConsolidationEvent.Action.TRANSFER,
            request_hash=request_hash,
            actor=actor,
        )
        if replay:
            return consolidation_allocation, replay, True, None
        if target.status not in {LooseCargoShipment.Status.DRAFT, LooseCargoShipment.Status.LOADING}:
            raise StateConflict("Shipment is not accepting transferred boxes.")
        if consolidation.status != LooseCargoConsolidation.Status.READY_FOR_SHIPMENT:
            raise StateConflict("Only a ready-for-shipment consolidation can be transferred.")
        if consolidation.region_code != target.region_code:
            raise BusinessRuleViolation("Consolidation and shipment regions are incompatible.")
        if consolidation_allocation.state != ConsolidationBoxAllocation.State.RECEIVED:
            raise StateConflict("Only received consolidation allocations can be transferred.")
        source_consumption = consolidation_allocation.packing_box_consumption
        if (
            source_consumption.consumer_type != PackingBoxConsumption.ConsumerType.CONSOLIDATION
            or source_consumption.state != PackingBoxConsumption.State.COMMITTED
            or source_consumption.active_guard is not True
        ):
            raise StateConflict("The consolidation packing consumer is not an active received slot.")
        before = {
            "allocation": _allocation_snapshot(consolidation_allocation),
            "consolidation": _consolidation_snapshot(consolidation),
            "shipment_id": target.id,
        }
        target_consumption, _ = transfer_box_consumption(
            consumption_id=source_consumption.id,
            target_consumer_type=PackingBoxConsumption.ConsumerType.SHIPMENT,
            target_consumer_id=target.id,
            actor=actor,
            idempotency_key=f"{idempotency_key}:packing-transfer",
            target_consumer_version=int(target_consumer_version),
            reason=reason or "Consolidation to shipment transfer",
        )
        consolidation_allocation.state = ConsolidationBoxAllocation.State.TRANSFERRED
        consolidation_allocation.version += 1
        with _consolidation_domain_write_context():
            consolidation_allocation.save(update_fields=["state", "version", "updated_at"])
        active = list(consolidation.allocations.select_for_update().exclude(
            state=ConsolidationBoxAllocation.State.RELEASED,
        ))
        if active and all(item.state == ConsolidationBoxAllocation.State.TRANSFERRED for item in active):
            consolidation.status = LooseCargoConsolidation.Status.TRANSFERRED
            consolidation.version += 1
            consolidation.save(update_fields=["status", "version", "updated_at"])
        after = {
            "allocation": _allocation_snapshot(consolidation_allocation),
            "consolidation": _consolidation_snapshot(consolidation),
            "shipment_id": target.id,
            "shipment_consumption_id": target_consumption.id,
        }
        event, replayed = _event(
            tenant=actor.tenant,
            action=ConsolidationEvent.Action.TRANSFER,
            actor=actor,
            key=idempotency_key,
            request_hash=request_hash,
            before=before,
            after=after,
            reason=reason,
            consolidation=consolidation,
            allocation=consolidation_allocation,
            box=consolidation_allocation.box,
            expected_version=target_consumer_version,
            source_type="consolidation_to_shipment",
            source_id=target.id,
            source_version=consolidation_allocation.version,
        )
        return consolidation_allocation, event, replayed, target_consumption


@consolidation_domain_action
def cancel_consolidation(*, consolidation_id, actor, expected_version, idempotency_key, reason):
    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    if not str(reason or "").strip():
        raise ValidationError({"reason": "A cancellation reason is required."})
    request_hash = _canonical_hash({"consolidation_id": consolidation_id, "expected_version": expected_version,
                                    "reason": reason})
    with transaction.atomic():
        consolidation = _lock_consolidation(consolidation_id, actor)
        replay = _event_replay(tenant=actor.tenant, key=idempotency_key,
                               action=ConsolidationEvent.Action.CANCEL,
                               request_hash=request_hash, actor=actor)
        if replay:
            return consolidation, replay, True
        _expected(consolidation, expected_version)
        if consolidation.status not in {LooseCargoConsolidation.Status.DRAFT,
                                         LooseCargoConsolidation.Status.RELEASED}:
            raise StateConflict("Only an unreceived draft/released consolidation can be cancelled.")
        allocations = list(ConsolidationBoxAllocation.objects.select_for_update().filter(
            tenant=actor.tenant, consolidation=consolidation
        ).order_by("box_id", "id"))
        if any(item.state != ConsolidationBoxAllocation.State.ALLOCATED for item in allocations):
            raise StateConflict("Cancellation is allowed only while every box remains allocated.")
        before = _consolidation_snapshot(consolidation)
        for allocation in allocations:
            child = _child_key("cancel", idempotency_key, allocation.id, allocation.packing_box_consumption_id)
            release_box_consumption(consumption_id=allocation.packing_box_consumption_id, actor=actor,
                                    idempotency_key=child, reason=reason)
            allocation.state = ConsolidationBoxAllocation.State.RELEASED
            allocation.released_at = timezone.now()
            allocation.version += 1
            allocation.save(update_fields=["state", "released_at", "version", "updated_at"])
        consolidation.status = LooseCargoConsolidation.Status.CANCELLED
        consolidation.cancelled_by = actor
        consolidation.cancelled_at = timezone.now()
        consolidation.cancelled_reason = str(reason).strip()
        consolidation.version += 1
        consolidation.save(update_fields=["status", "cancelled_by", "cancelled_at", "cancelled_reason",
                                          "version", "updated_at"])
        after = _consolidation_snapshot(consolidation)
        after["allocations"] = [_allocation_snapshot(item) for item in allocations]
        event, replayed = _event(tenant=actor.tenant, action=ConsolidationEvent.Action.CANCEL,
                                 actor=actor, key=idempotency_key, request_hash=request_hash,
                                 before=before, after=after, reason=reason, consolidation=consolidation,
                                 expected_version=expected_version, source_type="loose_cargo_consolidation",
                                 source_id=consolidation.id, source_version=consolidation.version)
        return consolidation, event, replayed


@consolidation_domain_action
def submit_consolidation_handover(*, consolidation_id, allocation_id, actor, expected_version,
                                  evidence_ids, idempotency_key, handover_method="",
                                  handover_reference="", reason="", channel="external"):
    """Atomically bind accepted controlled evidence to one released allocation.

    This is the only attachment/consolidation integration in ATTACH-1.  It is
    deliberately a domain entry point, not an API: caller identity, tenant,
    supplier owner, allocation and release version are all re-read under the
    same transaction before the allocation state changes.
    """

    if not actor or not getattr(actor, "is_authenticated", False) or not actor.is_active or not actor.tenant_id:
        raise PermissionDenied("An active tenant-bound actor is required.")
    if actor.user_type not in {CustomUser.UserType.INTERNAL, CustomUser.UserType.EXTERNAL}:
        raise PermissionDenied("Only internal or bound supplier actors can submit handover evidence.")
    _validate_idempotency_key(idempotency_key)
    try:
        normalized_ids = sorted({int(value) for value in evidence_ids})
    except (TypeError, ValueError) as exc:
        raise ValidationError({"evidence_ids": "Positive evidence IDs are required."}) from exc
    if not normalized_ids or len(normalized_ids) > 9 or normalized_ids[0] <= 0:
        raise BusinessRuleViolation("At least one and at most nine evidence IDs are required.")
    if actor.user_type == CustomUser.UserType.EXTERNAL:
        profile = getattr(actor, "external_profile", None)
        if profile is None or not profile.supplier_id:
            raise PermissionDenied("A valid supplier binding is required.")
    request_hash = _canonical_hash({
        "consolidation_id": consolidation_id,
        "allocation_id": allocation_id,
        "expected_version": expected_version,
        "evidence_ids": normalized_ids,
        "handover_method": handover_method,
        "handover_reference": handover_reference,
        "reason": reason,
        "channel": channel,
    })
    with transaction.atomic():
        consolidation = _lock_consolidation(consolidation_id, actor)
        allocation = ConsolidationBoxAllocation.objects.select_for_update().filter(
            pk=allocation_id,
            tenant=actor.tenant,
            consolidation=consolidation,
        ).first()
        if allocation is None:
            raise ScopedResourceNotFound("Consolidation allocation is not available in this tenant.")
        replay = _event_replay(
            tenant=actor.tenant,
            key=idempotency_key,
            action=ConsolidationEvent.Action.HANDOVER_SUBMIT,
            request_hash=request_hash,
            actor=actor,
        )
        if replay:
            return allocation, replay, True
        _expected(consolidation, expected_version)
        if consolidation.status not in {
            LooseCargoConsolidation.Status.RELEASED,
            LooseCargoConsolidation.Status.RECEIVING,
        }:
            raise StateConflict("Handover evidence requires a released/receiving consolidation.")
        if allocation.state != ConsolidationBoxAllocation.State.ALLOCATED:
            raise StateConflict("Only an allocated box can receive its first handover submission.")
        if actor.user_type == CustomUser.UserType.EXTERNAL:
            if actor.external_profile.supplier_id != allocation.supplier_id_snapshot:
                raise ScopedResourceNotFound("Consolidation allocation is not available to this supplier.")
            _require_handover_capability(actor, allocation.supplier_id_snapshot)
        release_event = ConsolidationEvent.objects.filter(
            tenant=actor.tenant,
            consolidation=consolidation,
            action=ConsolidationEvent.Action.RELEASE,
        ).order_by("-source_version", "-created_at", "-id").first()
        release_version = release_event.source_version if release_event else None
        if not release_version:
            raise StateConflict("The consolidation has no verifiable release version.")
        from apps.files.models import ControlledAttachment

        evidence = list(ControlledAttachment.objects.select_for_update().filter(
            tenant=actor.tenant,
            pk__in=normalized_ids,
        ).order_by("pk"))
        if len(evidence) != len(normalized_ids):
            raise ScopedResourceNotFound("One or more evidence assets are not available in this tenant.")
        for item in evidence:
            if item.state != ControlledAttachment.State.ACCEPTED:
                raise StateConflict("Only accepted evidence can be submitted for handover.")
            if (
                item.business_type != "consolidation_handover"
                or item.business_id != str(allocation.id)
                or item.business_version != int(release_version)
                or item.owner_type != "supplier"
                or item.owner_id != allocation.supplier_id_snapshot
            ):
                raise BusinessRuleViolation("Evidence binding does not match this allocation release version.")
            if actor.user_type == CustomUser.UserType.EXTERNAL and item.owner_id != actor.external_profile.supplier_id:
                raise ScopedResourceNotFound("Evidence is not available to this supplier.")
        before = {
            "allocation": _allocation_snapshot(allocation),
            "consolidation": _consolidation_snapshot(consolidation),
        }
        allocation.state = ConsolidationBoxAllocation.State.HANDOVER_SUBMITTED
        allocation.handover_method = str(handover_method or "")
        allocation.handover_reference = str(handover_reference or "")
        # Persist the complete immutable set in a structured JSON column.  The
        # legacy varchar is retained only as a compatibility pointer to the
        # first evidence ID; it must never be used as the authoritative set.
        allocation.evidence_ids = normalized_ids
        allocation.handover_evidence_id = str(normalized_ids[0])
        allocation.submitted_by = actor
        allocation.submitted_at = timezone.now()
        allocation.version += 1
        allocation.save(update_fields=[
            "state", "handover_method", "handover_reference", "evidence_ids", "handover_evidence_id",
            "submitted_by", "submitted_at", "version", "updated_at",
        ])
        if consolidation.status == LooseCargoConsolidation.Status.RELEASED:
            consolidation.status = LooseCargoConsolidation.Status.RECEIVING
        consolidation.version += 1
        consolidation.save(update_fields=["status", "version", "updated_at"])
        after = {
            "allocation": _allocation_snapshot(allocation),
            "consolidation": _consolidation_snapshot(consolidation),
            "evidence_ids": normalized_ids,
            "release_version": int(release_version),
        }
        event, replayed = _event(
            tenant=actor.tenant,
            action=ConsolidationEvent.Action.HANDOVER_SUBMIT,
            actor=actor,
            key=idempotency_key,
            request_hash=request_hash,
            before=before,
            after=after,
            reason=reason,
            consolidation=consolidation,
            allocation=allocation,
            box=allocation.box,
            expected_version=expected_version,
            source_type="consolidation_handover",
            source_id=allocation.id,
            source_version=allocation.version,
        )
        return allocation, event, replayed


# Domain-vocabulary aliases for future API adapters.
create_site = create_consolidation_site
update_site = update_consolidation_site
deactivate_site = deactivate_consolidation_site
create_consolidation = create_loose_cargo_consolidation
update_consolidation = update_loose_cargo_consolidation
allocate_box = allocate_consolidation_box
allocate_boxes = allocate_consolidation_boxes
remove_box = remove_consolidation_box
release = release_consolidation
receive_box = receive_consolidation_box
mark_exception = mark_consolidation_exception
controlled_release = controlled_release_consolidation_box
ready = ready_consolidation
cancel = cancel_consolidation
submit_handover = submit_consolidation_handover
submit_consolidation_evidence = submit_consolidation_handover
