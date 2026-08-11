from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.common.responses import success_response
from apps.products.models import ProductSKU, ProductSPU
from apps.masterdata.models import StoreMaster

from .models import (
    ListingAttributeMapping,
    ListingProfile,
    ListingPublicationJob,
    ListingTask,
    ListingTaskErrorLog,
    ListingTaskStepLog,
    ListingTemplate,
    PlatformCategoryMapping,
)
from .permissions import (
    CanApproveListings,
    CanManageListingMappings,
    CanManageListingProfiles,
    CanManageListingWorkbench,
    CanManageListings,
    CanManageTemplates,
    CanPublishListings,
    CanViewListingMappings,
    CanViewListingTasks,
    CanViewListingWorkbench,
    CanViewListingProfiles,
    CanViewListings,
    CanViewTemplates,
)
from .serializers import (
    ListingAttributeMappingSerializer,
    ListingProfileSerializer,
    ListingPublicationJobSerializer,
    ListingTaskErrorLogSerializer,
    ListingTaskSerializer,
    ListingTaskStepLogSerializer,
    ListingTemplateSerializer,
    PlatformCategoryMappingSerializer,
)
from .services import (
    approve_listing,
    generate_listing_drafts,
    listing_task_snapshot,
    queue_listing_publication,
    submit_listing_for_approval,
    validate_listing,
)


def _require(request, permission):
    if not permission.has_permission(request, None):
        raise PermissionDenied()


@api_view(["GET", "POST"])
def template_collection(request):
    _require(request, CanViewTemplates() if request.method == "GET" else CanManageTemplates())
    if request.method == "GET":
        queryset = ListingTemplate.objects.filter(tenant=request.user.tenant).select_related("platform")
        return success_response(ListingTemplateSerializer(queryset, many=True).data)
    serializer = ListingTemplateSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    item = serializer.save(tenant=request.user.tenant, created_by=request.user)
    return success_response(ListingTemplateSerializer(item).data, status=201)


@api_view(["GET", "PATCH", "DELETE"])
def template_detail(request, pk):
    _require(request, CanViewTemplates() if request.method == "GET" else CanManageTemplates())
    item = get_object_or_404(ListingTemplate, pk=pk, tenant=request.user.tenant)
    if request.method == "GET":
        return success_response(ListingTemplateSerializer(item).data)
    if request.method == "DELETE":
        item.is_active = False
        item.save(update_fields=["is_active", "updated_at"])
        return success_response({"deleted": True})
    serializer = ListingTemplateSerializer(item, data=request.data, partial=True, context={"request": request})
    serializer.is_valid(raise_exception=True)
    return success_response(ListingTemplateSerializer(serializer.save()).data)


@api_view(["GET", "POST"])
def profile_collection(request):
    _require(request, CanViewListingProfiles() if request.method == "GET" else CanManageListingProfiles())
    if request.method == "GET":
        queryset = ListingProfile.objects.filter(tenant=request.user.tenant).select_related("product", "store", "template").prefetch_related("variants")
        status = request.query_params.get("status", "").strip()
        if status:
            queryset = queryset.filter(status=status)
        store_id = request.query_params.get("store_id")
        product_id = request.query_params.get("product_id") or request.query_params.get("spu_id")
        if store_id:
            queryset = queryset.filter(store_id=store_id)
        if product_id:
            queryset = queryset.filter(product_id=product_id)
        return success_response(ListingProfileSerializer(queryset, many=True).data)
    serializer = ListingProfileSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    item = serializer.save(tenant=request.user.tenant, created_by=request.user)
    return success_response(ListingProfileSerializer(item).data, status=201)


@api_view(["POST"])
@permission_classes([CanManageListingWorkbench])
def profile_batch_generate(request):
    spu_ids = request.data.get("spu_ids") or request.data.get("product_ids") or []
    store_ids = request.data.get("store_ids") or request.data.get("stores") or []
    template_id = request.data.get("template_id")
    template_ids = request.data.get("template_ids")
    sku_ids = request.data.get("sku_ids") or []
    profiles = generate_listing_drafts(
        tenant=request.user.tenant,
        actor=request.user,
        spu_ids=spu_ids,
        store_ids=store_ids,
        template_id=template_id,
        template_ids=template_ids,
        sku_ids=sku_ids,
        idempotency_key=request.headers.get("Idempotency-Key", ""),
    )
    return success_response({
        "count": len(profiles),
        "items": ListingProfileSerializer(profiles, many=True).data,
    }, status=201)


