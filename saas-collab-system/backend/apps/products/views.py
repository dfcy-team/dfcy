import csv
import io
import os
import re
import secrets
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes

from apps.common.query import pagination_query
from apps.common.error_codes import ErrorCode
from apps.common.exceptions import StateConflict
from apps.common.responses import error_response, paginated_data, success_response
from apps.permissions.ui_p5_scopes import (
    filter_product_research,
    filter_product_skus,
    filter_product_spus,
    require_create_scope,
)

from .coding_services import SEASONS, category_path
from .standard_colors import STANDARD_COLORS
from .models import (
    ProductBundleComponent,
    ProductCategory,
    ProductColor,
    ProductAttribute,
    ProductLegacyItem,
    ProductResearch,
    ProductSKU,
    ProductSPU,
    ProductStatusRecommendation,
    ProductStatusTransition,
)
from apps.files.models import AttachmentFile
from .permissions import (
    IsProductAttributeReadOrManage,
    IsProductBundleReadOrManage,
    IsProductCategoryReadOrManage,
    IsProductCodeFreezer,
    IsProductColorReadOrManage,
    IsProductMasterReadOrManage,
    IsProductResearchReadOrManage,
    IsProductStatusConfirmer,
    IsProductStatusEvaluator,
    IsProductStatusViewer,
)
from .serializers import (
    ProductBundleComponentSerializer,
    ProductCategorySerializer,
    ProductColorSerializer,
    ProductAttributeSerializer,
    ProductLegacyItemSerializer,
    ProductResearchSerializer,
    ProductSKUSerializer,
    ProductSPUSerializer,
    ProductStatusRecommendationSerializer,
    ProductStatusTransitionSerializer,
)
from .status_services import confirm_recommendation, evaluate_mock_status, reject_recommendation


def _serializer_context(request):
    return {"request": request}


# Product images deliberately use a narrow, tenant-scoped storage boundary.
# This avoids placing binary data in ProductSKU and keeps URL uploads and file
# uploads on the same ``image_url`` business field.
PRODUCT_IMAGE_MAX_BYTES = 5 * 1024 * 1024
PRODUCT_IMAGE_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".avif": "image/avif",
}


def _product_image_relative_path(tenant_id, extension):
    return f"product-images/tenant-{int(tenant_id)}/{secrets.token_hex(20)}{extension}"


def _validate_product_image(uploaded):
    if uploaded is None:
        raise ValueError("Image file is required.")
    if uploaded.size <= 0 or uploaded.size > PRODUCT_IMAGE_MAX_BYTES:
        raise ValueError("Image file must be between 1 byte and 5 MB.")
    original_name = str(getattr(uploaded, "name", "") or "")
    extension = Path(original_name).suffix.lower()
    expected_type = PRODUCT_IMAGE_TYPES.get(extension)
    content_type = str(getattr(uploaded, "content_type", "") or "").lower().split(";", 1)[0].strip()
    if not expected_type or content_type != expected_type:
        raise ValueError("Only jpg, jpeg, png, gif, webp and avif images with a matching MIME type are allowed.")
    head = uploaded.read(64)
    uploaded.seek(0)
    valid_magic = {
        ".jpg": head.startswith(b"\xff\xd8\xff"),
        ".jpeg": head.startswith(b"\xff\xd8\xff"),
        ".png": head.startswith(b"\x89PNG\r\n\x1a\n"),
        ".gif": head.startswith((b"GIF87a", b"GIF89a")),
        ".webp": head.startswith(b"RIFF") and head[8:12] == b"WEBP",
        # AVIF is an ISO-BMFF file; require an avif/avis ftyp brand.
        ".avif": b"ftypavif" in head[4:32] or b"ftypavis" in head[4:32],
    }[extension]
    if not valid_magic:
        raise ValueError("The uploaded file content does not match its image type.")
    return extension, expected_type


def _stored_product_image_path(image_url):
    """Return a storage-relative path only for our own media URLs."""
    if not image_url:
        return None
    media_url = str(settings.MEDIA_URL or "/media/")
    if not media_url.startswith("/"):
        return None
    prefix = media_url.rstrip("/") + "/"
    if not str(image_url).startswith(prefix):
        return None
    relative = str(image_url)[len(prefix):].replace("\\", "/")
    if not relative.startswith("product-images/") or ".." in relative.split("/"):
        return None
    return relative


def _replace_product_image(item, uploaded, request):
    extension, file_type = _validate_product_image(uploaded)
    relative = _product_image_relative_path(item.tenant_id, extension)
    media_root = Path(settings.MEDIA_ROOT).resolve()
    target = (media_root / relative).resolve()
    if media_root not in target.parents:
        raise ValueError("Invalid image storage path.")
    uploaded.seek(0)
    saved_name = default_storage.save(relative, ContentFile(uploaded.read()))
    media_url = f"{str(settings.MEDIA_URL).rstrip('/')}/{saved_name.replace(os.sep, '/') }"
    old_path = _stored_product_image_path(item.image_url)
    try:
        item.image_url = media_url
        item.save(update_fields=["image_url", "updated_at"])
        AttachmentFile.objects.create(
            tenant=item.tenant,
            file_name=str(getattr(uploaded, "name", "") or saved_name),
            file_path=saved_name,
            file_type=file_type,
            file_size=int(uploaded.size),
            uploaded_by=request.user,
            business_type="product_sku_image",
            business_id=str(item.pk),
            is_private=False,
        )
    except Exception:
        default_storage.delete(saved_name)
        raise
    if old_path and old_path != saved_name:
        default_storage.delete(old_path)
    return item


