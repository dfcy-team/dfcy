from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError

from apps.common.responses import success_response
from apps.products.models import ProductResearch

from .models import DevelopmentCostEstimate, DevelopmentProject, ProductSalesSummary
from .permissions import (
    CanApproveCosts,
    CanFinalizeProjects,
    CanImportSales,
    CanManageCosts,
    CanManageProjects,
    CanReviewRequirements,
    CanViewProjects,
    CanViewSales,
)
from .serializers import DevelopmentCostEstimateSerializer, DevelopmentProjectSerializer, ProductSalesSummarySerializer
from .services import advance_project_stage, calculate_cost_summary, check_duplicate_requirement, finalize_product, import_sales_csv, review_reminder_candidates


@api_view(["POST"])
@permission_classes([CanReviewRequirements])
def duplicate_check(request):
    return success_response({"matches": check_duplicate_requirement(tenant=request.user.tenant, product_name=request.data.get("product_name", ""), category=request.data.get("category", ""), exclude_id=request.data.get("exclude_id"))})


@api_view(["GET", "POST"])
def project_collection(request):
    permission = CanViewProjects() if request.method == "GET" else CanManageProjects()
    if not permission.has_permission(request, project_collection):
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied()
    if request.method == "GET":
        queryset = DevelopmentProject.objects.filter(tenant=request.user.tenant).select_related("assigned_to", "supplier", "finalized_product")
        return success_response(DevelopmentProjectSerializer(queryset, many=True).data)
    serializer = DevelopmentProjectSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    item = serializer.save(tenant=request.user.tenant, created_by=request.user)
    return success_response(DevelopmentProjectSerializer(item).data, status=201)


@api_view(["GET"])
@permission_classes([CanViewProjects])
def project_detail(request, pk):
    item = get_object_or_404(DevelopmentProject, pk=pk, tenant=request.user.tenant)
    return success_response(DevelopmentProjectSerializer(item).data)


@api_view(["POST"])
@permission_classes([CanFinalizeProjects])
def project_finalize(request, pk):
    product, created = finalize_product(project_id=pk, actor=request.user)
    return success_response({"product_id": product.id, "spu_code": product.spu_code, "created": created})


@api_view(["POST"])
@permission_classes([CanFinalizeProjects])
def project_advance(request, pk):
    item = advance_project_stage(
        project_id=pk,
        actor=request.user,
        target_stage=request.data.get("target_stage", ""),
        approval_notes=request.data.get("approval_notes", ""),
        deliverables=request.data.get("deliverables", {}),
    )
    return success_response(DevelopmentProjectSerializer(item).data)


@api_view(["POST"])
@permission_classes([CanManageCosts])
def cost_calculate(request, pk):
    item = calculate_cost_summary(estimate_id=pk, actor=request.user)
    return success_response(DevelopmentCostEstimateSerializer(item).data)


@api_view(["POST"])
@permission_classes([CanApproveCosts])
def cost_approve(request, pk):
    item = calculate_cost_summary(estimate_id=pk, actor=request.user, approve=True)
    return success_response(DevelopmentCostEstimateSerializer(item).data)


@api_view(["POST"])
@permission_classes([CanImportSales])
def sales_import(request):
    csv_text = request.data.get("csv_text", "")
    if not csv_text and request.FILES.get("file"):
        csv_text = request.FILES["file"].read().decode("utf-8-sig")
    if not csv_text:
        raise ValidationError({"csv": "CSV text or file is required."})
    return success_response(import_sales_csv(tenant=request.user.tenant, csv_text=csv_text, actor=request.user))


@api_view(["GET"])
@permission_classes([CanViewSales])
def sales_summary(request):
    queryset = ProductSalesSummary.objects.filter(tenant=request.user.tenant)
    return success_response(ProductSalesSummarySerializer(queryset, many=True).data)


@api_view(["GET"])
@permission_classes([CanViewProjects])
def review_reminders(request):
    return success_response({"results": review_reminder_candidates(tenant=request.user.tenant)})
