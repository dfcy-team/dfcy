from django.shortcuts import get_object_or_404
from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError

from apps.common.responses import success_response
from apps.products.models import ProductResearch

from .models import DevelopmentCostEstimate, DevelopmentProductArchive, DevelopmentProject, ProductSalesSummary
from .permissions import (
    CanApproveCosts,
    CanFinalizeProjects,
    CanImportSales,
    CanGenerateProductArchives,
    CanManageCosts,
    CanManageProjects,
    CanManageProductArchives,
    CanConfirmProductArchives,
    CanReviewRequirements,
    CanViewProjects,
    CanViewProductArchives,
    CanViewSales,
)
from .serializers import (
    DevelopmentCostEstimateSerializer,
    DevelopmentProductArchiveConfirmationSerializer,
    DevelopmentProductArchiveSerializer,
    DevelopmentProjectSerializer,
    ProductSalesSummarySerializer,
)
from .services import (
    advance_project_stage,
    calculate_cost_summary,
    check_duplicate_requirement,
    confirm_product_archive,
    create_product_archive,
    finalize_product,
    formalize_product_archive,
    generate_trial_product,
    import_sales_csv,
    review_reminder_candidates,
    update_product_archive,
)


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


def _archive_queryset(request):
    return (
        DevelopmentProductArchive.objects.filter(tenant=request.user.tenant)
        .select_related(
            "project",
            "project__category_node",
            "category_node",
            "category_node__parent__parent",
            "formal_product",
            "formal_sku",
            "trial_product",
            "trial_sku",
            "platform_master",
            "store_master",
            "created_by",
            "updated_by",
        )
        .prefetch_related("events__actor")
    )


@api_view(["GET", "POST"])
def product_archive_collection(request):
    permission = CanViewProductArchives() if request.method == "GET" else CanManageProductArchives()
    if not permission.has_permission(request, product_archive_collection):
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied()
    if request.method == "GET":
        queryset = _archive_queryset(request)
        status = request.query_params.get("status", "").strip()
        search = request.query_params.get("search", "").strip()
        if status:
            queryset = queryset.filter(status=status)
        if search:
            queryset = queryset.filter(
                Q(archive_no__icontains=search)
                | Q(product_name__icontains=search)
                | Q(project__project_no__icontains=search)
                | Q(virtual_inventory_sku__icontains=search)
            )
        return success_response(DevelopmentProductArchiveSerializer(queryset, many=True).data)

    serializer = DevelopmentProductArchiveSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    project = serializer.validated_data.pop("project", None)
    if project is None:
        raise ValidationError({"project": "A development project is required."})
    archive, created = create_product_archive(project_id=project.id, actor=request.user, data=serializer.validated_data)
    return success_response(DevelopmentProductArchiveSerializer(archive).data, status=201 if created else 200)


@api_view(["GET", "PATCH"])
def product_archive_detail(request, pk):
    permission = CanViewProductArchives() if request.method == "GET" else CanManageProductArchives()
    if not permission.has_permission(request, product_archive_detail):
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied()
    archive = get_object_or_404(_archive_queryset(request), pk=pk)
    if request.method == "GET":
        return success_response(DevelopmentProductArchiveSerializer(archive).data)
    serializer = DevelopmentProductArchiveSerializer(
        archive,
        data=request.data,
        partial=True,
        context={"request": request},
    )
    serializer.is_valid(raise_exception=True)
    updated = update_product_archive(archive_id=archive.id, actor=request.user, data=serializer.validated_data)
    return success_response(DevelopmentProductArchiveSerializer(_archive_queryset(request).get(pk=updated.pk)).data)


@api_view(["POST"])
@permission_classes([CanConfirmProductArchives])
def product_archive_confirm(request, pk):
    serializer = DevelopmentProductArchiveConfirmationSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    archive, changed = confirm_product_archive(
        archive_id=pk,
        actor=request.user,
        test_result=serializer.validated_data.get("test_result"),
        test_notes=serializer.validated_data.get("test_notes"),
        idempotency_key=request.headers.get("Idempotency-Key", ""),
    )
    return success_response({"archive": DevelopmentProductArchiveSerializer(archive).data, "changed": changed})


@api_view(["POST"])
@permission_classes([CanGenerateProductArchives])
def product_archive_generate_trial(request, pk):
    archive, changed = generate_trial_product(
        archive_id=pk,
        actor=request.user,
        data=request.data,
        idempotency_key=request.headers.get("Idempotency-Key", ""),
    )
    return success_response({
        "archive": DevelopmentProductArchiveSerializer(_archive_queryset(request).get(pk=archive.pk)).data,
        "changed": changed,
        "development_spu_code": archive.development_spu_code,
        "trial_product_id": archive.trial_product_id,
        "trial_spu_code": archive.trial_product.spu_code if archive.trial_product_id else "",
        "trial_sku_id": archive.trial_sku_id,
        "trial_sku_code": archive.trial_sku.sku_code if archive.trial_sku_id else "",
        "formal_product_id": archive.formal_product_id,
        "formal_sku_id": archive.formal_sku_id,
        "formal_sku_code": archive.formal_sku.sku_code if archive.formal_sku_id else "",
    })


@api_view(["POST"])
@permission_classes([CanConfirmProductArchives])
def product_archive_formalize(request, pk):
    product, created = formalize_product_archive(
        archive_id=pk,
        actor=request.user,
        idempotency_key=request.headers.get("Idempotency-Key", ""),
    )
    archive = _archive_queryset(request).get(pk=pk)
    return success_response({
        "archive": DevelopmentProductArchiveSerializer(archive).data,
        "product_id": product.id,
        "spu_code": product.spu_code,
        "formal_sku_id": archive.formal_sku_id,
        "formal_sku_code": archive.formal_sku.sku_code if archive.formal_sku_id else "",
        "created": created,
    })


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