@api_view(["GET"])
@permission_classes([IsProductMasterReadOrManage])
def product_coding_options(request):
    return success_response({"seasons": SEASONS, "product_types": ProductSPU.ProductType.choices})


@api_view(["GET", "POST"])
@permission_classes([IsProductAttributeReadOrManage])
def product_attribute_collection(request):
    if request.method == "GET":
        queryset = ProductAttribute.objects.filter(tenant=request.user.tenant)
        return success_response(ProductAttributeSerializer(queryset, many=True).data)
    require_create_scope(request.user, "products.attribute.manage")
    with transaction.atomic():
        existing = list(ProductAttribute.objects.select_for_update().filter(tenant=request.user.tenant).values_list("code", flat=True))
        next_code = next((str(number) for number in range(1, 10) if str(number) not in existing), None)
        if next_code is None:
            return error_response(ErrorCode.STATE_CONFLICT, "一位属性编码已用完（1-9）。", status=409)
        serializer = ProductAttributeSerializer(data=request.data, context=_serializer_context(request))
        serializer.is_valid(raise_exception=True)
        item = serializer.save(tenant=request.user.tenant, code=next_code)
    return success_response(ProductAttributeSerializer(item).data, status=201)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsProductAttributeReadOrManage])
def product_attribute_detail(request, pk):
    item = get_object_or_404(ProductAttribute, pk=pk, tenant=request.user.tenant)
    if request.method == "GET":
        return success_response(ProductAttributeSerializer(item).data)
    if request.method == "DELETE":
        if ProductSPU.objects.filter(tenant=request.user.tenant, season_code=item.code).exists():
            return error_response(ErrorCode.STATE_CONFLICT, "属性已被商品使用，不能删除。", status=409)
        item.delete()
        return success_response({"deleted": True})
    serializer = ProductAttributeSerializer(item, data=request.data, partial=True, context=_serializer_context(request))
    serializer.is_valid(raise_exception=True)
    item = serializer.save()
    return success_response(ProductAttributeSerializer(item).data)


@api_view(["GET", "POST"])
@permission_classes([IsProductCategoryReadOrManage])
def product_category_collection(request):
    if request.method == "GET":
        queryset = ProductCategory.objects.filter(tenant=request.user.tenant)
        level = request.query_params.get("level", "").strip()
        parent_id = request.query_params.get("parent_id", "").strip()
        if level.isdigit():
            queryset = queryset.filter(level=int(level))
        if parent_id.isdigit():
            queryset = queryset.filter(parent_id=int(parent_id))
        return success_response(ProductCategorySerializer(queryset, many=True).data)
    require_create_scope(request.user, "products.category.manage")
    serializer = ProductCategorySerializer(data=request.data, context=_serializer_context(request))
    serializer.is_valid(raise_exception=True)
    item = serializer.save(tenant=request.user.tenant)
    return success_response(ProductCategorySerializer(item).data, status=201)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsProductCategoryReadOrManage])
def product_category_detail(request, pk):
    item = get_object_or_404(ProductCategory, pk=pk, tenant=request.user.tenant)
    if request.method == "DELETE":
        if item.children.exists():
            return error_response(ErrorCode.STATE_CONFLICT, "请先删除下级分类。", status=409)
        if item.products.exists():
            return error_response(ErrorCode.STATE_CONFLICT, "分类已被商品使用，不能删除。", status=409)
        item.delete()
        return success_response({"deleted": True})
    if request.method == "GET":
        return success_response(ProductCategorySerializer(item).data)
    serializer = ProductCategorySerializer(item, data=request.data, partial=True, context=_serializer_context(request))
    serializer.is_valid(raise_exception=True)
    item = serializer.save()
    return success_response(ProductCategorySerializer(item).data)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsProductAttributeReadOrManage])
def product_category_attributes(request, pk):
    item = get_object_or_404(ProductCategory, pk=pk, tenant=request.user.tenant)
    try:
        category_path(item)
    except DjangoValidationError:
        return error_response(ErrorCode.VALIDATION_ERROR, "规格只能设置在 L3 分类或没有 L3 下级的 L2 分类。", status=400)
    if request.method == "GET":
        return success_response({"category_id": item.id, "spec_dimensions": item.spec_dimensions})
    serializer = ProductCategorySerializer(
        item,
        data={"spec_dimensions": request.data.get("spec_dimensions", [])},
        partial=True,
        context=_serializer_context(request),
    )
    serializer.is_valid(raise_exception=True)
    item = serializer.save()
    return success_response({"category_id": item.id, "spec_dimensions": item.spec_dimensions})


