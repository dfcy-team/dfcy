"""HTTP adapters for consolidation, supplier handover and local attachments.

Every write delegates to ``apps.consolidation.services`` or
``apps.files.services``.  The adapters intentionally return compact DTOs and
never serialize event ``before``/``after`` payloads to external channels.
"""

from __future__ import annotations

import base64
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Prefetch
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError

from apps.common.responses import success_response
from apps.common.exceptions import ContractViolation
from apps.accounts.miniapp_permissions import IsMiniAppToken
from apps.files.models import AttachmentUploadSession, ControlledAttachment
from apps.files.services import (
    create_attachment_upload_session,
    finalize_attachment,
)

from .api_serializers import (
    AllocationActionSerializer,
    SimpleAllocationActionSerializer,
    ExceptionActionSerializer,
    BoxesActionSerializer,
    ConsolidationCreateSerializer,
    ConsolidationUpdateSerializer,
    HandoverSerializer,
    SiteCreateSerializer,
    SiteUpdateSerializer,
    TransferSerializer,
    SupplierCapabilitySerializer,
    allocation_dto,
    consolidation_dto,
    site_dto,
    supplier_assignment_dto,
    supplier_capability_dto,
)
from .api_support import (
    INTERNAL,
    MINIAPP,
    SUPPLIER_WEB,
    authorized_consolidation,
    authorized_shipment,
    authorize_box_ids_for_scope,
    authorized_site,
    assert_channel,
    consolidation_dimensions,
    event_result,
    internal_permissions,
    page_payload,
    require_internal,
    require_json,
    require_key,
    require_supplier,
    supplier_allocation,
    supplier_permissions,
)
from .models import ConsolidationBoxAllocation, ConsolidationSite, LooseCargoConsolidation, ConsolidationSupplierCapability
from .services import (
    allocate_consolidation_boxes,
    cancel_consolidation,
    controlled_release_consolidation_box,
    create_consolidation_site,
    create_loose_cargo_consolidation,
    deactivate_consolidation_site,
    mark_consolidation_exception,
    receive_consolidation_box,
    release_consolidation,
    remove_consolidation_box,
    ready_consolidation,
    submit_consolidation_handover,
    set_consolidation_supplier_capability,
    update_consolidation_site,
    update_loose_cargo_consolidation,
)
from apps.shipping.models import LooseCargoShipment
from apps.shipping.services import allocate_shipment_boxes


def _strict_query(request, allowed=()):
    unknown = set(request.query_params) - set(allowed)
    if unknown:
        raise ValidationError({"unknown_query": f"Unknown query parameters: {sorted(unknown)}"})


def _resource(result, transform, status=200):
    obj, event, replayed = result
    if status == 200:
        return event_result(obj, event, replayed, transform)
    response = success_response(transform(obj), status=status)
    response["Idempotency-Replayed"] = "true" if replayed else "false"
    return response


def _service_error(exc):
    if isinstance(exc, DjangoValidationError):
        raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages)
    raise exc


@api_view(["GET", "POST"])
@internal_permissions()
def internal_site_collection(request):
    assert_channel(request, INTERNAL)
    if request.method == "GET":
        _strict_query(request, {"page", "page_size", "region_code", "is_active"})
        sites, _ = authorized_site(ConsolidationSite.objects.order_by("site_code"), request.user, "supply.consolidation_site.view")
        if request.query_params.get("region_code"):
            sites = [item for item in sites if item.region_code == request.query_params["region_code"]]
        if request.query_params.get("is_active") in {"true", "false"}:
            expected = request.query_params["is_active"] == "true"
            sites = [item for item in sites if item.is_active == expected]
        return success_response(page_payload(request, sites, lambda item: site_dto(item, internal=True)))
    require_json(request)
    scopes = require_internal(request.user, "supply.consolidation_site.manage")
    payload = SiteCreateSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    data = payload.validated_data
    # CUSTOM create may only target declared site IDs when supplied; a site
    # does not yet have a persisted ID, so a custom scope must be ALL for site
    # provisioning.  This is safer than allowing an unbounded create.
    if not any(scope["scope_type"] == "all" for scope in scopes):
        raise ValidationError({"data_scope": "A CUSTOM scope cannot provision an undeclared site ID."})
    key = require_key(request)
    result = create_consolidation_site(actor=request.user, idempotency_key=key, **data)
    return _resource(result, lambda item: site_dto(item, internal=True), status=201)


