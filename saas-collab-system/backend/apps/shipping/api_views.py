"""Internal HTTP adapters for typed loose-cargo shipments."""

from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError

from apps.common.responses import success_response

from apps.consolidation.api_support import (
    INTERNAL,
    authorized_shipment,
    authorize_consolidation_allocations_for_scope,
    assert_channel,
    event_result,
    internal_permissions,
    page_payload,
    require_internal,
    require_json,
    require_key,
)

from .api_serializers import (
    ShipmentActionSerializer,
    CustomsActionSerializer,
    DispatchActionSerializer,
    SimpleActionSerializer,
    ShipmentBoxesSerializer,
    ShipmentCreateSerializer,
    ShipmentUpdateSerializer,
    shipment_dto,
)
from .models import LooseCargoShipment
from .services import (
    allocate_shipment_boxes,
    cancel_shipment,
    clear_shipment,
    customs_declare_shipment,
    dispatch_shipment,
    mark_shipment_exception,
    port_arrival_shipment,
    warehouse_arrival_shipment,
    create_shipment,
    update_shipment,
)


def _strict_query(request, allowed=()):
    unknown = set(request.query_params) - set(allowed)
    if unknown:
        raise ValidationError({"unknown_query": f"Unknown query parameters: {sorted(unknown)}"})


def _resource(result, transform, status=200):
    obj, event, replayed = result
    response = success_response(transform(obj), status=status)
    response["Idempotency-Replayed"] = "true" if replayed else "false"
    return response


def _queryset():
    return LooseCargoShipment.objects.prefetch_related("box_allocations__consolidation")


@api_view(["GET", "POST"])
@internal_permissions()
def internal_shipment_collection(request):
    assert_channel(request, INTERNAL)
    if request.method == "GET":
        _strict_query(request, {"page", "page_size", "status", "region_code", "route_type"})
        items, _ = authorized_shipment(_queryset().order_by("-created_at"), request.user, "supply.shipment.view")
        if request.query_params.get("status"):
            items = [item for item in items if item.status == request.query_params["status"]]
        if request.query_params.get("region_code"):
            items = [item for item in items if item.region_code == request.query_params["region_code"]]
        if request.query_params.get("route_type"):
            items = [item for item in items if item.route_type == request.query_params["route_type"]]
        return success_response(page_payload(request, items, lambda item: shipment_dto(item, internal=True)))
    require_json(request)
    scopes = require_internal(request.user, "supply.shipment.create")
    payload = ShipmentCreateSerializer(data=request.data); payload.is_valid(raise_exception=True)
    data = payload.validated_data
    if not any(scope["scope_type"] == "all" for scope in scopes):
        origin_site = data.get("origin_site_id")
        if not origin_site or not any(origin_site in scope["config"]["consolidation_site_ids"] for scope in scopes):
            from apps.common.exceptions import DataScopeDenied
            raise DataScopeDenied("A CUSTOM shipment create requires a declared origin site.", error_code="DATA_SCOPE_FORBIDDEN")
    result = create_shipment(actor=request.user, idempotency_key=require_key(request), **data)
    return _resource(result, lambda item: shipment_dto(item, internal=True), status=201)


@api_view(["GET", "PUT"])
@internal_permissions()
def internal_shipment_detail(request, pk):
    assert_channel(request, INTERNAL)
    if request.method == "GET":
        item, _ = authorized_shipment(_queryset(), request.user, "supply.shipment.view", pk=pk)
        return success_response(shipment_dto(item, internal=True))
    require_json(request)
    item, _ = authorized_shipment(_queryset(), request.user, "supply.shipment.update", pk=pk)
    payload = ShipmentUpdateSerializer(data=request.data); payload.is_valid(raise_exception=True)
    data = dict(payload.validated_data)
    expected = data.pop("expected_version"); reason = data.pop("reason", "")
    result = update_shipment(shipment_id=item.id, actor=request.user, expected_version=expected, idempotency_key=require_key(request), updates=data, reason=reason)
    return _resource(result, lambda obj: shipment_dto(obj, internal=True))


@api_view(["POST"])
@internal_permissions()
def internal_shipment_boxes(request, pk):
    assert_channel(request, INTERNAL); require_json(request)
    item, scopes = authorized_shipment(_queryset(), request.user, "supply.shipment.allocate", pk=pk)
    payload = ShipmentBoxesSerializer(data=request.data); payload.is_valid(raise_exception=True)
    data = payload.validated_data
    allocations = authorize_consolidation_allocations_for_scope(request.user, scopes, allocation_ids=data["allocation_ids"], shipment_id=item.id)
    if any(int(allocation.consolidation_id) != int(data["consolidation_id"]) for allocation in allocations):
        from apps.common.exceptions import ScopedResourceNotFound
        raise ScopedResourceNotFound("One or more consolidation allocations are not in the requested source.")
    result = allocate_shipment_boxes(shipment_id=item.id, actor=request.user, expected_version=data["expected_version"], idempotency_key=require_key(request), consolidation_id=data["consolidation_id"], allocation_ids=data["allocation_ids"], reason=data.get("reason", ""))
    return _resource(result, lambda obj: shipment_dto(obj, internal=True))


def _shipment_action(request, pk, permission, service, *, fields=None, serializer_class=SimpleActionSerializer):
    assert_channel(request, INTERNAL); require_json(request)
    item, _ = authorized_shipment(_queryset(), request.user, permission, pk=pk)
    payload = serializer_class(data=request.data); payload.is_valid(raise_exception=True)
    data = dict(payload.validated_data)
    expected = data.pop("expected_version"); key = require_key(request)
    kwargs = {"shipment_id": item.id, "actor": request.user, "expected_version": expected, "idempotency_key": key,
              "reason": data.pop("reason", "")}
    if fields:
        kwargs.update(fields(data))
    result = service(**kwargs)
    return _resource(result, lambda obj: shipment_dto(obj, internal=True))


@api_view(["POST"])
@internal_permissions()
def internal_shipment_customs(request, pk):
    return _shipment_action(request, pk, "supply.shipment.customs.confirm", customs_declare_shipment, fields=lambda d: {"customs_reference": d.get("customs_reference", "")}, serializer_class=CustomsActionSerializer)


@api_view(["POST"])
@internal_permissions()
def internal_shipment_dispatch(request, pk):
    return _shipment_action(request, pk, "supply.shipment.dispatch", dispatch_shipment, fields=lambda d: {"allocation_ids": d.get("allocation_ids")}, serializer_class=DispatchActionSerializer)


@api_view(["POST"])
@internal_permissions()
def internal_shipment_port_arrival(request, pk):
    return _shipment_action(request, pk, "supply.shipment.port_arrival.confirm", port_arrival_shipment)


@api_view(["POST"])
@internal_permissions()
def internal_shipment_warehouse_arrival(request, pk):
    return _shipment_action(request, pk, "supply.shipment.warehouse_arrival.confirm", warehouse_arrival_shipment)


@api_view(["POST"])
@internal_permissions()
def internal_shipment_clearance(request, pk):
    return _shipment_action(request, pk, "supply.shipment.clearance.complete", clear_shipment)


@api_view(["POST"])
@internal_permissions()
def internal_shipment_exception(request, pk):
    return _shipment_action(request, pk, "supply.shipment.exception.manage", mark_shipment_exception)


@api_view(["POST"])
@internal_permissions()
def internal_shipment_cancel(request, pk):
    return _shipment_action(request, pk, "supply.shipment.cancel", cancel_shipment)