@api_view(["GET", "POST"])
@permission_classes([IsProductColorReadOrManage])
def product_color_collection(request):
    if request.method == "GET":
        queryset = ProductColor.objects.filter(tenant=request.user.tenant)
        return success_response(ProductColorSerializer(queryset, many=True).data)
    require_create_scope(request.user, "products.color.manage")
    serializer = ProductColorSerializer(data=request.data, context=_serializer_context(request))
    serializer.is_valid(raise_exception=True)
    item = serializer.save(tenant=request.user.tenant)
    return success_response(ProductColorSerializer(item).data, status=201)


@api_view(["POST"])
@permission_classes([IsProductColorReadOrManage])
def import_standard_product_colors(request):
    require_create_scope(request.user, "products.color.manage")
    created = updated = 0
    for code, name in STANDARD_COLORS:
        _, was_created = ProductColor.objects.update_or_create(
            tenant=request.user.tenant,
            code=code,
            defaults={"name": name, "is_active": True},
        )
        created += int(was_created)
        updated += int(not was_created)
    return success_response({"created": created, "updated": updated, "total": len(STANDARD_COLORS)}, status=201)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsProductColorReadOrManage])
def product_color_detail(request, pk):
    item = get_object_or_404(ProductColor, pk=pk, tenant=request.user.tenant)
    if request.method == "DELETE":
        if ProductSKU.objects.filter(tenant=request.user.tenant, color_code=item.code).exists():
            return error_response(ErrorCode.STATE_CONFLICT, "颜色已被 SKU 使用，不能删除。", status=409)
        item.delete()
        return success_response({"deleted": True})
    if request.method == "GET":
        return success_response(ProductColorSerializer(item).data)
    serializer = ProductColorSerializer(item, data=request.data, partial=True, context=_serializer_context(request))
    serializer.is_valid(raise_exception=True)
    item = serializer.save()
    return success_response(ProductColorSerializer(item).data)


@api_view(["GET", "POST"])
@permission_classes([IsProductResearchReadOrManage])
def product_research_collection(request):
    if request.method == "GET":
        queryset = ProductResearch.objects.filter(tenant=request.user.tenant)
        queryset = filter_product_research(request.user, queryset, "products.research.view")
        search = request.query_params.get("search", "").strip()
        platform = request.query_params.get("platform", "").strip()
        if search:
            queryset = queryset.filter(product_name__icontains=search)
        if platform:
            queryset = queryset.filter(platform=platform)
        page, page_size = pagination_query(request)
        return success_response(
            paginated_data(request, queryset, ProductResearchSerializer, page=page, page_size=page_size)
        )

    require_create_scope(request.user, "products.research.manage", allow_own=True)
    serializer = ProductResearchSerializer(data=request.data, context=_serializer_context(request))
    serializer.is_valid(raise_exception=True)
    item = serializer.save(tenant=request.user.tenant, created_by=request.user)
    return success_response(ProductResearchSerializer(item).data, status=201)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsProductResearchReadOrManage])
def product_research_detail(request, pk):
    permission_code = "products.research.view" if request.method == "GET" else "products.research.manage"
    queryset = ProductResearch.objects.filter(tenant=request.user.tenant)
    item = get_object_or_404(filter_product_research(request.user, queryset, permission_code), pk=pk)
    if request.method == "GET":
        return success_response(ProductResearchSerializer(item).data)

    serializer = ProductResearchSerializer(
        item,
        data=request.data,
        partial=True,
        context=_serializer_context(request),
    )
    serializer.is_valid(raise_exception=True)
    item = serializer.save()
    return success_response(ProductResearchSerializer(item).data)


@api_view(["GET", "POST"])
@permission_classes([IsProductMasterReadOrManage])
def product_spu_collection(request):
    if request.method == "GET":
        queryset = ProductSPU.objects.filter(tenant=request.user.tenant).prefetch_related("skus")
        queryset = filter_product_spus(request.user, queryset, "products.master.view")
        search = request.query_params.get("search", "").strip()
        status = request.query_params.get("sales_status", "").strip()
        if search:
            queryset = queryset.filter(product_name__icontains=search)
        if status:
            queryset = queryset.filter(sales_status=status)
        category_id = request.query_params.get("category_id", "").strip()
        if category_id.isdigit():
            selected = get_object_or_404(ProductCategory, pk=int(category_id), tenant=request.user.tenant)
            ids = [selected.id]
            frontier = [selected.id]
            while frontier:
                frontier = list(ProductCategory.objects.filter(tenant=request.user.tenant, parent_id__in=frontier).values_list("id", flat=True))
                ids.extend(frontier)
            queryset = queryset.filter(category_node_id__in=ids)
        page, page_size = pagination_query(request)
        return success_response(paginated_data(request, queryset, ProductSPUSerializer, page=page, page_size=page_size))

    require_create_scope(request.user, "products.master.manage")
    serializer = ProductSPUSerializer(data=request.data, context=_serializer_context(request))
    serializer.is_valid(raise_exception=True)
    item = serializer.save(tenant=request.user.tenant)
    return success_response(ProductSPUSerializer(item).data, status=201)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsProductMasterReadOrManage])
