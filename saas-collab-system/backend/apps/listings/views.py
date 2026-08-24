from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.views import APIView

from apps.common.error_codes import ErrorCode
from apps.common.query import pagination_query
from apps.common.responses import success_response
from apps.common.responses import error_response, paginated_data
from apps.products.models import ProductCategory, ProductLegacyItem, ProductSKU, ProductSPU
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
    PlatformProductDetail,
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
    CanViewPlatformProductDetails,
    CanManagePlatformProductDetails,
    CanImportPlatformProductDetails,
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
    PlatformProductDetailBulkUpdateSerializer,
    PlatformProductDetailSerializer,
)
from .platform_product_details import _resolve_sku, import_platform_product_details, import_platform_product_ids
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

class PlatformProductDetailCollectionView(APIView):
    def get_permissions(self):
        return [CanViewPlatformProductDetails() if self.request.method == "GET" else CanManagePlatformProductDetails()]

    def get(self, request):
        queryset = PlatformProductDetail.objects.filter(tenant=request.user.tenant).select_related("platform", "store", "site", "internal_sku")
        for field in ("platform_id", "store_id", "site_id", "internal_sku_id"):
            value = request.query_params.get(field)
            if value:
                queryset = queryset.filter(**{field: value})
        for field in ("sales_status", "platform_variant_id", "platform_product_id", "platform_sku", "owner", "leader"):
            value = request.query_params.get(field, "").strip()
            if value:
                queryset = queryset.filter(**{f"{field}__icontains": value})
        category_id = request.query_params.get("category_id", "").strip()
        if category_id.isdigit():
            selected = get_object_or_404(ProductCategory, pk=int(category_id), tenant=request.user.tenant)
            category_ids = [selected.id]
            frontier = [selected.id]
            while frontier:
                frontier = list(ProductCategory.objects.filter(tenant=request.user.tenant, parent_id__in=frontier).values_list("id", flat=True))
                category_ids.extend(frontier)
            queryset = queryset.filter(internal_sku__spu__category_node_id__in=category_ids)
        search = request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search)
                | Q(variant__icontains=search)
                | Q(platform_sku__icontains=search)
                | Q(source_old_sku_code__icontains=search)
                | Q(internal_sku__sku_code__icontains=search)
                | Q(internal_sku__legacy_sku_code__icontains=search)
            )
        page, page_size = pagination_query(request)
        return success_response(
            paginated_data(
                request,
                queryset,
                PlatformProductDetailSerializer,
                page=page,
                page_size=page_size,
            )
        )

    def post(self, request):
        self.check_permissions(request)
        serializer = PlatformProductDetailSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        item = serializer.save(tenant=request.user.tenant)
        return success_response(PlatformProductDetailSerializer(item, context={"request": request}).data, status=201)


