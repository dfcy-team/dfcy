from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied

from apps.common.query import pagination_query
from apps.common.responses import paginated_data, success_response
from apps.permissions.api_permissions import IsExternalUser

from .models import SupplierPerformanceSnapshot, SupplierShipment, SupplierTask
from .performance_services import calculate_supplier_performance
from .permissions import (
    IsSupplierPerformanceCalculator,
    IsSupplierPerformanceViewer,
    can_access_supplier_performance,
    get_supplier_performance_scope,
)
from .serializers import (
    SupplierPerformanceCalculationSerializer,
    SupplierPerformanceSnapshotSerializer,
    SupplierShipmentSerializer,
    SupplierTaskFeedbackSerializer,
    SupplierTaskSerializer,
)


def _supplier_id_for_user(request):
    profile = getattr(request.user, "external_profile", None)
    supplier_id = getattr(profile, "supplier_id", None)
    if supplier_id is None:
        raise PermissionDenied("Supplier identity is required.")
    requested_supplier_id = request.query_params.get("supplier_id")
    if requested_supplier_id is not None and requested_supplier_id != str(supplier_id):
        raise PermissionDenied("Suppliers can only access their own performance data.")
    return supplier_id


@api_view(["GET"])
@permission_classes([IsExternalUser])
def supplier_task_collection(request):
    supplier_id = _supplier_id_for_user(request)
    queryset = SupplierTask.objects.filter(tenant=request.user.tenant, supplier_id=supplier_id)
    status = request.query_params.get("status", "").strip()
    if status:
        queryset = queryset.filter(status=status)
    page, page_size = pagination_query(request)
    return success_response(paginated_data(request, queryset, SupplierTaskSerializer, page=page, page_size=page_size))


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
        status = request.query_params.get("status", "").strip()
        if status:
            queryset = queryset.filter(status=status)
        page, page_size = pagination_query(request)
        return success_response(
            paginated_data(request, queryset, SupplierShipmentSerializer, page=page, page_size=page_size)
        )

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


@api_view(["GET"])
@permission_classes([IsSupplierPerformanceViewer])
def internal_performance_collection(request):
    queryset = SupplierPerformanceSnapshot.objects.filter(tenant=request.user.tenant)
    allowed_supplier_ids = get_supplier_performance_scope(request.user)
    if allowed_supplier_ids is not None:
        queryset = queryset.filter(supplier_id__in=allowed_supplier_ids)
    return success_response(SupplierPerformanceSnapshotSerializer(queryset, many=True).data)


@api_view(["GET"])
@permission_classes([IsSupplierPerformanceViewer])
def internal_performance_detail(request, supplier_id):
    if not can_access_supplier_performance(request.user, supplier_id):
        raise PermissionDenied("Supplier performance is outside the authorized data scope.")
    queryset = SupplierPerformanceSnapshot.objects.filter(
        tenant=request.user.tenant,
        supplier_id=supplier_id,
    )
    return success_response(SupplierPerformanceSnapshotSerializer(queryset, many=True).data)


@api_view(["POST"])
@permission_classes([IsSupplierPerformanceCalculator])
def internal_performance_calculate_mock(request):
    serializer = SupplierPerformanceCalculationSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    if not can_access_supplier_performance(request.user, serializer.validated_data["supplier_id"]):
        raise PermissionDenied("Supplier performance is outside the authorized data scope.")
    snapshot = calculate_supplier_performance(
        tenant=request.user.tenant,
        **serializer.validated_data,
    )
    return success_response(SupplierPerformanceSnapshotSerializer(snapshot).data)


@api_view(["GET"])
@permission_classes([IsExternalUser])
def external_supplier_performance(request):
    supplier_id = _supplier_id_for_user(request)
    snapshot = SupplierPerformanceSnapshot.objects.filter(
        tenant=request.user.tenant,
        supplier_id=supplier_id,
    ).first()
    data = SupplierPerformanceSnapshotSerializer(snapshot).data if snapshot else {}
    return success_response(data)


@api_view(["GET"])
@permission_classes([IsExternalUser])
def external_supplier_performance_history(request):
    supplier_id = _supplier_id_for_user(request)
    queryset = SupplierPerformanceSnapshot.objects.filter(
        tenant=request.user.tenant,
        supplier_id=supplier_id,
    )
    return success_response(SupplierPerformanceSnapshotSerializer(queryset, many=True).data)