@api_view(["GET", "PUT"])
@internal_permissions()
def internal_site_detail(request, pk):
    assert_channel(request, INTERNAL)
    if request.method == "GET":
        site, _ = authorized_site(ConsolidationSite.objects, request.user, "supply.consolidation_site.view", pk=pk)
        return success_response(site_dto(site, internal=True))
    require_json(request)
    site, _ = authorized_site(ConsolidationSite.objects, request.user, "supply.consolidation_site.manage", pk=pk)
    payload = SiteUpdateSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    data = dict(payload.validated_data)
    expected = data.pop("expected_version")
    key = require_key(request)
    if "timezone" in data:
        data["timezone"] = data.pop("timezone")
    result = update_consolidation_site(site_id=site.id, actor=request.user, expected_version=expected, idempotency_key=key, **data)
    return _resource(result, lambda item: site_dto(item, internal=True))


@api_view(["POST"])
@internal_permissions()
def internal_site_deactivate(request, pk):
    assert_channel(request, INTERNAL)
    require_json(request)
    site, _ = authorized_site(ConsolidationSite.objects, request.user, "supply.consolidation_site.manage", pk=pk)
    payload = SimpleAllocationActionSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    data = payload.validated_data
    result = deactivate_consolidation_site(site_id=site.id, actor=request.user, expected_version=data["expected_version"], idempotency_key=require_key(request), reason=data.get("reason", ""))
    return _resource(result, lambda item: site_dto(item, internal=True))


def _capability_scope(request, supplier_id):
    scopes = require_internal(request.user, "supply.consolidation.manage")
    if not any(
        scope["scope_type"] == "all" or int(supplier_id) in scope["config"]["supplier_ids"]
        for scope in scopes
    ):
        from apps.common.exceptions import DataScopeDenied
        raise DataScopeDenied("Supplier capability is outside the management scope.", error_code="DATA_SCOPE_FORBIDDEN")
    return scopes


@api_view(["GET", "POST"])
@internal_permissions()
def internal_supplier_capability_collection(request, supplier_id=None):
    assert_channel(request, INTERNAL)
    if request.method == "GET":
        _strict_query(request, {"supplier_id"})
        try:
            supplier_id = int(supplier_id if supplier_id is not None else request.query_params["supplier_id"])
        except (KeyError, TypeError, ValueError):
            raise ValidationError({"supplier_id": "A positive supplier ID is required."})
        if supplier_id <= 0:
            raise ValidationError({"supplier_id": "A positive supplier ID is required."})
        _capability_scope(request, supplier_id)
        capability = ConsolidationSupplierCapability.objects.filter(tenant=request.user.tenant, supplier_id=supplier_id).first()
        if capability is None:
            from apps.common.exceptions import ScopedResourceNotFound
            raise ScopedResourceNotFound("Supplier capability is not configured.")
        return success_response(supplier_capability_dto(capability))
    require_json(request)
    payload = SupplierCapabilitySerializer(data=request.data); payload.is_valid(raise_exception=True)
    data = payload.validated_data
    _capability_scope(request, data["supplier_id"])
    expected = data.pop("expected_version", None)
    reason = data.pop("reason", "")
    result = set_consolidation_supplier_capability(
        actor=request.user, idempotency_key=require_key(request), expected_version=expected,
        reason=reason, **data,
    )
    return _resource(result, supplier_capability_dto)


def _consolidation_queryset():
    return LooseCargoConsolidation.objects.select_related("site").prefetch_related("allocations")