@api_view(["GET"])
@permission_classes([CanViewListingWorkbench])
def workbench_options(request):
    tenant = request.user.tenant
    return success_response({
        "spus": list(ProductSPU.objects.filter(tenant=tenant).values(
            "id", "spu_code", "legacy_spu_code", "product_name", "brand", "category",
        )),
        "skus": list(ProductSKU.objects.filter(tenant=tenant, is_active=True).values(
            "id", "spu_id", "sku_code", "legacy_sku_code", "color_code", "specification", "spec_values", "purchase_price",
        )),
        "stores": list(StoreMaster.objects.filter(tenant=tenant).select_related("platform").values(
            "id", "code", "name", "country_code", "currency", "platform_id", "platform__code", "platform__name",
        )),
        "templates": ListingTemplateSerializer(
            ListingTemplate.objects.filter(tenant=tenant, is_active=True).select_related("platform"), many=True,
        ).data,
    })


@api_view(["GET", "PATCH"])
def profile_detail(request, pk):
    _require(request, CanViewListingProfiles() if request.method == "GET" else CanManageListingProfiles())
    item = get_object_or_404(ListingProfile, pk=pk, tenant=request.user.tenant)
    if request.method == "GET":
        return success_response(ListingProfileSerializer(item).data)
    if item.status not in {ListingProfile.Status.DRAFT, ListingProfile.Status.READY, ListingProfile.Status.FAILED}:
        from apps.common.exceptions import StateConflict
        raise StateConflict("Only an editable listing draft can be changed.")
    serializer = ListingProfileSerializer(item, data=request.data, partial=True, context={"request": request})
    serializer.is_valid(raise_exception=True)
    item = serializer.save()
    return success_response(ListingProfileSerializer(item).data)


@api_view(["POST"])
@permission_classes([CanManageListingProfiles])
def profile_validate(request, pk):
    profile, errors = validate_listing(profile_id=pk, actor=request.user)
    return success_response({"valid": not errors, "errors": errors, "profile": ListingProfileSerializer(profile).data})


@api_view(["POST"])
@permission_classes([CanManageListingProfiles])
def profile_submit(request, pk):
    return success_response(ListingProfileSerializer(submit_listing_for_approval(profile_id=pk, actor=request.user)).data)


@api_view(["POST"])
@permission_classes([CanApproveListings])
def profile_approve(request, pk):
    return success_response(ListingProfileSerializer(approve_listing(profile_id=pk, actor=request.user)).data)


@api_view(["POST"])
@permission_classes([CanPublishListings])
def profile_publish(request, pk):
    job, replayed = queue_listing_publication(
        profile_id=pk,
        actor=request.user,
        idempotency_key=request.headers.get("Idempotency-Key", "") or request.data.get("idempotency_key", ""),
        action=request.data.get("action", "create"),
        execution_channel=request.data.get("execution_channel", "rpa"),
        execution_mode=request.data.get("execution_mode", request.data.get("mode", "dry_run")),
        confirm_production=request.data.get("confirm_production") is True,
    )
    data = ListingPublicationJobSerializer(job).data
    data["replayed"] = replayed
    return success_response(data, status=200 if replayed else 201)