def product_spu_detail(request, pk):
    permission_code = "products.master.view" if request.method == "GET" else "products.master.manage"
    queryset = ProductSPU.objects.filter(tenant=request.user.tenant).prefetch_related("skus")
    item = get_object_or_404(filter_product_spus(request.user, queryset, permission_code), pk=pk)
    if request.method == "DELETE":
        if item.skus.exists():
            return error_response(ErrorCode.STATE_CONFLICT, "商品已存在 SKU，请先处理 SKU 或业务数据。", status=409)
        item.delete()
        return success_response({"deleted": True})
    if request.method == "GET":
        return success_response(ProductSPUSerializer(item).data)

    serializer = ProductSPUSerializer(
        item,
        data=request.data,
        partial=True,
        context=_serializer_context(request),
    )
    serializer.is_valid(raise_exception=True)
    item = serializer.save()
    return success_response(ProductSPUSerializer(item).data)


@api_view(["POST"])
@permission_classes([IsProductCodeFreezer])
def freeze_product_spu_code(request, pk):
    queryset = ProductSPU.objects.filter(tenant=request.user.tenant)
    item = get_object_or_404(filter_product_spus(request.user, queryset, "products.master.freeze"), pk=pk)
    item.is_code_frozen = True
    item.skus.update(is_code_frozen=True)
    item.save(update_fields=["is_code_frozen", "updated_at"])
    return success_response(ProductSPUSerializer(item).data)


@api_view(["GET", "POST"])
@permission_classes([IsProductMasterReadOrManage])
def product_sku_collection(request):
    if request.method == "GET":
        queryset = ProductSKU.objects.filter(tenant=request.user.tenant).select_related("spu")
        queryset = filter_product_skus(request.user, queryset, "products.master.view")
        search = request.query_params.get("search", "").strip()
        spu_id = request.query_params.get("spu_id", "").strip()
        active_status = request.query_params.get("active_status", "active").strip()
        if search:
            queryset = queryset.filter(sku_code__icontains=search)
        if spu_id.isdigit():
            queryset = queryset.filter(spu_id=int(spu_id))
        if active_status == "active":
            queryset = queryset.filter(is_active=True)
        elif active_status == "inactive":
            queryset = queryset.filter(is_active=False)
        page, page_size = pagination_query(request)
        return success_response(paginated_data(request, queryset, ProductSKUSerializer, page=page, page_size=page_size))

    require_create_scope(request.user, "products.master.manage")
    serializer = ProductSKUSerializer(data=request.data, context=_serializer_context(request))
    serializer.is_valid(raise_exception=True)
    item = serializer.save(tenant=request.user.tenant)
    return success_response(ProductSKUSerializer(item).data, status=201)


def _sku_business_references(item):
    references = []
    for relation in item._meta.related_objects:
        accessor = relation.get_accessor_name()
        related = getattr(item, accessor)
        if relation.one_to_one:
            try:
                exists = related is not None
            except relation.related_model.DoesNotExist:
                exists = False
        else:
            exists = related.exists()
        if exists:
            references.append(relation.related_model._meta.verbose_name)
    return sorted(set(references))


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsProductMasterReadOrManage])
def product_sku_detail(request, pk):
    permission_code = "products.master.view" if request.method == "GET" else "products.master.manage"
    queryset = ProductSKU.objects.filter(tenant=request.user.tenant).select_related("spu")
    item = get_object_or_404(filter_product_skus(request.user, queryset, permission_code), pk=pk)
    if request.method == "GET":
        return success_response(ProductSKUSerializer(item).data)
    if request.method == "DELETE":
        references = _sku_business_references(item)
        if references:
            raise StateConflict("该 SKU 已存在业务关联，不能删除，请改为停用。")
        sku_id = item.pk
        old_image_path = _stored_product_image_path(item.image_url)
        item.delete()
        if old_image_path:
            default_storage.delete(old_image_path)
        AttachmentFile.objects.filter(
            tenant=request.user.tenant,
            business_type="product_sku_image",
            business_id=str(sku_id),
        ).delete()
        return success_response({"deleted": True, "id": sku_id})

    serializer = ProductSKUSerializer(
        item,
        data=request.data,
        partial=True,
        context=_serializer_context(request),
    )
    serializer.is_valid(raise_exception=True)
    old_image_url = item.image_url
    item = serializer.save()
    # A URL edit replaces an uploaded image as well; remove the old binary
    # only when it belongs to this service's tenant-scoped storage boundary.
    old_image_path = _stored_product_image_path(old_image_url)
    new_image_path = _stored_product_image_path(item.image_url)
    if old_image_path and old_image_path != new_image_path:
        default_storage.delete(old_image_path)
    return success_response(ProductSKUSerializer(item).data)


