from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied

from apps.common.responses import success_response
from apps.permissions.api_permissions import IsExternalUser

from .models import SupplierShipment, SupplierTask
from .serializers import SupplierShipmentSerializer, SupplierTaskFeedbackSerializer, SupplierTaskSerializer


def _supplier_id_for_user(request):
    profile = getattr(request.user, "external_profile", None)
    supplier_id = getattr(profile, "supplier_id", None)
    if supplier_id is None:
        raise PermissionDenied("Supplier identity is required.")
    return supplier_id


@api_view(["GET"])
@permission_classes([IsExternalUser])
def supplier_task_collection(request):
    supplier_id = _supplier_id_for_user(request)
    queryset = SupplierTask.objects.filter(tenant=request.user.tenant, supplier_id=supplier_id)
    return success_response(SupplierTaskSerializer(queryset, many=True).data)


@api_view(["GET"])
@permission_classes([IsExternalUser])
def supplier_task_detail(request, pk):
    supplier_id = _supplier_id_for_user(request)
    task = get_object_or_404(SupplierTask, pk=pk, tenant=request.user.tenant, supplier_id=supplier_id)
    return success_response(SupplierTaskSerializer(task).data)


@api_view(["PATCH"])
@permission_classes([IsExternalUser])
def supplier_task_feedback(request, pk):
    supplier_id = _supplier_id_for_user(request)
    task = get_object_or_404(SupplierTask, pk=pk, tenant=request.user.tenant, supplier_id=supplier_id)
    serializer = SupplierTaskFeedbackSerializer(task, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    task = serializer.save()
    return success_response(SupplierTaskSerializer(task).data)


@api_view(["GET", "POST"])
@permission_classes([IsExternalUser])
def supplier_shipment_collection(request):
    supplier_id = _supplier_id_for_user(request)
    if request.method == "GET":
        queryset = SupplierShipment.objects.filter(tenant=request.user.tenant, supplier_id=supplier_id)
        return success_response(SupplierShipmentSerializer(queryset, many=True).data)

    serializer = SupplierShipmentSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    shipment = serializer.save(tenant=request.user.tenant, supplier_id=supplier_id)
    return success_response(SupplierShipmentSerializer(shipment).data, status=201)


@api_view(["GET"])
@permission_classes([IsExternalUser])
def supplier_shipment_detail(request, pk):
    supplier_id = _supplier_id_for_user(request)
    shipment = get_object_or_404(SupplierShipment, pk=pk, tenant=request.user.tenant, supplier_id=supplier_id)
    return success_response(SupplierShipmentSerializer(shipment).data)
