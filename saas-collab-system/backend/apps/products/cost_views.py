from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_datetime
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.common.responses import success_response

from .cost_services import append_cost_version, effective_cost_for, preview_system_backfill
from .models import ProductCostVersion, ProductSKU
from .permissions import IsProductCostApprover, IsProductCostBackfillOperator, IsProductCostManager, IsProductCostViewer
from .serializers import ProductCostVersionSerializer


@api_view(["GET"])
@permission_classes([IsProductCostViewer])
def product_cost_collection(request):
    queryset = ProductCostVersion.objects.filter(tenant=request.user.tenant).select_related("sku", "created_by")
    sku_id = request.query_params.get("sku_id")
    if sku_id:
        queryset = queryset.filter(sku_id=sku_id)
    occurred_at = request.query_params.get("occurred_at")
    if occurred_at and sku_id:
        parsed = parse_datetime(occurred_at)
        if parsed is None:
            raise ValidationError({"occurred_at": "Use an ISO-8601 datetime."})
        sku = get_object_or_404(ProductSKU, tenant=request.user.tenant, pk=sku_id)
        item = effective_cost_for(tenant=request.user.tenant, sku=sku, occurred_at=parsed)
        return success_response(ProductCostVersionSerializer(item).data if item else None)
    return success_response(ProductCostVersionSerializer(queryset, many=True).data)


@api_view(["POST"])
@permission_classes([IsProductCostManager])
def product_cost_create(request):
    serializer = ProductCostVersionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    if serializer.validated_data.get("status", ProductCostVersion.Status.PENDING) == ProductCostVersion.Status.CONFIRMED:
        if not IsProductCostApprover().has_permission(request, None):
            raise PermissionDenied("products.cost.approve permission is required to confirm a version.")
    sku = get_object_or_404(ProductSKU, tenant=request.user.tenant, pk=serializer.validated_data.pop("sku").pk)
    try:
        item = append_cost_version(
            tenant=request.user.tenant, sku=sku, actor=request.user, **serializer.validated_data
        )
    except DjangoValidationError as exc:
        raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages) from exc
    return success_response(ProductCostVersionSerializer(item).data, status=201)


@api_view(["POST"])
@permission_classes([IsProductCostBackfillOperator])
def product_cost_backfill_preview(request):
    sku_ids = request.data.get("sku_ids") or []
    if not isinstance(sku_ids, list):
        raise ValidationError({"sku_ids": "Must be a list."})
    return success_response({"dry_run": True, "results": preview_system_backfill(tenant=request.user.tenant, sku_ids=sku_ids)})