@api_view(["POST", "DELETE"])
@permission_classes([IsProductMasterReadOrManage])
def product_sku_image(request, pk):
    """Upload or remove a SKU image while preserving tenant isolation."""
    require_create_scope(request.user, "products.master.manage")
    item = get_object_or_404(ProductSKU, pk=pk, tenant=request.user.tenant)
    if request.method == "DELETE":
        old_path = _stored_product_image_path(item.image_url)
        item.image_url = None
        item.save(update_fields=["image_url", "updated_at"])
        if old_path:
            default_storage.delete(old_path)
        AttachmentFile.objects.filter(
            tenant=request.user.tenant,
            business_type="product_sku_image",
            business_id=str(item.pk),
        ).delete()
        return success_response(ProductSKUSerializer(item).data)
    uploaded = request.FILES.get("file") or request.FILES.get("image")
    try:
        item = _replace_product_image(item, uploaded, request)
    except ValueError as exc:
        return error_response(ErrorCode.VALIDATION_ERROR, str(exc), status=400)
    return success_response(ProductSKUSerializer(item).data)


def _prepare_legacy_dictionaries(item):
    standard_names = dict(STANDARD_COLORS)
    ProductColor.objects.update_or_create(
        tenant=item.tenant,
        code=item.color_code,
        defaults={
            "name": standard_names.get(item.color_code.lower(), item.color_code),
            "is_active": True,
        },
    )
    # The CSV importer reuses category instances while processing thousands of
    # rows. Reload before appending a specification so values added by earlier
    # rows are not overwritten by a stale in-memory spec_dimensions value.
    category = item.category_node
    category.refresh_from_db(fields=["spec_dimensions", "updated_at"])
    dimensions = list(category.spec_dimensions or [])
    if not dimensions:
        dimensions = [{"code": "spec", "name": "规格", "values": []}]
    first = dict(dimensions[0])
    values = list(first.get("values") or [])
    if item.specification and item.specification != "0" and item.specification not in values:
        values.append(item.specification)
        first["values"] = values
        dimensions[0] = first
        category.spec_dimensions = dimensions
        category.save(update_fields=["spec_dimensions", "updated_at"])


LEGACY_SKU_SYNC_FIELDS = (
    "product_name",
    "legacy_sku_code",
    "purchase_price",
    "unit",
    "image_url",
    "package_weight",
    "package_volume",
    "package_length_cm",
    "package_width_cm",
    "package_height_cm",
    "origin_country",
    "hs_code",
    "product_description",
)


def _sync_legacy_fields_to_sku(item, sku=None):
    """Copy editable legacy-row fields onto its existing SKU in place.

    Generated rows are an audit bridge: editing an imported row must not
    allocate another SKU or change the generated identifier.  The SKU code is
    deliberately absent from ``LEGACY_SKU_SYNC_FIELDS`` and is therefore
    always preserved.  Variant dimensions (colour/specification/category)
    remain immutable after generation and are intentionally not copied.
    """

    sku = sku or item.generated_sku
    if sku is None:
        return None
    changed = []
    for field in LEGACY_SKU_SYNC_FIELDS:
        value = getattr(item, field)
        if getattr(sku, field) != value:
            setattr(sku, field, value)
            changed.append(field)
    if changed:
        changed.append("updated_at")
        sku.save(update_fields=changed)
    return sku


@transaction.atomic
def _generate_legacy_item(item, request):
    category = item.category_node
    dimensions = category.spec_dimensions or []
    spec_values = {dimensions[0].get("code", "spec"): item.specification} if dimensions and item.specification else {}
    # Re-generating an already generated import row is an in-place update.
    # This preserves the stable SKU identifier even when a user edits the
    # legacy code/name/details before pressing Generate again.
    existing_sku = None
    if item.generated_sku_id:
        existing_sku = (
            ProductSKU.objects.select_for_update()
            .select_related("spu")
            .filter(pk=item.generated_sku_id, tenant=request.user.tenant)
            .first()
        )
    if existing_sku is not None:
        spu = existing_sku.spu
        _sync_legacy_fields_to_sku(item, existing_sku)
        item.status = ProductLegacyItem.Status.GENERATED
        item.generated_spu = spu
        item.error_message = ""
        item.save(update_fields=["status", "generated_spu", "error_message", "updated_at"])
        return existing_sku

    spu = None
    if item.legacy_spu_code:
        spu = ProductSPU.objects.filter(
            tenant=request.user.tenant,
            legacy_spu_code=item.legacy_spu_code,
            category_node=category,
        ).first()
    if not spu:
        spu_serializer = ProductSPUSerializer(
            data={
                "product_name": item.product_name,
                "category_node": category.id,
                "season_code": item.attribute_code or "0",
                "legacy_spu_code": item.legacy_spu_code,
                "product_type": "standard",
            },
            context=_serializer_context(request),
        )
        spu_serializer.is_valid(raise_exception=True)
        spu = spu_serializer.save(tenant=request.user.tenant)
    sku_serializer = ProductSKUSerializer(
        data={
            "spu": spu.id,
            "product_name": item.product_name,
            "color_code": item.color_code,
            "spec_values": spec_values,
            "legacy_sku_code": item.legacy_sku_code,
            "purchase_price": item.purchase_price,
            "unit": item.unit,
            "image_url": item.image_url,
            "package_weight": item.package_weight,
            "package_volume": item.package_volume,
            "package_length_cm": item.package_length_cm,
            "package_width_cm": item.package_width_cm,
            "package_height_cm": item.package_height_cm,
            "origin_country": item.origin_country,
            "hs_code": item.hs_code,
            "product_description": item.product_description,
        },
        context=_serializer_context(request),
    )
    sku_serializer.is_valid(raise_exception=True)
    sku = sku_serializer.save(tenant=request.user.tenant)
    item.status = ProductLegacyItem.Status.GENERATED
    item.generated_spu = spu
    item.generated_sku = sku
    item.error_message = ""
    item.save(
        update_fields=["status", "generated_spu", "generated_sku", "error_message", "updated_at"]
    )
    return sku


