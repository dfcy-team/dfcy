from django.db import transaction
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.views import APIView

from apps.common.query import pagination_query
from apps.common.responses import error_response, paginated_data, success_response
from apps.common.error_codes import ErrorCode
from apps.products.models import ProductCategory, ProductLegacyItem, ProductSKU

from .models import ListingProfile, ListingTemplate, PlatformProductDetail
from .permissions import CanApproveListings, CanManageListings, CanManageTemplates, CanPublishListingEndpoint, CanViewListings, CanViewTemplates, CanViewPlatformProductDetails, CanManagePlatformProductDetails, CanImportPlatformProductDetails
from .serializers import (
    ListingProfileSerializer,
    ListingPublicationJobSerializer,
    ListingTemplateSerializer,
    PlatformProductDetailBulkUpdateSerializer,
    PlatformProductDetailSerializer,
)
from .platform_product_details import _resolve_sku, import_platform_product_details
from .services import approve_listing, queue_listing_publication, submit_listing_for_approval


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


@api_view(["GET", "POST"])
def profile_collection(request):
    _require(request, CanViewListings() if request.method == "GET" else CanManageListings())
    if request.method == "GET":
        queryset = ListingProfile.objects.filter(tenant=request.user.tenant).select_related("product", "store", "template").prefetch_related("variants")
        status = request.query_params.get("status", "").strip()
        if status:
            queryset = queryset.filter(status=status)
        return success_response(ListingProfileSerializer(queryset, many=True).data)
    serializer = ListingProfileSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    item = serializer.save(tenant=request.user.tenant, created_by=request.user)
    return success_response(ListingProfileSerializer(item).data, status=201)


@api_view(["GET", "PATCH"])
def profile_detail(request, pk):
    _require(request, CanViewListings() if request.method == "GET" else CanManageListings())
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
@permission_classes([CanManageListings])
def profile_submit(request, pk):
    return success_response(ListingProfileSerializer(submit_listing_for_approval(profile_id=pk, actor=request.user)).data)


@api_view(["POST"])
@permission_classes([CanApproveListings])
def profile_approve(request, pk):
    return success_response(ListingProfileSerializer(approve_listing(profile_id=pk, actor=request.user)).data)


@api_view(["POST"])
@permission_classes([CanPublishListingEndpoint])
def profile_publish(request, pk):
    execution_mode = str(request.data.get("execution_mode", "dry_run") or "dry_run").strip().lower()
    execution_channel = str(request.data.get("execution_channel", "rpa") or "rpa").strip().lower()
    action = str(request.data.get("action", "create") or "create").strip().lower()
    job, replayed = queue_listing_publication(
        profile_id=pk,
        actor=request.user,
        idempotency_key=request.headers.get("Idempotency-Key", ""),
        action=action,
        execution_mode=execution_mode,
        execution_channel=execution_channel,
        confirm_production=request.data.get("confirm_production") is True,
    )
    data = ListingPublicationJobSerializer(job).data
    data["replayed"] = replayed
    data["queue_boundary"] = "queue_only"
    data["external_platform_call"] = False
    return success_response(data, status=200 if replayed else 201)


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