@api_view(["GET", "POST"])
@internal_permissions()
def internal_consolidation_collection(request):
    assert_channel(request, INTERNAL)
    if request.method == "GET":
        _strict_query(request, {"page", "page_size", "status", "site_id", "region_code"})
        items, _ = authorized_consolidation(_consolidation_queryset().order_by("-created_at"), request.user, "supply.consolidation.view")
        if request.query_params.get("status"):
            items = [item for item in items if item.status == request.query_params["status"]]
        if request.query_params.get("site_id"):
            try: site_id = int(request.query_params["site_id"])
            except ValueError: raise ValidationError({"site_id": "A positive integer is required."})
            items = [item for item in items if item.site_id == site_id]
        if request.query_params.get("region_code"):
            items = [item for item in items if item.region_code == request.query_params["region_code"]]
        return success_response(page_payload(request, items, lambda item: consolidation_dto(item, internal=True)))
    require_json(request)
    scopes = require_internal(request.user, "supply.consolidation.create")
    payload = ConsolidationCreateSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    data = payload.validated_data
    site = ConsolidationSite.objects.filter(tenant=request.user.tenant, pk=data["site_id"]).first()
    if site is None:
        from apps.common.exceptions import ScopedResourceNotFound
        raise ScopedResourceNotFound("Consolidation site is not available in the authorized scope.")
    if not any(scope["scope_type"] == "all" or site.id in scope["config"]["consolidation_site_ids"] for scope in scopes):
        from apps.common.exceptions import DataScopeDenied
        raise DataScopeDenied("The site is outside the create data scope.", error_code="DATA_SCOPE_FORBIDDEN")
    key = require_key(request)
    result = create_loose_cargo_consolidation(actor=request.user, idempotency_key=key, **data)
    return _resource(result, lambda item: consolidation_dto(item, internal=True), status=201)


@api_view(["GET", "PUT"])
@internal_permissions()
def internal_consolidation_detail(request, pk):
    assert_channel(request, INTERNAL)
    if request.method == "GET":
        item, _ = authorized_consolidation(_consolidation_queryset(), request.user, "supply.consolidation.view", pk=pk)
        return success_response(consolidation_dto(item, internal=True))
    require_json(request)
    item, _ = authorized_consolidation(_consolidation_queryset(), request.user, "supply.consolidation.manage", pk=pk)
    payload = ConsolidationUpdateSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    data = dict(payload.validated_data)
    expected = data.pop("expected_version")
    result = update_loose_cargo_consolidation(consolidation_id=item.id, actor=request.user, expected_version=expected, idempotency_key=require_key(request), **data)
    return _resource(result, lambda obj: consolidation_dto(obj, internal=True))


@api_view(["POST"])
@internal_permissions()
def internal_consolidation_boxes(request, pk):
    assert_channel(request, INTERNAL)
    require_json(request)
    item, scopes = authorized_consolidation(_consolidation_queryset(), request.user, "supply.consolidation.allocate", pk=pk)
    payload = BoxesActionSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    data = payload.validated_data
    authorize_box_ids_for_scope(
        request.user, scopes, box_ids=data["box_ids"], site_id=item.site_id, consolidation_id=item.id,
    )
    result = allocate_consolidation_boxes(consolidation_id=item.id, box_ids=data["box_ids"], actor=request.user, expected_version=data["expected_version"], idempotency_key=require_key(request), reason=data.get("reason", ""))
    return _resource(result, lambda obj: consolidation_dto(obj, internal=True))


def _allocation_action(request, pk, allocation_id, permission, service, *, extra=None, serializer_class=SimpleAllocationActionSerializer):
    assert_channel(request, INTERNAL)
    require_json(request)
    item, _ = authorized_consolidation(_consolidation_queryset(), request.user, permission, pk=pk)
    allocation = item.allocations.filter(pk=allocation_id).first()
    if allocation is None:
        from apps.common.exceptions import ScopedResourceNotFound
        raise ScopedResourceNotFound("Consolidation allocation is not available in the authorized scope.")
    payload = serializer_class(data=request.data)
    payload.is_valid(raise_exception=True)
    data = payload.validated_data
    kwargs = {"consolidation_id": item.id, "allocation_id": allocation.id, "actor": request.user,
              "expected_version": data["expected_version"], "idempotency_key": require_key(request),
              "reason": data.get("reason", "")}
    if extra:
        kwargs.update(extra(data))
    result = service(**kwargs)
    # The allocation services lock and update a fresh aggregate instance;
    # reload both version and allocations before constructing the DTO.
    fresh = _consolidation_queryset().get(pk=item.id)
    response = _resource((fresh, result[1], result[2]), lambda obj: consolidation_dto(obj, internal=True))
    return response


@api_view(["POST"])
@internal_permissions()
def internal_consolidation_box_remove(request, pk, allocation_id):
    return _allocation_action(request, pk, allocation_id, "supply.consolidation.allocate", remove_consolidation_box)