@api_view(["GET", "POST"])
@permission_classes([IsProductMasterReadOrManage])
def product_legacy_collection(request):
    if request.method == "GET":
        queryset = ProductLegacyItem.objects.filter(tenant=request.user.tenant).select_related(
            "category_node", "generated_spu", "generated_sku"
        )
        status_value = request.query_params.get("status", "").strip()
        if status_value:
            queryset = queryset.filter(status=status_value)
        return success_response(ProductLegacyItemSerializer(queryset, many=True).data)

    require_create_scope(request.user, "products.master.manage")
    csv_text = str(request.data.get("csv_text") or "").lstrip("\ufeff")
    if not csv_text.strip():
        return error_response(ErrorCode.VALIDATION_ERROR, "请选择包含旧商品数据的 CSV 文件。", status=400)
    reader = csv.DictReader(io.StringIO(csv_text))
    aliases = {
        "legacy_spu_code": ("旧SPU编码", "old_spu_code", "legacy_spu_code"),
        "legacy_sku_code": ("旧SKU编码", "old_sku_code", "legacy_sku_code"),
        "product_name": ("商品名称", "product_name"),
        "category_code": ("完整类目编码", "分类编码", "category_code"),
        "attribute_code": ("属性码", "attribute_code"),
        "color_code": ("颜色英文编码", "颜色", "颜色编码", "color_code"),
        "specification": ("规格", "specification"),
        "purchase_price": ("采购价格", "采购价", "purchase_price", "purchase_cost"),
        "unit": ("单位", "unit"),
        "image_url": ("商品图片", "商品图片 URL", "图片URL", "图片 URL", "图片地址", "image_url", "image"),
        "package_weight": ("重量(g)", "重量（g）", "重量", "package_weight", "weight_g"),
        "package_volume": ("体积(m³)", "体积(m3)", "体积", "package_volume", "volume_m3"),
        "package_length_cm": ("长(cm)", "长（cm）", "长度", "package_length_cm", "length_cm"),
        "package_width_cm": ("宽(cm)", "宽（cm）", "宽度", "package_width_cm", "width_cm"),
        "package_height_cm": ("高(cm)", "高（cm）", "高度", "package_height_cm", "height_cm"),
        "origin_country": ("原产国", "原产地", "origin_country", "country_of_origin"),
        "hs_code": ("HS编码", "HS码", "hs_code", "hs"),
        "product_description": ("商品描述", "描述", "product_description", "description"),
    }
    def value(row, key):
        return next((str(row.get(name) or "").strip() for name in aliases[key] if str(row.get(name) or "").strip()), "")
    fieldnames = set(reader.fieldnames or [])

    def has_column(key):
        return any(name in fieldnames for name in aliases[key])

    def optional_decimal(row, key, line_no, errors):
        raw = value(row, key)
        if not raw:
            return None, True
        try:
            parsed = Decimal(raw.replace(",", ""))
            digits = len(parsed.as_tuple().digits)
            scale = max(0, -parsed.as_tuple().exponent)
            if not parsed.is_finite() or parsed < 0 or digits > 10 or scale > 3:
                raise InvalidOperation
            return parsed, True
        except (InvalidOperation, ValueError):
            errors.append({"line": line_no, "message": f"{key} must be a non-negative number: {raw}"})
            return None, False

    created = updated = generated = 0
    errors = []
    for line_no, row in enumerate(reader, 2):
        old_sku = value(row, "legacy_sku_code")
        name = value(row, "product_name")
        if not old_sku or not name:
            errors.append({"line": line_no, "message": "旧SKU编码和商品名称不能为空"})
            continue
        attribute_code = value(row, "attribute_code")
        if attribute_code and (len(attribute_code) != 1 or not attribute_code.isdigit()):
            errors.append({"line": line_no, "message": f"属性码必须为空或1位数字：{attribute_code}"})
            continue
        raw_price = value(row, "purchase_price")
        purchase_price = None
        if raw_price:
            try:
                purchase_price = Decimal(raw_price.replace(",", ""))
                digits = len(purchase_price.as_tuple().digits)
                scale = max(0, -purchase_price.as_tuple().exponent)
                if not purchase_price.is_finite() or purchase_price < 0 or digits > 14 or scale > 4:
                    raise InvalidOperation
            except (InvalidOperation, ValueError):
                errors.append({"line": line_no, "message": f"采购价格格式无效：{raw_price}"})
                continue
        extended = {}
        invalid_extended = False
        for field in ("package_weight", "package_volume", "package_length_cm", "package_width_cm", "package_height_cm"):
            if has_column(field):
                extended[field], valid = optional_decimal(row, field, line_no, errors)
                invalid_extended = invalid_extended or not valid
        for field in ("unit", "image_url", "origin_country", "hs_code", "product_description"):
            if has_column(field):
                extended[field] = value(row, field) or None
        if invalid_extended:
            continue
        if "hs_code" in extended and extended["hs_code"]:
            hs = extended["hs_code"]
            if len(hs) < 2 or len(hs) > 20 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.\- ]*", hs):
                errors.append({"line": line_no, "message": f"HS code length/format is invalid: {hs}"})
                continue
        if "image_url" in extended and extended["image_url"]:
            image_url = extended["image_url"]
            if not ((image_url.startswith("/media/product-images/") and ".." not in image_url.split("/")) or re.match(r"^https?://[^\s]+$", image_url, flags=re.IGNORECASE)):
                errors.append({"line": line_no, "message": "image_url must be an http(s) URL or /media/ URL"})
                continue
        category = None
        category_code = value(row, "category_code")
        if category_code:
            leaves = ProductCategory.objects.filter(
                tenant=request.user.tenant, level__in=(2, 3), is_active=True
            ).select_related("parent__parent")
            leaves = list(leaves)
            category = next(
                (
                    leaf for leaf in leaves
                    if leaf.parent_id and (
                        (leaf.level == 2 and f"{leaf.parent.code}{leaf.code}" == category_code)
                        or (leaf.level == 3 and leaf.parent.parent_id and f"{leaf.parent.parent.code}{leaf.parent.code}{leaf.code}" == category_code)
                    )
                ),
                None,
            )
            if category is None:
                matches = [leaf for leaf in leaves if leaf.code == category_code][:2]
                category = matches[0] if len(matches) == 1 else None
        defaults = {"legacy_spu_code": value(row, "legacy_spu_code"), "product_name": name,
                    "category_node": category, "attribute_code": attribute_code,
                    "color_code": value(row, "color_code").lower(), "specification": value(row, "specification"),
                    "purchase_price": purchase_price,
                    "status": ProductLegacyItem.Status.PENDING, "error_message": ""}
        # Do not clear newly added fields when an old CSV omits the new column.
        defaults.update(extended)
        item, was_created = ProductLegacyItem.objects.update_or_create(
            tenant=request.user.tenant, legacy_sku_code=old_sku,
            defaults=defaults,
        )
        if was_created and not has_column("unit"):
            item.unit = "件"
            item.save(update_fields=["unit", "updated_at"])
        created += int(was_created); updated += int(not was_created)
        if category and item.color_code:
            generated_sku = (
                ProductSKU.objects.filter(pk=item.generated_sku_id, tenant=request.user.tenant).first()
                if item.generated_sku_id
                else None
            )
            if generated_sku is not None:
                _sync_legacy_fields_to_sku(item, generated_sku)
                item.status = ProductLegacyItem.Status.GENERATED
                item.error_message = ""
                item.save(update_fields=["status", "error_message", "updated_at"])
                generated += 1
                continue
            try:
                _prepare_legacy_dictionaries(item)
                _generate_legacy_item(item, request)
                generated += 1
            except Exception as exc:
                item.status = ProductLegacyItem.Status.ERROR
                item.error_message = str(exc)[:500]
                item.save(update_fields=["status", "error_message", "updated_at"])
                errors.append({"line": line_no, "message": item.error_message})
        elif category_code and not category:
            errors.append({"line": line_no, "message": f"未找到完整类目编码 {category_code}"})
    return success_response(
        {"created": created, "updated": updated, "generated": generated, "error_count": len(errors), "errors": errors},
        status=201,
    )