def _mapping_collection(request, model, serializer_class, permission):
    _require(request, permission)
    tenant = request.user.tenant
    if request.method == "GET":
        queryset = model.objects.filter(tenant=tenant)
        platform_id = request.query_params.get("platform_id")
        status = request.query_params.get("status")
        if platform_id:
            queryset = queryset.filter(platform_id=platform_id)
        if status:
            queryset = queryset.filter(status=status)
        return success_response(serializer_class(queryset, many=True).data)
    serializer = serializer_class(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    return success_response(serializer_class(serializer.save(tenant=tenant, created_by=request.user)).data, status=201)


@api_view(["GET", "POST"])
def category_mapping_collection(request):
    return _mapping_collection(request, PlatformCategoryMapping, PlatformCategoryMappingSerializer, CanViewListingMappings() if request.method == "GET" else CanManageListingMappings())


@api_view(["GET", "PATCH", "DELETE"])
def category_mapping_detail(request, pk):
    _require(request, CanViewListingMappings() if request.method == "GET" else CanManageListingMappings())
    item = get_object_or_404(PlatformCategoryMapping, pk=pk, tenant=request.user.tenant)
    if request.method == "GET":
        return success_response(PlatformCategoryMappingSerializer(item).data)
    if request.method == "DELETE":
        item.status = PlatformCategoryMapping.Status.INACTIVE
        item.save(update_fields=["status", "updated_at"])
        return success_response({"deleted": True})
    serializer = PlatformCategoryMappingSerializer(item, data=request.data, partial=True, context={"request": request})
    serializer.is_valid(raise_exception=True)
    return success_response(PlatformCategoryMappingSerializer(serializer.save()).data)


@api_view(["GET", "POST"])
def attribute_mapping_collection(request):
    return _mapping_collection(request, ListingAttributeMapping, ListingAttributeMappingSerializer, CanViewListingMappings() if request.method == "GET" else CanManageListingMappings())


@api_view(["GET", "PATCH", "DELETE"])
def attribute_mapping_detail(request, pk):
    _require(request, CanViewListingMappings() if request.method == "GET" else CanManageListingMappings())
    item = get_object_or_404(ListingAttributeMapping, pk=pk, tenant=request.user.tenant)
    if request.method == "GET":
        return success_response(ListingAttributeMappingSerializer(item).data)
    if request.method == "DELETE":
        item.status = ListingAttributeMapping.Status.INACTIVE
        item.save(update_fields=["status", "updated_at"])
        return success_response({"deleted": True})
    serializer = ListingAttributeMappingSerializer(item, data=request.data, partial=True, context={"request": request})
    serializer.is_valid(raise_exception=True)
    return success_response(ListingAttributeMappingSerializer(serializer.save()).data)


@api_view(["GET"])
@permission_classes([CanViewListingTasks])
def task_collection(request):
    queryset = ListingTask.objects.filter(tenant=request.user.tenant).select_related("profile", "rpa_task").prefetch_related("step_logs", "error_logs")
    if request.query_params.get("status"):
        queryset = queryset.filter(status=request.query_params["status"])
    if request.query_params.get("execution_mode"):
        queryset = queryset.filter(execution_mode=request.query_params["execution_mode"])
    return success_response(ListingTaskSerializer(queryset, many=True).data)


@api_view(["GET"])
@permission_classes([CanViewListingTasks])
def task_detail(request, pk):
    task = get_object_or_404(
        ListingTask.objects.filter(tenant=request.user.tenant).select_related("profile", "rpa_task").prefetch_related("step_logs", "error_logs"),
        pk=pk,
    )
    return success_response(ListingTaskSerializer(task).data)


@api_view(["GET"])
@permission_classes([CanViewListingTasks])
def task_log_collection(request):
    queryset = ListingTaskStepLog.objects.filter(tenant=request.user.tenant).select_related("task")
    if request.query_params.get("task_id"):
        queryset = queryset.filter(task_id=request.query_params["task_id"])
    return success_response(ListingTaskStepLogSerializer(queryset, many=True).data)


@api_view(["GET"])
@permission_classes([CanViewListingTasks])
def task_exception_collection(request):
    queryset = ListingTaskErrorLog.objects.filter(tenant=request.user.tenant).select_related("task", "step")
    if request.query_params.get("resolved") in {"true", "false"}:
        queryset = queryset.filter(is_resolved=request.query_params["resolved"] == "true")
    if request.query_params.get("task_id"):
        queryset = queryset.filter(task_id=request.query_params["task_id"])
    return success_response(ListingTaskErrorLogSerializer(queryset, many=True).data)
