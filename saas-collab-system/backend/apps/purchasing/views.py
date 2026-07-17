from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes

from apps.common.query import pagination_query
from apps.common.responses import paginated_data, success_response
from apps.permissions.ui_p5_scopes import filter_purchase_orders, require_create_scope

from .models import PurchaseOrder
from .permissions import IsPurchaseOrderReadOrManage
from .serializers import PurchaseOrderSerializer


@api_view(["GET", "POST"])
@permission_classes([IsPurchaseOrderReadOrManage])
def purchase_order_collection(request):
    if request.method == "GET":
        queryset = PurchaseOrder.objects.filter(tenant=request.user.tenant)
        queryset = filter_purchase_orders(request.user, queryset, "purchasing.orders.view")
        search = request.query_params.get("search", "").strip()
        status = request.query_params.get("status", "").strip()
        if search:
            queryset = queryset.filter(po_no__icontains=search)
        if status:
            queryset = queryset.filter(status=status)
        page, page_size = pagination_query(request)
        return success_response(
            paginated_data(request, queryset, PurchaseOrderSerializer, page=page, page_size=page_size)
        )

    require_create_scope(request.user, "purchasing.orders.manage", allow_own=True)
    serializer = PurchaseOrderSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    order = serializer.save(tenant=request.user.tenant, created_by=request.user)
    return success_response(PurchaseOrderSerializer(order).data, status=201)


@api_view(["GET", "PATCH"])
@permission_classes([IsPurchaseOrderReadOrManage])
def purchase_order_detail(request, pk):
    permission_code = "purchasing.orders.view" if request.method == "GET" else "purchasing.orders.manage"
    queryset = PurchaseOrder.objects.filter(tenant=request.user.tenant)
    order = get_object_or_404(filter_purchase_orders(request.user, queryset, permission_code), pk=pk)
    if request.method == "GET":
        return success_response(PurchaseOrderSerializer(order).data)

    serializer = PurchaseOrderSerializer(order, data=request.data, partial=True, context={"request": request})
    serializer.is_valid(raise_exception=True)
    order = serializer.save()
    return success_response(PurchaseOrderSerializer(order).data)
