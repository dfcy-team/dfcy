from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes

from apps.common.responses import success_response
from apps.permissions.api_permissions import IsInternalUser

from .models import PurchaseOrder
from .serializers import PurchaseOrderSerializer


@api_view(["GET", "POST"])
@permission_classes([IsInternalUser])
def purchase_order_collection(request):
    if request.method == "GET":
        queryset = PurchaseOrder.objects.filter(tenant=request.user.tenant)
        return success_response(PurchaseOrderSerializer(queryset, many=True).data)

    serializer = PurchaseOrderSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    order = serializer.save(tenant=request.user.tenant, created_by=request.user)
    return success_response(PurchaseOrderSerializer(order).data, status=201)


@api_view(["GET", "PATCH"])
@permission_classes([IsInternalUser])
def purchase_order_detail(request, pk):
    order = get_object_or_404(PurchaseOrder, pk=pk, tenant=request.user.tenant)
    if request.method == "GET":
        return success_response(PurchaseOrderSerializer(order).data)

    serializer = PurchaseOrderSerializer(order, data=request.data, partial=True, context={"request": request})
    serializer.is_valid(raise_exception=True)
    order = serializer.save()
    return success_response(PurchaseOrderSerializer(order).data)
