import hashlib
import json

from django.db import IntegrityError, transaction
from django.db.models import Q
from rest_framework.exceptions import ValidationError
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

from apps.accounts.miniapp_permissions import IsMiniAppToken
from apps.audit.services import write_operation_log
from apps.common.exceptions import ScopedResourceNotFound, StateConflict
from apps.common.query import pagination_query
from apps.common.responses import paginated_data, success_response

from .models import SupplyPurchaseOrder, SupplyPurchaseOrderEvent
from .supply_permissions import (
    IsNonMiniAppChannel,
    authorize_internal_supplier,
    filter_internal_supply_orders,
    filter_supplier_supply_orders,
    require_internal_supply_permission,
    supplier_id_for_user,
)
from .supply_serializers import (
    EmptySupplyOrderActionSerializer,
    SupplierSupplyPurchaseOrderSerializer,
    SupplyOrderProgressActionSerializer,
    SupplyPurchaseOrderCreateSerializer,
    SupplyPurchaseOrderDetailSerializer,
    SupplyPurchaseOrderSummarySerializer,
)
from .supply_services import perform_supply_order_action


INTERNAL_ACTION_PERMISSIONS = {
    SupplyPurchaseOrderEvent.Action.ACCEPT: "supply.purchase_order.accept",
    SupplyPurchaseOrderEvent.Action.START_PRODUCTION: "supply.production.start",
    SupplyPurchaseOrderEvent.Action.UPDATE_PROGRESS: "supply.production.update",
    SupplyPurchaseOrderEvent.Action.COMPLETE_PRODUCTION: "supply.production.complete",
}

URL_ACTIONS = {
    "accept": SupplyPurchaseOrderEvent.Action.ACCEPT,
    "start-production": SupplyPurchaseOrderEvent.Action.START_PRODUCTION,
    "update-progress": SupplyPurchaseOrderEvent.Action.UPDATE_PROGRESS,
    "complete-production": SupplyPurchaseOrderEvent.Action.COMPLETE_PRODUCTION,
}


def _order_queryset():
    return (
        SupplyPurchaseOrder.objects.select_related("tenant", "supplier", "created_by")
        .prefetch_related(
            "lines",
            "lines__sku",
            "progress_entries",
            "events",
        )
    )


def _filtered_queryset(request, queryset):
    search = request.query_params.get("search", "").strip()
    status = request.query_params.get("status", "").strip()
    supplier_id = request.query_params.get("supplier_id", "").strip()
    if search:
        queryset = queryset.filter(
            Q(order_no__icontains=search)
            | Q(supplier__code__icontains=search)
            | Q(supplier__name__icontains=search)
            | Q(lines__sku_code_snapshot__icontains=search)
        ).distinct()
    if status:
        queryset = queryset.filter(status=status)
    if supplier_id.isdigit():
        queryset = queryset.filter(supplier_id=int(supplier_id))
    return queryset


def _idempotency_key(request):
    return request.META.get("HTTP_IDEMPOTENCY_KEY", "").strip()