class PlatformProductDetailView(APIView):
    def get_permissions(self):
        return [CanViewPlatformProductDetails() if self.request.method == "GET" else CanManagePlatformProductDetails()]

    def get_object(self, request, pk):
        return get_object_or_404(PlatformProductDetail.objects.select_related("platform", "store", "site", "internal_sku"), pk=pk, tenant=request.user.tenant)

    def get(self, request, pk):
        return success_response(PlatformProductDetailSerializer(self.get_object(request, pk), context={"request": request}).data)

    def patch(self, request, pk):
        item = self.get_object(request, pk)
        payload = request.data.copy()
        # Accept either legacy or generated SKU code when remapping a detail.
        # Resolve it to the tenant-scoped FK before serializer validation so
        # callers cannot attach a SKU from another tenant or an unknown code.
        if "new_sku_code" in payload and "internal_sku" not in payload:
            new_code = str(payload.get("new_sku_code") or "").strip()
            if new_code:
                try:
                    payload["internal_sku"] = _resolve_sku(
                        request.user.tenant,
                        {"new_sku_code": new_code, "source_old_sku_code": ""},
                    ).pk
                except (ValueError, TypeError) as exc:
                    from rest_framework.exceptions import ValidationError
                    raise ValidationError({"new_sku_code": str(exc)}) from exc
            payload.pop("new_sku_code", None)
        if "source_old_sku_code" in payload and "internal_sku" not in payload:
            old_code = str(payload.get("source_old_sku_code") or "").strip()
            if old_code:
                try:
                    payload["internal_sku"] = _resolve_sku(request.user.tenant, {"source_old_sku_code": old_code, "new_sku_code": ""}).pk
                except (ValueError, TypeError) as exc:
                    from rest_framework.exceptions import ValidationError
                    raise ValidationError({"source_old_sku_code": str(exc)}) from exc
        serializer = PlatformProductDetailSerializer(item, data=payload, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        if "platform_variant_id" in serializer.validated_data:
            variant_id = serializer.validated_data["platform_variant_id"]
            conflict = PlatformProductDetail.objects.filter(
                tenant=request.user.tenant, platform=item.platform, store=item.store, platform_variant_id=variant_id,
            ).exclude(pk=item.pk).exists()
            if conflict:
                from rest_framework.exceptions import ValidationError
                raise ValidationError({"platform_variant_id": "同一平台店铺下的变体 ID 已存在。"})
        item = serializer.save()
        return success_response(PlatformProductDetailSerializer(item, context={"request": request}).data)


def _platform_detail_bulk_ref(raw):
    if isinstance(raw, dict):
        row_type = str(raw.get("row_type") or raw.get("type") or "").strip().lower()
        value = raw.get("id") or raw.get("pk")
    else:
        text = str(raw or "").strip()
        row_type, value = (text.split(":", 1) + [""])[:2] if ":" in text else ("", text)
    try:
        return row_type, int(value)
    except (TypeError, ValueError):
        return row_type, None


@api_view(["POST"])
@permission_classes([CanManagePlatformProductDetails])
@transaction.atomic
def platform_product_detail_bulk_update(request):
    serializer = PlatformProductDetailBulkUpdateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    payload = serializer.validated_data
    tenant = request.user.tenant
    match_type = payload["match_type"]
    code = payload["spu_code"]
    query = PlatformProductDetail.objects.select_for_update().select_related("platform", "store", "internal_sku", "internal_sku__spu")
    query = query.filter(tenant=tenant)
    if match_type == "old_spu":
        # A platform row may not have an internal SKU yet.  In that case the
        # source old-SKU value is still matchable through the tenant's legacy
        # import records, but an SPU code must never be compared directly to
        # an SKU column.
        legacy_sku_codes = ProductLegacyItem.objects.filter(
            tenant=tenant,
            legacy_spu_code=code,
        ).exclude(legacy_sku_code="").values("legacy_sku_code")
        query = query.filter(
            Q(internal_sku__spu__legacy_spu_code=code)
            | Q(source_old_sku_code__in=legacy_sku_codes)
        )
    else:
        query = query.filter(internal_sku__spu__spu_code=code)
    refs = {_platform_detail_bulk_ref(raw) for raw in (payload.get("ids") or [])}
    refs.discard(("", None))
    if refs:
        ids = [value for _kind, value in refs if value is not None]
        query = query.filter(pk__in=ids)
    rows = list(query.order_by("id"))
    result = {"matched": len(rows), "updated": 0, "unchanged": 0, "errors": []}
    if payload.get("preview"):
        result["preview"] = True
        return success_response(result)
    fields = payload.get("fields") or {}
    sentinel = object()
    mapping_code = fields.get("source_old_sku_code", sentinel)
    new_code = fields.get("new_sku_code", sentinel)
    internal_sku_id = fields.get("internal_sku", sentinel)
    mapped_sku = None
    if new_code is not sentinel or mapping_code is not sentinel or internal_sku_id is not sentinel:
        try:
            if new_code is not sentinel and str(new_code).strip():
                mapped_sku = _resolve_sku(tenant, {"new_sku_code": str(new_code).strip(), "source_old_sku_code": ""})
            elif mapping_code is not sentinel and str(mapping_code).strip():
                mapped_sku = _resolve_sku(tenant, {"new_sku_code": "", "source_old_sku_code": str(mapping_code).strip()})
            elif internal_sku_id is not sentinel:
                mapped_sku = ProductSKU.objects.filter(tenant=tenant, pk=internal_sku_id).first()
                if mapped_sku is None:
                    raise ValueError("指定的新 SKU 不存在或不属于当前租户。")
        except (ValueError, TypeError) as exc:
            return error_response(ErrorCode.VALIDATION_ERROR, str(exc), status=400)
    simple_fields = ("title", "variant", "sales_status", "owner", "leader", "platform_sku", "platform_product_id")
    for item in rows:
        try:
            updates = {}
            for field in simple_fields:
                if field in fields and getattr(item, field) != fields[field]:
                    updates[field] = fields[field]
            if mapped_sku is not None:
                updates["internal_sku"] = mapped_sku
                if mapping_code is not sentinel:
                    updates["source_old_sku_code"] = str(mapping_code).strip()
            if "platform_variant_id" in fields and fields["platform_variant_id"] != item.platform_variant_id:
                conflict = PlatformProductDetail.objects.filter(
                    tenant=tenant, platform_id=item.platform_id, store_id=item.store_id,
                    platform_variant_id=fields["platform_variant_id"],
                ).exclude(pk=item.pk).exists()
                if conflict:
                    raise ValueError("同一平台店铺下的变体 ID 已存在。")
                updates["platform_variant_id"] = fields["platform_variant_id"]
            if not updates:
                result["unchanged"] += 1
                continue
            for field, value in updates.items():
                setattr(item, field, value)
            item.save(update_fields=[*updates.keys(), "updated_at"])
            result["updated"] += 1
        except Exception as exc:
            result["errors"].append({"id": item.id, "message": str(exc)})
    result["error_count"] = len(result["errors"])
    return success_response(result)


class PlatformProductDetailImportView(APIView):
    permission_classes = [CanImportPlatformProductDetails]

    def post(self, request):
        upload = request.FILES.get("file")
        raw = upload.read() if upload else str(request.data.get("csv_text", "")).encode("utf-8-sig")
        if not raw:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({"file": "CSV/XLSX 文件不能为空。"})
        result = import_platform_product_details(
            tenant=request.user.tenant,
            raw=raw,
            filename=getattr(upload, "name", ""),
            platform_hint=request.data.get("platform", ""),
            dry_run=str(request.data.get("dry_run", "")).lower() in {"1", "true", "yes", "on"},
            actor=request.user,
        )
        return success_response(result)


class PlatformProductIdImportView(APIView):
    """Import only platform product IDs by an existing variant ID."""

    permission_classes = [CanImportPlatformProductDetails]

    def post(self, request):
        upload = request.FILES.get("file")
        raw = upload.read() if upload else str(request.data.get("csv_text", "")).encode("utf-8-sig")
        if not raw:
            raise ValidationError({"file": "CSV/XLSX 文件不能为空。"})
        result = import_platform_product_ids(
            tenant=request.user.tenant,
            raw=raw,
            filename=getattr(upload, "name", ""),
            dry_run=str(request.data.get("dry_run", "")).lower() in {"1", "true", "yes", "on"},
        )
        return success_response(result)
