from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_datetime
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.common.responses import success_response

from .cost_services import (
    append_cost_version,
    confirm_pending_cost_version,
    effective_cost_for,
    execute_system_backfill,
    preview_system_backfill,
)
from .cost_import_services import confirm_cost_import, preview_cost_import
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


@api_view(["POST"])
@permission_classes([IsProductCostBackfillOperator])
def product_cost_backfill_execute(request):
    sku_ids = request.data.get("sku_ids") or []
    if not isinstance(sku_ids, list):
        raise ValidationError({"sku_ids": "Must be a list."})
    effective_from = parse_datetime(str(request.data.get("effective_from") or ""))
    if effective_from is None:
        raise ValidationError({"effective_from": "Use an ISO-8601 datetime."})
    return success_response(execute_system_backfill(
        tenant=request.user.tenant,
        actor=request.user,
        effective_from=effective_from,
        sku_ids=sku_ids,
        reason=str(request.data.get("reason") or "System cost backfill"),
    ), status=201)


@api_view(["POST"])
@permission_classes([IsProductCostApprover])
def product_cost_confirm(request, pk):
    try:
        item = confirm_pending_cost_version(
            tenant=request.user.tenant,
            version_id=pk,
            actor=request.user,
            confirmed_cost=request.data.get("confirmed_cost"),
            reason=str(request.data.get("reason") or ""),
        )
    except ProductCostVersion.DoesNotExist as exc:
        raise ValidationError({"id": "Pending cost version was not found."}) from exc
    except DjangoValidationError as exc:
        raise ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages) from exc
    return success_response(ProductCostVersionSerializer(item).data)


def _uploaded_cost_file(request):
    upload = request.FILES.get("file")
    if upload is None:
        raise ValidationError({"file": "A CSV or XLSX file is required."})
    if not upload.name.lower().endswith((".csv", ".xlsx")):
        raise ValidationError({"file": "Only CSV and XLSX files are supported."})
    raw = upload.read()
    if not raw:
        raise ValidationError({"file": "The import file is empty."})
    return raw, upload.name


@api_view(["POST"])
@permission_classes([IsProductCostBackfillOperator])
def product_cost_import_preview(request):
    raw, filename = _uploaded_cost_file(request)
    return success_response(preview_cost_import(tenant=request.user.tenant, raw=raw, filename=filename))


@api_view(["POST"])
@permission_classes([IsProductCostBackfillOperator])
def product_cost_import_confirm(request):
    if not IsProductCostApprover().has_permission(request, None):
        raise PermissionDenied("products.cost.approve permission is required to confirm an import.")
    raw, filename = _uploaded_cost_file(request)
    result = confirm_cost_import(
        tenant=request.user.tenant,
        actor=request.user,
        raw=raw,
        filename=filename,
        token=request.data.get("token", ""),
        idempotency_key=request.headers.get("Idempotency-Key"),
    )
    return success_response(result, status=201)