def _request_hash(data):
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _action_payload(request, action):
    serializer_class = (
        SupplyOrderProgressActionSerializer
        if action == SupplyPurchaseOrderEvent.Action.UPDATE_PROGRESS
        else EmptySupplyOrderActionSerializer
    )
    serializer = serializer_class(data=request.data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def _creation_replay(user, idempotency_key, request_hash):
    replay = _order_queryset().filter(
        tenant=user.tenant,
        creation_idempotency_key=idempotency_key,
    ).first()
    if replay and replay.creation_request_hash != request_hash:
        raise StateConflict("The idempotency key was already used with a different create payload.")
    return replay


def _action_response(order_id, event, replayed, *, supplier=False):
    snapshot = event.response_snapshot
    if not snapshot:
        order = _order_queryset().get(pk=order_id)
        serializer_class = SupplierSupplyPurchaseOrderSerializer if supplier else SupplyPurchaseOrderDetailSerializer
        snapshot = serializer_class(order).data
    return success_response(
        {
            "replayed": replayed,
            "order": snapshot,
        }
    )


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated, IsNonMiniAppChannel])
def internal_supply_order_collection(request):
    if request.method == "GET":
        permission_code = "supply.purchase_order.view"
        require_internal_supply_permission(request.user, permission_code)
        queryset = filter_internal_supply_orders(
            request.user,
            _order_queryset(),
            permission_code,
        )
        queryset = _filtered_queryset(request, queryset)
        page, page_size = pagination_query(request)
        return success_response(
            paginated_data(
                request,
                queryset,
                SupplyPurchaseOrderSummarySerializer,
                page=page,
                page_size=page_size,
            )
        )

    permission_code = "supply.purchase_order.create"
    require_internal_supply_permission(request.user, permission_code)
    idempotency_key = _idempotency_key(request)
    if not idempotency_key or len(idempotency_key) > 128:
        raise ValidationError({"idempotency_key": "A valid Idempotency-Key header is required."})
    request_hash = _request_hash(request.data)
    replay = _creation_replay(request.user, idempotency_key, request_hash)
    if replay:
        return success_response(SupplyPurchaseOrderDetailSerializer(replay).data)

    serializer = SupplyPurchaseOrderCreateSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    authorize_internal_supplier(
        request.user,
        permission_code,
        serializer.validated_data["supplier_id"],
    )
    try:
        with transaction.atomic():
            order = serializer.save(
                creation_idempotency_key=idempotency_key,
                creation_request_hash=request_hash,
            )
            write_operation_log(
                tenant=order.tenant,
                user=request.user,
                module="supply_chain",
                action="purchase_order.create",
                object_type="SupplyPurchaseOrder",
                object_id=order.id,
                after_data={
                    "order_no": order.order_no,
                    "supplier_id": order.supplier_id,
                    "status": order.status,
                    "line_count": order.lines.count(),
                    "idempotency_key": idempotency_key,
                },
                ip_address=request.META.get("REMOTE_ADDR") or None,
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:1000],
            )
    except IntegrityError:
        replay = _creation_replay(request.user, idempotency_key, request_hash)
        if replay:
            return success_response(SupplyPurchaseOrderDetailSerializer(replay).data)
        if SupplyPurchaseOrder.objects.filter(
            tenant=request.user.tenant,
            order_no=serializer.validated_data["order_no"],
        ).exists():
            raise StateConflict("A supply purchase order with this number already exists in the tenant.")
        raise
    order = _order_queryset().get(pk=order.pk)
    return success_response(SupplyPurchaseOrderDetailSerializer(order).data, status=201)


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsNonMiniAppChannel])
def internal_supply_order_detail(request, pk):
    permission_code = "supply.purchase_order.view"
    require_internal_supply_permission(request.user, permission_code)
    order = filter_internal_supply_orders(
        request.user,
        _order_queryset(),
        permission_code,
    ).filter(pk=pk).first()
    if order is None:
        raise ScopedResourceNotFound("Supply purchase order is not available in the authorized scope.")
    return success_response(SupplyPurchaseOrderDetailSerializer(order).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsNonMiniAppChannel])
def internal_supply_order_action(request, pk, action_name):
    action = URL_ACTIONS.get(action_name)
    if action is None:
        raise ScopedResourceNotFound("Supply purchase order action does not exist.")
    permission_code = INTERNAL_ACTION_PERMISSIONS[action]
    require_internal_supply_permission(request.user, permission_code)
    authorized = filter_internal_supply_orders(
        request.user,
        SupplyPurchaseOrder.objects.all(),
        permission_code,
    ).filter(pk=pk).exists()
    if not authorized:
        raise ScopedResourceNotFound("Supply purchase order is not available in the authorized scope.")
    payload = _action_payload(request, action)
    order, event, replayed = perform_supply_order_action(
        order_id=pk,
        actor=request.user,
        action=action,
        idempotency_key=_idempotency_key(request),
        request=request,
        **payload,
    )
    return _action_response(order.id, event, replayed)


def _supplier_collection(request):
    queryset = filter_supplier_supply_orders(request.user, _order_queryset())
    queryset = _filtered_queryset(request, queryset)
    page, page_size = pagination_query(request)
    return success_response(
        paginated_data(
            request,
            queryset,
            SupplierSupplyPurchaseOrderSerializer,
            page=page,
            page_size=page_size,
        )
    )


def _supplier_detail(request, pk):
    order = filter_supplier_supply_orders(
        request.user,
        _order_queryset(),
    ).filter(pk=pk).first()
    if order is None:
        raise ScopedResourceNotFound("Supply purchase order is not available in the authorized scope.")
    return success_response(SupplierSupplyPurchaseOrderSerializer(order).data)


def _supplier_action(request, pk, action_name):
    action = URL_ACTIONS.get(action_name)
    if action is None:
        raise ScopedResourceNotFound("Supply purchase order action does not exist.")
    payload = _action_payload(request, action)
    order, event, replayed = perform_supply_order_action(
        order_id=pk,
        actor=request.user,
        supplier_id=supplier_id_for_user(request.user),
        action=action,
        idempotency_key=_idempotency_key(request),
        request=request,
        **payload,
    )
    return _action_response(order.id, event, replayed, supplier=True)


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsNonMiniAppChannel])
def supplier_supply_order_collection(request):
    return _supplier_collection(request)


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsNonMiniAppChannel])
def supplier_supply_order_detail(request, pk):
    return _supplier_detail(request, pk)


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsNonMiniAppChannel])
def supplier_supply_order_action(request, pk, action_name):
    return _supplier_action(request, pk, action_name)


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsMiniAppToken])
def miniapp_supply_order_collection(request):
    return _supplier_collection(request)


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsMiniAppToken])
def miniapp_supply_order_detail(request, pk):
    return _supplier_detail(request, pk)


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsMiniAppToken])
def miniapp_supply_order_action(request, pk, action_name):
    return _supplier_action(request, pk, action_name)