@api_view(["POST"])
@internal_permissions()
def internal_consolidation_release(request, pk):
    assert_channel(request, INTERNAL)
    require_json(request)
    item, _ = authorized_consolidation(_consolidation_queryset(), request.user, "supply.consolidation.release", pk=pk)
    payload = SimpleAllocationActionSerializer(data=request.data); payload.is_valid(raise_exception=True)
    data = payload.validated_data
    result = release_consolidation(consolidation_id=item.id, actor=request.user, expected_version=data["expected_version"], idempotency_key=require_key(request), reason=data.get("reason", ""))
    return _resource(result, lambda obj: consolidation_dto(obj, internal=True))


@api_view(["POST"])
@internal_permissions()
def internal_consolidation_receive(request, pk, allocation_id):
    return _allocation_action(request, pk, allocation_id, "supply.consolidation.receive", receive_consolidation_box)


@api_view(["POST"])
@internal_permissions()
def internal_consolidation_exception(request, pk, allocation_id):
    return _allocation_action(request, pk, allocation_id, "supply.consolidation.exception.manage", mark_consolidation_exception, extra=lambda data: {"exception_code": data.get("exception_code", "")}, serializer_class=ExceptionActionSerializer)


@api_view(["POST"])
@internal_permissions()
def internal_consolidation_controlled_release(request, pk, allocation_id):
    return _allocation_action(request, pk, allocation_id, "supply.consolidation.exception.manage", controlled_release_consolidation_box)


@api_view(["POST"])
@internal_permissions()
def internal_consolidation_ready(request, pk):
    assert_channel(request, INTERNAL); require_json(request)
    item, _ = authorized_consolidation(_consolidation_queryset(), request.user, "supply.consolidation.receive", pk=pk)
    payload = SimpleAllocationActionSerializer(data=request.data); payload.is_valid(raise_exception=True)
    data = payload.validated_data
    result = ready_consolidation(consolidation_id=item.id, actor=request.user, expected_version=data["expected_version"], idempotency_key=require_key(request), reason=data.get("reason", ""))
    return _resource(result, lambda obj: consolidation_dto(obj, internal=True))


@api_view(["POST"])
@internal_permissions()
def internal_consolidation_cancel(request, pk):
    assert_channel(request, INTERNAL); require_json(request)
    item, _ = authorized_consolidation(_consolidation_queryset(), request.user, "supply.consolidation.cancel", pk=pk)
    payload = SimpleAllocationActionSerializer(data=request.data); payload.is_valid(raise_exception=True)
    data = payload.validated_data
    result = cancel_consolidation(consolidation_id=item.id, actor=request.user, expected_version=data["expected_version"], idempotency_key=require_key(request), reason=data.get("reason", ""))
    return _resource(result, lambda obj: consolidation_dto(obj, internal=True))


@api_view(["POST"])
@internal_permissions()
def internal_consolidation_transfer(request, pk):
    """Expose the typed consolidation鈫抯hipment handshake.

    The shipment domain service performs the atomic source/target consumption
    transfer and locks both aggregates; this adapter only authorizes the
    source scope and validates the typed target identifier.
    """
    assert_channel(request, INTERNAL); require_json(request)
    consolidation, _ = authorized_consolidation(_consolidation_queryset(), request.user, "supply.consolidation.transfer", pk=pk)
    payload = TransferSerializer(data=request.data); payload.is_valid(raise_exception=True)
    data = payload.validated_data
    shipment = LooseCargoShipment.objects.filter(tenant=request.user.tenant, pk=data["shipment_id"]).first()
    if shipment is None:
        from apps.common.exceptions import ScopedResourceNotFound
        raise ScopedResourceNotFound("Shipment is not available in the authorized tenant.")
    # Shipment allocation permission is checked as a second write boundary;
    # no client-supplied integer is passed to the generic consumption service.
    authorized_shipment(LooseCargoShipment.objects.all(), request.user, "supply.shipment.allocate", pk=shipment.id)
    result = allocate_shipment_boxes(
        shipment_id=shipment.id, consolidation_id=consolidation.id,
        allocation_ids=data["allocation_ids"], actor=request.user,
        expected_version=data["expected_version"], idempotency_key=require_key(request),
        reason=data.get("reason", ""),
    )
    from apps.shipping.api_serializers import shipment_dto
    return _resource(result, lambda obj: shipment_dto(obj, internal=True))


