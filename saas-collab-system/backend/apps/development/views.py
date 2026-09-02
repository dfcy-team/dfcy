from django.shortcuts import get_object_or_404
from django.db import models
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError

from apps.common.responses import success_response
from apps.products.models import ProductResearch

from .models import (
    DevelopmentCostEstimate,
    DevelopmentProject,
    DevelopmentProductArchive,
    DevelopmentRequirementCompetitorLink,
    ProductSalesSummary,
)
from .permissions import (
    CanApproveCosts,
    CanFinalizeProjects,
    CanImportSales,
    CanManageCosts,
    CanManageProjects,
    CanManageProductArchives,
    CanConfirmProductArchives,
    CanManageCompetitorLinks,
    CanReviewRequirements,
    CanViewCompetitorReports,
    CanViewProjects,
    CanViewProductArchives,
    CanViewSales,
)
from .serializers import (
    CompetitorReportSelectionSerializer,
    DevelopmentCostEstimateSerializer,
    DevelopmentProjectSerializer,
    DevelopmentProductArchiveConfirmationSerializer,
    DevelopmentProductArchiveSerializer,
    DevelopmentRequirementCompetitorLinkSerializer,
    ProductSalesSummarySerializer,
)
from .services import (
    advance_project_stage,
    calculate_cost_summary,
    check_duplicate_requirement,
    create_competitor_link,
    create_product_archive,
    confirm_product_archive,
    finalize_product,
    formalize_product_archive,
    get_competitor_report_client,
    import_sales_csv,
    list_competitor_links,
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
        queryset = DevelopmentProject.objects.filter(tenant=request.user.tenant).select_related(
            "assigned_to",
            "supplier",
            "finalized_product",
            "category_node",
            "requirement__category_node",
        )
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


@api_view(["GET", "POST"])
def product_archive_collection(request):
    """List/create virtual development product archives in the workspace."""

    permission = CanViewProductArchives() if request.method == "GET" else CanManageProductArchives()
    if not permission.has_permission(request, product_archive_collection):
        from rest_framework.exceptions import PermissionDenied

        raise PermissionDenied()
    if request.method == "GET":
        queryset = (
            DevelopmentProductArchive.objects.filter(tenant=request.user.tenant)
            .select_related(
                "project",
                "project__category_node",
                "project__requirement__category_node",
                "category_node",
                "category_node__parent__parent",
                "formal_product",
                "created_by",
                "updated_by",
            )
            .prefetch_related("events__actor")
        )
        status = request.query_params.get("status", "").strip()
        platform = request.query_params.get("platform", "").strip()
        site = request.query_params.get("site", "").strip()
        search = request.query_params.get("search", "").strip()
        if status:
            queryset = queryset.filter(status=status)
        if platform:
            queryset = queryset.filter(platform=platform)
        if site:
            queryset = queryset.filter(site=site)
        if search:
            queryset = queryset.filter(
                models.Q(archive_no__icontains=search)
                | models.Q(product_name__icontains=search)
                | models.Q(project__project_no__icontains=search)
                | models.Q(virtual_inventory_sku__icontains=search)
            )
        return success_response(DevelopmentProductArchiveSerializer(queryset, many=True).data)

    serializer = DevelopmentProductArchiveSerializer(
        data=request.data,
        context={"request": request},
    )
    serializer.is_valid(raise_exception=True)
    project = serializer.validated_data.pop("project", None)
    if project is None:
        raise ValidationError({"project": "A development project is required."})
    archive, created = create_product_archive(
        project_id=project.id,
        actor=request.user,
        data=serializer.validated_data,
    )
    return success_response(
        DevelopmentProductArchiveSerializer(archive).data,
        status=201 if created else 200,
    )


@api_view(["GET", "PATCH"])
def product_archive_detail(request, pk):
    permission = CanViewProductArchives() if request.method == "GET" else CanManageProductArchives()
    if not permission.has_permission(request, product_archive_detail):
        from rest_framework.exceptions import PermissionDenied

        raise PermissionDenied()
    archive = get_object_or_404(
        DevelopmentProductArchive.objects.filter(tenant=request.user.tenant)
        .select_related(
            "project",
            "project__category_node",
            "project__requirement__category_node",
            "category_node",
            "category_node__parent__parent",
            "formal_product",
            "created_by",
            "updated_by",
        )
        .prefetch_related("events__actor"),
        pk=pk,
    )
    if request.method == "GET":
        return success_response(DevelopmentProductArchiveSerializer(archive).data)

    serializer = DevelopmentProductArchiveSerializer(
        archive,
        data=request.data,
        partial=True,
        context={"request": request},
    )
    serializer.is_valid(raise_exception=True)
    updated = update_product_archive(
        archive_id=archive.id,
        actor=request.user,
        data=serializer.validated_data,
    )
    updated = (
        DevelopmentProductArchive.objects.select_related(
            "project",
            "project__category_node",
            "project__requirement__category_node",
            "category_node",
            "category_node__parent__parent",
            "formal_product",
            "created_by",
            "updated_by",
        )
        .prefetch_related("events__actor")
        .get(pk=updated.pk)
    )
    return success_response(DevelopmentProductArchiveSerializer(updated).data)


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
    return success_response(
        {
            "archive": DevelopmentProductArchiveSerializer(archive).data,
            "changed": changed,
        }
    )


@api_view(["POST"])
@permission_classes([CanConfirmProductArchives])
def product_archive_formalize(request, pk):
    product, created = formalize_product_archive(
        archive_id=pk,
        actor=request.user,
        idempotency_key=request.headers.get("Idempotency-Key", ""),
    )
    archive = (
        DevelopmentProductArchive.objects.select_related(
            "project",
            "project__category_node",
            "project__requirement__category_node",
            "category_node",
            "category_node__parent__parent",
            "formal_product",
            "created_by",
            "updated_by",
        )
        .prefetch_related("events__actor")
        .get(pk=pk, tenant=request.user.tenant)
    )
    return success_response(
        {
            "archive": DevelopmentProductArchiveSerializer(archive).data,
            "product_id": product.id,
            "spu_code": product.spu_code,
            "created": created,
        }
    )


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


def _competitor_params(request):
    allowed = ("platform", "site", "product_id", "search", "page", "page_size")
    return {
        key: request.query_params[key]
        for key in allowed
        if request.query_params.get(key) not in (None, "")
    }


@api_view(["GET"])
@permission_classes([CanViewCompetitorReports])
def competitor_report_collection(request):
    """Read-only proxy for reports owned by the competitor service."""

    payload = get_competitor_report_client().list_reports(
        tenant=request.user.tenant,
        params=_competitor_params(request),
    )
    return success_response(payload)


@api_view(["GET"])
@permission_classes([CanViewCompetitorReports])
def competitor_report_detail(request, report_id):
    payload = get_competitor_report_client().get_report(report_id, tenant=request.user.tenant)
    return success_response(payload)


@api_view(["GET"])
@permission_classes([CanViewCompetitorReports])
def competitor_report_evidence(request, report_id):
    payload = get_competitor_report_client().list_evidence(
        report_id,
        tenant=request.user.tenant,
        page=request.query_params.get("page", 1),
        page_size=request.query_params.get("page_size", 20),
    )
    return success_response(payload)


def _requirement_for_user(request, requirement_id):
    return get_object_or_404(
        ProductResearch,
        pk=requirement_id,
        tenant=request.user.tenant,
    )


@api_view(["GET", "POST"])
def requirement_competitor_collection(request, requirement_id):
    permission = (
        CanViewCompetitorReports()
        if request.method == "GET"
        else CanManageCompetitorLinks()
    )
    if not permission.has_permission(request, requirement_competitor_collection):
        from rest_framework.exceptions import PermissionDenied

        raise PermissionDenied()

    requirement = _requirement_for_user(request, requirement_id)
    if request.method == "GET":
        links = list_competitor_links(requirement=requirement, tenant=request.user.tenant)
        return success_response(DevelopmentRequirementCompetitorLinkSerializer(links, many=True).data)

    # The URL/body report ID identifies which upstream report to read.  All
    # metadata in the response is sourced by the server-side GET client.
    report_id = request.data.get("report_id")
    if not isinstance(report_id, (str, int)) or not str(report_id).strip():
        raise ValidationError({"report_id": "A competitor report ID is required."})
    serializer = CompetitorReportSelectionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    link = create_competitor_link(
        requirement=requirement,
        actor=request.user,
        report_id=str(report_id).strip(),
        selection=serializer.validated_data,
        client=get_competitor_report_client(),
    )
    return success_response(DevelopmentRequirementCompetitorLinkSerializer(link).data, status=201)


@api_view(["DELETE"])
@permission_classes([CanManageCompetitorLinks])
def requirement_competitor_detail(request, requirement_id, link_id):
    requirement = _requirement_for_user(request, requirement_id)
    link = get_object_or_404(
        DevelopmentRequirementCompetitorLink,
        pk=link_id,
        requirement=requirement,
        tenant=request.user.tenant,
    )
    link.delete()
    return success_response({"deleted": True})