@api_view(["PATCH"])
@permission_classes([IsProductMasterReadOrManage])
@transaction.atomic
def product_legacy_detail(request, pk):
    require_create_scope(request.user, "products.master.manage")
    item = get_object_or_404(
        ProductLegacyItem.objects.select_for_update(),
        pk=pk,
        tenant=request.user.tenant,
    )
    was_generated = item.status == ProductLegacyItem.Status.GENERATED and bool(item.generated_sku_id)
    generated_sku = None
    if was_generated:
        generated_sku = (
            ProductSKU.objects.select_for_update()
            .filter(pk=item.generated_sku_id, tenant=request.user.tenant)
            .first()
        )
    serializer = ProductLegacyItemSerializer(item, data=request.data, partial=True, context=_serializer_context(request))
    serializer.is_valid(raise_exception=True)
    item = serializer.save()
    if generated_sku is not None:
        # Keep the generated relation/status and update the existing SKU in
        # place.  In particular, no new SKU code is allocated for a simple
        # name, legacy-code, or detail edit.
        _sync_legacy_fields_to_sku(item, generated_sku)
        item.status = ProductLegacyItem.Status.GENERATED
        item.error_message = ""
        item.save(update_fields=["status", "error_message", "updated_at"])
    else:
        item.status = ProductLegacyItem.Status.PENDING
        item.error_message = ""
        item.save(update_fields=["status", "error_message", "updated_at"])
    return success_response(ProductLegacyItemSerializer(item).data)