def _supplier_assignments(request, *, miniapp=False, allocation_id=None):
    assert_channel(request, MINIAPP if miniapp else SUPPLIER_WEB)
    supplier_id = require_supplier(request.user)
    qs = ConsolidationBoxAllocation.objects.select_related("consolidation", "consolidation__site").prefetch_related("consolidation__allocations").filter(
        tenant=request.user.tenant, supplier_id_snapshot=supplier_id,
        consolidation__status__in={
            LooseCargoConsolidation.Status.RELEASED,
            LooseCargoConsolidation.Status.RECEIVING,
            LooseCargoConsolidation.Status.READY_FOR_SHIPMENT,
            LooseCargoConsolidation.Status.TRANSFERRED,
        },
    ).exclude(state=ConsolidationBoxAllocation.State.RELEASED)
    if allocation_id is not None:
        allocation = qs.filter(pk=allocation_id).first()
        if allocation is None:
            from apps.common.exceptions import ScopedResourceNotFound
            raise ScopedResourceNotFound("The assignment is not available for this supplier.")
        if request.method == "GET":
            return success_response(supplier_assignment_dto(allocation))
        require_json(request)
        payload = HandoverSerializer(data=request.data); payload.is_valid(raise_exception=True)
        data = payload.validated_data
        release_event = allocation.consolidation.events.filter(action="release").order_by("-source_version", "-id").first()
        if not release_event or data["release_version"] != release_event.source_version:
            from apps.common.exceptions import StateConflict
            raise StateConflict("The supplied release version is stale.")
        result = submit_consolidation_handover(
            consolidation_id=allocation.consolidation_id, allocation_id=allocation.id,
            actor=request.user, expected_version=data["expected_version"], evidence_ids=data["evidence_ids"],
            idempotency_key=require_key(request), handover_method=data["handover_method"],
            handover_reference=data["handover_reference"], reason=data.get("reason", ""),
            channel=MINIAPP if miniapp else SUPPLIER_WEB,
        )
        obj, event, replayed = result
        response = success_response(allocation_dto(obj, internal=False))
        response["Idempotency-Replayed"] = "true" if replayed else "false"
        return response
    if request.method != "GET":
        raise ValidationError("Only assignment handover actions accept writes.")
    _strict_query(request, {"page", "page_size", "status"})
    if request.query_params.get("status"):
        qs = qs.filter(state=request.query_params["status"])
    return success_response(page_payload(request, qs, supplier_assignment_dto))


@api_view(["GET"])
@supplier_permissions()
def supplier_assignment_collection(request):
    return _supplier_assignments(request, miniapp=False)


@api_view(["GET"])
@supplier_permissions()
def supplier_assignment_detail(request, allocation_id):
    return _supplier_assignments(request, miniapp=False, allocation_id=allocation_id)


@api_view(["POST"])
@supplier_permissions()
def supplier_assignment_handover(request, allocation_id):
    return _supplier_assignments(request, miniapp=False, allocation_id=allocation_id)


@api_view(["GET"])
@supplier_permissions(miniapp=True)
def miniapp_assignment_collection(request):
    return _supplier_assignments(request, miniapp=True)


@api_view(["GET"])
@supplier_permissions(miniapp=True)
def miniapp_assignment_detail(request, allocation_id):
    return _supplier_assignments(request, miniapp=True, allocation_id=allocation_id)


@api_view(["POST"])
@supplier_permissions(miniapp=True)
def miniapp_assignment_handover(request, allocation_id):
    return _supplier_assignments(request, miniapp=True, allocation_id=allocation_id)


def _attachment_queryset(request, attachment_id):
    supplier_id = require_supplier(request.user)
    item = ControlledAttachment.objects.filter(tenant=request.user.tenant, pk=attachment_id, owner_type="supplier", owner_id=supplier_id).first()
    if item is None:
        from apps.common.exceptions import ScopedResourceNotFound
        raise ScopedResourceNotFound("The attachment is not available for this supplier.")
    return item


def _attachment_status(item):
    return {
        "id": item.id, "attachment_no": item.attachment_no, "state": item.state,
        "scan_status": item.scan_status, "file_name": item.file_name,
        "media_type": item.media_type, "byte_size": item.byte_size,
    }


def _upload_response(attachment, event, replayed, session, *, status=201):
    token = getattr(session, "upload_token", None)
    response = success_response({**_attachment_status(attachment), "upload_session_id": session.id if session else None, "upload_token": token}, status=status)
    response["Idempotency-Replayed"] = "true" if replayed else "false"
    return response


