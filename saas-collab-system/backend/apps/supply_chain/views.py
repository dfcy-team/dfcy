from decimal import Decimal

from django.db.models import Exists, OuterRef
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.purchasing.supply_permissions import IsNonMiniAppChannel
from apps.permissions.api_permissions import DeclaredApplicationPermission
from .contracts import CONTRACT
from .models import DispatchBatch, DispatchMembership, InboundOrder, PurchaseOrder, SupplierShipment
from .permissions import MANAGE, VIEW, internal_orders, supplier_orders
from .services import purchase_snapshot


def _page(request, queryset, serialize):
    try:
        limit, offset = int(request.query_params.get("limit", 50)), int(request.query_params.get("offset", 0))
    except (ValueError, TypeError):
        raise ValidationError("Invalid pagination.")
    if not 1 <= limit <= 100 or offset < 0:
        raise ValidationError("Limit must be 1–100 and offset must be nonnegative.")
    return Response({"data": [serialize(obj) for obj in queryset.order_by("-id")[offset:offset + limit]], "count": queryset.count(), "limit": limit, "offset": offset})


def purchase_data(order):
    return purchase_snapshot(order)


def shipment_data(shipment):
    member = next((m for m in shipment.dispatch_memberships.all() if m.active_guard), None)
    batch = member.batch if member else None
    return {
        "id": shipment.pk, "number": shipment.number, "order_id": shipment.order_id,
        "country_code": shipment.order.country_code_snapshot, "entry_mode": shipment.entry_mode,
        "status": shipment.status,
        "collection_arrived": shipment.collection_arrived, "version": shipment.version,
        # A derived projection; there is no independently editable shipment stage.
        "logistics_stage": batch.stage if batch else "unmarked",
        "logistics_dates": {key: getattr(batch, key) if batch else None for key in ("departed_at", "arrived_port_at", "arrived_warehouse_at")},
        "lines": [{"id": line.pk, "sku_id": line.sku_id, "sku": line.sku_code_snapshot, "quantity": line.quantity, "purchase_line_id": line.purchase_line_id, "exception_type": line.exception_type, "excess_quantity": line.excess_quantity} for line in shipment.lines.all()],
    }


def visible_batches(user):
    orders = internal_orders(user, PurchaseOrder.objects.all())
    denied_members = DispatchMembership.objects.filter(batch_id=OuterRef("pk")).exclude(shipment__order__in=orders)
    return DispatchBatch.objects.filter(tenant_id=user.tenant_id).annotate(has_denied_member=Exists(denied_members)).filter(has_denied_member=False)


class ReadAPI(APIView):
    permission_classes = [IsAuthenticated, IsNonMiniAppChannel]

    def finalize_response(self, request, response, *args, **kwargs):
        if isinstance(response, Response) and response.status_code < 400 and isinstance(response.data, dict) and "data" in response.data:
            response.data = {"success": True, "code": "OK", "message": "success", **response.data}
        return super().finalize_response(request, response, *args, **kwargs)


class InternalAPI(ReadAPI):
    permission_classes = [IsAuthenticated, IsNonMiniAppChannel, DeclaredApplicationPermission]
    read_permission_code = VIEW
    write_permission_code = MANAGE


class ContractAPI(InternalAPI):
    def get(self, request):
        internal_orders(request.user, PurchaseOrder.objects.all())
        return Response({"data": CONTRACT})


class InternalPurchases(InternalAPI):
    def get(self, request):
        from .api import purchase_queryset
        return _page(request, purchase_queryset(request), purchase_data)

    def post(self, request):
        from .api import create_purchase_response
        return create_purchase_response(request)


class SupplierPurchases(ReadAPI):
    def get(self, request):
        return _page(request, supplier_orders(request.user, PurchaseOrder.objects.all()).prefetch_related("lines"), purchase_data)


class Shipments(InternalAPI):
    supplier = False

    def get(self, request):
        orders = (supplier_orders if self.supplier else internal_orders)(request.user, PurchaseOrder.objects.all())
        queryset = SupplierShipment.objects.filter(tenant_id=request.user.tenant_id, order__in=orders).select_related("order").prefetch_related("lines", "dispatch_memberships__batch")
        return _page(request, queryset, shipment_data)


class SupplierShipments(Shipments):
    supplier = True
    permission_classes = ReadAPI.permission_classes


class Dispatches(InternalAPI):
    def get(self, request):
        return _page(request, visible_batches(request.user).prefetch_related("memberships"), lambda batch: {
            "id": batch.pk, "number": batch.number, "country_code": batch.country_code_snapshot,
            "stage": batch.stage, "version": batch.version, "freight_company_id": batch.freight_company_id,
            "freight_number": batch.freight_number,
            "shipment_ids": [m.shipment_id for m in batch.memberships.all() if m.active_guard],
        })


class Inbounds(InternalAPI):
    def get(self, request):
        queryset = InboundOrder.objects.filter(tenant_id=request.user.tenant_id, batch__in=visible_batches(request.user)).prefetch_related("lines")
        return _page(request, queryset, lambda inbound: {
            "id": inbound.pk, "number": inbound.number, "batch_id": inbound.batch_id,
            "warehouse_id": inbound.warehouse_id, "status": inbound.status, "version": inbound.version,
            "lines": [{"shipment_line_id": line.shipment_line_id, "expected_quantity": line.expected_quantity, "received_quantity": line.received_quantity} for line in inbound.lines.all()],
        })