@api_view(["POST"])
@permission_classes([IsProductMasterReadOrManage])
def product_legacy_generate(request, pk):
    require_create_scope(request.user, "products.master.manage")
    item = get_object_or_404(ProductLegacyItem, pk=pk, tenant=request.user.tenant)
    category = item.category_node
    try:
        valid_category = bool(category and category.is_active and category_path(category))
    except DjangoValidationError:
        valid_category = False
    if not valid_category:
        return error_response(ErrorCode.VALIDATION_ERROR, "请选择启用的末级分类。", status=400)
    if not item.color_code:
        return error_response(ErrorCode.VALIDATION_ERROR, "请选择颜色。", status=400)
    try:
        _prepare_legacy_dictionaries(item)
        _generate_legacy_item(item, request)
    except Exception as exc:
        item.status = ProductLegacyItem.Status.ERROR; item.error_message = str(exc)[:500]
        item.save(update_fields=["status", "error_message", "updated_at"])
        return error_response(ErrorCode.VALIDATION_ERROR, item.error_message, status=400)
    return success_response(ProductLegacyItemSerializer(item).data)


@api_view(["GET", "POST"])
@permission_classes([IsProductBundleReadOrManage])
def product_bundle_component_collection(request):
    queryset = ProductBundleComponent.objects.filter(tenant=request.user.tenant).select_related(
        "bundle_sku__spu", "component_sku__spu"
    )
    bundle_sku_id = request.query_params.get("bundle_sku_id", "").strip()
    if bundle_sku_id.isdigit():
        queryset = queryset.filter(bundle_sku_id=int(bundle_sku_id))
    if request.method == "GET":
        visible_skus = filter_product_skus(
            request.user,
            ProductSKU.objects.filter(tenant=request.user.tenant),
            "products.bundle.view",
        )
        queryset = queryset.filter(bundle_sku_id__in=visible_skus.values("id"))
        return success_response(ProductBundleComponentSerializer(queryset, many=True).data)
    require_create_scope(request.user, "products.bundle.manage")
    serializer = ProductBundleComponentSerializer(data=request.data, context=_serializer_context(request))
    serializer.is_valid(raise_exception=True)
    item = serializer.save(tenant=request.user.tenant)
    return success_response(ProductBundleComponentSerializer(item).data, status=201)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsProductBundleReadOrManage])
def product_bundle_component_detail(request, pk):
    item = get_object_or_404(ProductBundleComponent, pk=pk, tenant=request.user.tenant)
    if request.method == "DELETE":
        item.delete()
        return success_response({"deleted": True})
    serializer = ProductBundleComponentSerializer(
        item, data=request.data, partial=True, context=_serializer_context(request)
    )
    serializer.is_valid(raise_exception=True)
    item = serializer.save()
    return success_response(ProductBundleComponentSerializer(item).data)


@api_view(["GET"])
@permission_classes([IsProductStatusViewer])
def status_recommendation_collection(request):
    queryset = ProductStatusRecommendation.objects.filter(tenant=request.user.tenant).select_related(
        "spu",
        "sku",
        "source_snapshot",
        "confirmed_by",
    )
    return success_response(ProductStatusRecommendationSerializer(queryset, many=True).data)


@api_view(["GET"])
@permission_classes([IsProductStatusViewer])
def status_recommendation_detail(request, pk):
    recommendation = get_object_or_404(ProductStatusRecommendation, pk=pk, tenant=request.user.tenant)
    return success_response(ProductStatusRecommendationSerializer(recommendation).data)


@api_view(["POST"])
@permission_classes([IsProductStatusConfirmer])
def confirm_status_recommendation(request, pk):
    recommendation = get_object_or_404(ProductStatusRecommendation, pk=pk, tenant=request.user.tenant)
    transition = confirm_recommendation(recommendation, request.user, reason=request.data.get("reason", ""))
    return success_response(ProductStatusTransitionSerializer(transition).data)


@api_view(["POST"])
@permission_classes([IsProductStatusConfirmer])
def reject_status_recommendation(request, pk):
    recommendation = get_object_or_404(ProductStatusRecommendation, pk=pk, tenant=request.user.tenant)
    reject_recommendation(recommendation, request.user, reason=request.data.get("reason", ""))
    recommendation.refresh_from_db()
    return success_response(ProductStatusRecommendationSerializer(recommendation).data)


@api_view(["GET"])
@permission_classes([IsProductStatusViewer])
def status_transition_collection(request):
    queryset = ProductStatusTransition.objects.filter(tenant=request.user.tenant).select_related(
        "spu",
        "sku",
        "recommendation",
        "approved_by",
    )
    return success_response(ProductStatusTransitionSerializer(queryset, many=True).data)


@api_view(["POST"])
@permission_classes([IsProductStatusEvaluator])
def evaluate_mock_status_view(request):
    spu_id = request.data.get("spu")
    sku_id = request.data.get("sku")
    recommendation = evaluate_mock_status(
        tenant=request.user.tenant,
        user=request.user,
        spu_id=spu_id,
        sku_id=sku_id,
        metrics=request.data.get("metrics") or {},
    )
    return success_response(ProductStatusRecommendationSerializer(recommendation).data, status=201)