@api_view(["POST"])
@supplier_permissions()
def supplier_attachment_upload_session(request, allocation_id):
    assert_channel(request, SUPPLIER_WEB); require_json(request)
    allocation, _ = supplier_allocation(ConsolidationBoxAllocation.objects, request.user, allocation_id)
    key = require_key(request)
    result = create_attachment_upload_session(actor=request.user, allocation_id=allocation.id, idempotency_key=key, channel=SUPPLIER_WEB)
    attachment, event, replayed = result
    session = getattr(attachment, "upload_session", None) or attachment.upload_sessions.order_by("-id").first()
    return _upload_response(attachment, event, replayed, session)


@api_view(["POST"])
@supplier_permissions(miniapp=True)
def miniapp_attachment_upload_session(request, allocation_id):
    assert_channel(request, MINIAPP); require_json(request)
    allocation, _ = supplier_allocation(ConsolidationBoxAllocation.objects, request.user, allocation_id)
    key = require_key(request)
    attachment, event, replayed = create_attachment_upload_session(actor=request.user, allocation_id=allocation.id, idempotency_key=key, channel=MINIAPP)
    session = getattr(attachment, "upload_session", None) or attachment.upload_sessions.order_by("-id").first()
    return _upload_response(attachment, event, replayed, session)


def _finalize_attachment(request, attachment_id, *, miniapp=False):
    assert_channel(request, MINIAPP if miniapp else SUPPLIER_WEB); require_json(request)
    attachment = _attachment_queryset(request, attachment_id)
    payload_fields = {"file_name", "claimed_media_type", "claimed_sha256", "upload_token", "content_base64", "upload_session_id"}
    unknown = set(request.data) - payload_fields
    if unknown:
        raise ValidationError({"unknown_fields": sorted(unknown)})
    content = None
    if request.data.get("content_base64") is not None:
        if not getattr(settings, "SUPPLY_FLOW_LOCAL_UPLOAD_ENABLED", False):
            raise ValidationError({"content_base64": "Binary HTTP upload is disabled outside the local test switch."})
        try:
            content = base64.b64decode(request.data["content_base64"], validate=True)
        except Exception as exc:
            raise ValidationError({"content_base64": "A valid base64 payload is required."}) from exc
    finalized, event, replayed = finalize_attachment(
        actor=request.user, attachment_id=attachment.id, upload_session_id=request.data.get("upload_session_id"),
        idempotency_key=require_key(request), file_name=request.data.get("file_name"),
        claimed_media_type=request.data.get("claimed_media_type"), claimed_sha256=request.data.get("claimed_sha256"),
        content=content, upload_token=request.data.get("upload_token"),
    )
    response = success_response(_attachment_status(finalized))
    response["Idempotency-Replayed"] = "true" if replayed else "false"
    return response


@api_view(["POST"])
@supplier_permissions()
def supplier_attachment_finalize(request, attachment_id):
    return _finalize_attachment(request, attachment_id, miniapp=False)


@api_view(["POST"])
@supplier_permissions(miniapp=True)
def miniapp_attachment_finalize(request, attachment_id):
    return _finalize_attachment(request, attachment_id, miniapp=True)


def _attachment_read(request, attachment_id, *, miniapp=False, ticket=False):
    assert_channel(request, MINIAPP if miniapp else SUPPLIER_WEB)
    if ticket:
        # A real short-lived, auditable download-ticket adapter is not part of
        # this local wave.  Never emit a predictable value or a hash-bearing
        # URL; fail closed for every caller/resource alike.
        raise ContractViolation(
            "Download tickets are disabled until the signed storage adapter is enabled.",
            error_code="FEATURE_UNAVAILABLE",
            status_code=503,
        )
    item = _attachment_queryset(request, attachment_id)
    return success_response({"attachment": _attachment_status(item)})


@api_view(["GET"])
@supplier_permissions()
def supplier_attachment_status(request, attachment_id):
    return _attachment_read(request, attachment_id, miniapp=False)


@api_view(["GET"])
@supplier_permissions(miniapp=True)
def miniapp_attachment_status(request, attachment_id):
    return _attachment_read(request, attachment_id, miniapp=True)


@api_view(["GET"])
@supplier_permissions()
def supplier_attachment_download_ticket(request, attachment_id):
    return _attachment_read(request, attachment_id, miniapp=False, ticket=True)


@api_view(["GET"])
@supplier_permissions(miniapp=True)
def miniapp_attachment_download_ticket(request, attachment_id):
    return _attachment_read(request, attachment_id, miniapp=True, ticket=True)
