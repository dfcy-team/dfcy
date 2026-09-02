import csv
import io
import os
import uuid
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes

from apps.common.query import pagination_query
from apps.common.error_codes import ErrorCode
from apps.common.responses import error_response, paginated_data, success_response
from apps.files.models import AttachmentFile
from apps.permissions.ui_p5_scopes import (
    filter_product_research,
    filter_product_skus,
    filter_product_spus,
    require_create_scope,
)

from .coding_services import SEASONS, allocate_legacy_sku_code, category_path
from .name_normalization import consensus_spu_product_name
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
    ProductDetailRowSerializer,
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
    require_create_scope(request.user, "products.master.manage")
    with transaction.atomic():
        existing = list(ProductAttribute.objects.select_for_update().filter(tenant=request.user.tenant).values_list("code", flat=True))
        next_code = next((str(number) for number in range(1, 10) if str(number) not in existing), None)
        if next_code is None:
            return error_response(ErrorCode.STATE_CONFLICT, "һλ���Ա��������꣨1-9����", status=409)
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
            return error_response(ErrorCode.STATE_CONFLICT, "�����ѱ���Ʒʹ�ã�����ɾ����", status=409)
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
    require_create_scope(request.user, "products.master.manage")
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
            return error_response(ErrorCode.STATE_CONFLICT, "����ɾ���¼����ࡣ", status=409)
        if item.products.exists():
            return error_response(ErrorCode.STATE_CONFLICT, "�����ѱ���Ʒʹ�ã�����ɾ����", status=409)
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
    item = get_object_or_404(ProductCategory, pk=pk, tenant=request.user.tenant, level=ProductCategory.Level.L3)
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
    require_create_scope(request.user, "products.master.manage")
    serializer = ProductColorSerializer(data=request.data, context=_serializer_context(request))
    serializer.is_valid(raise_exception=True)
    item = serializer.save(tenant=request.user.tenant)
    return success_response(ProductColorSerializer(item).data, status=201)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsProductColorReadOrManage])
def product_color_detail(request, pk):
    item = get_object_or_404(ProductColor, pk=pk, tenant=request.user.tenant)
    if request.method == "DELETE":
        if ProductSKU.objects.filter(tenant=request.user.tenant, color_code=item.code).exists():
            return error_response(ErrorCode.STATE_CONFLICT, "��ɫ�ѱ� SKU ʹ�ã�����ɾ����", status=409)
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
        category_id = request.query_params.get("category_node", "").strip()
        if category_id.isdigit():
            selected = get_object_or_404(ProductCategory, pk=int(category_id), tenant=request.user.tenant)
            category_ids = [selected.id]
            frontier = [selected.id]
            while frontier:
                frontier = list(ProductCategory.objects.filter(tenant=request.user.tenant, parent_id__in=frontier).values_list("id", flat=True))
                category_ids.extend(frontier)
            queryset = queryset.filter(category_node_id__in=category_ids)
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
            return error_response(ErrorCode.STATE_CONFLICT, "��Ʒ�Ѵ��� SKU�����ȴ��� SKU ��ҵ�����ݡ�", status=409)
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
    queryset = ProductSPU.objects.filter(tenant=request.user.tenant).prefetch_related("skus")
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
        if search:
            queryset = queryset.filter(sku_code__icontains=search)
        if spu_id.isdigit():
            queryset = queryset.filter(spu_id=int(spu_id))
        page, page_size = pagination_query(request)
        return success_response(paginated_data(request, queryset, ProductSKUSerializer, page=page, page_size=page_size))

    require_create_scope(request.user, "products.master.manage")
    serializer = ProductSKUSerializer(data=request.data, context=_serializer_context(request))
    serializer.is_valid(raise_exception=True)
    item = serializer.save(tenant=request.user.tenant)
    return success_response(ProductSKUSerializer(item).data, status=201)


@api_view(["GET", "PATCH"])
@permission_classes([IsProductMasterReadOrManage])
def product_sku_detail(request, pk):
    permission_code = "products.master.view" if request.method == "GET" else "products.master.manage"
    queryset = ProductSKU.objects.filter(tenant=request.user.tenant).select_related("spu")
    item = get_object_or_404(filter_product_skus(request.user, queryset, permission_code), pk=pk)
    if request.method == "GET":
        return success_response(ProductSKUSerializer(item).data)

    serializer = ProductSKUSerializer(
        item,
        data=request.data,
        partial=True,
        context=_serializer_context(request),
    )
    serializer.is_valid(raise_exception=True)
    item = serializer.save()
    return success_response(ProductSKUSerializer(item).data)


def _product_detail_search_filter(queryset, search, fields):
    """Apply one global search term to a product-detail queryset."""

    if not search:
        return queryset
    condition = Q(pk__in=[])
    for field in fields:
        condition |= Q(**{f"{field}__icontains": search})
    return queryset.filter(condition)


def _product_detail_page_url(request, page, page_size):
    if page is None:
        return None
    params = request.query_params.copy()
    params["page"] = page
    params["page_size"] = page_size
    return request.build_absolute_uri(f"{request.path}?{params.urlencode()}")


@api_view(["GET"])
@permission_classes([IsProductMasterReadOrManage])
def product_detail_collection(request):
    """Return the flattened 商品明细数据 read model.

    Legacy import rows that have not generated a SKU are shown alongside
    generated SKU rows.  Generated legacy staging rows are intentionally
    omitted because their generated SKU is already represented by the second
    row, preventing duplicate entries in the table.
    """

    search = request.query_params.get("search", "").strip()
    tenant = request.user.tenant
    legacy_queryset = ProductLegacyItem.objects.filter(
        tenant=tenant,
    ).exclude(
        status=ProductLegacyItem.Status.GENERATED,
    ).select_related("category_node")
    legacy_queryset = _product_detail_search_filter(
        legacy_queryset,
        "" if search.casefold() in {"待转换", "pending", "生成失败", "error"} else search,
        (
            "legacy_spu_code",
            "legacy_sku_code",
            "product_name",
            "category_node__name",
            "color_code",
            "specification",
            "purchase_price",
            "status",
        ),
    )

    sku_queryset = ProductSKU.objects.filter(tenant=tenant).select_related(
        "spu",
        "spu__category_node",
    )
    sku_queryset = filter_product_skus(request.user, sku_queryset, "products.master.view")
    sku_queryset = _product_detail_search_filter(
        sku_queryset,
        "" if search.casefold() in {"已生成", "generated"} else search,
        (
            "legacy_sku_code",
            "sku_code",
            "product_name",
            "spu__legacy_spu_code",
            "spu__spu_code",
            "spu__product_name",
            "spu__category",
            "spu__category_node__name",
            "color_code",
            "specification",
            "purchase_price",
        ),
    )

    status_labels = {
        ProductLegacyItem.Status.PENDING: "待转换",
        ProductLegacyItem.Status.GENERATED: "已生成",
        ProductLegacyItem.Status.ERROR: "生成失败",
    }
    rows = []
    for item in legacy_queryset:
        rows.append(
            {
                "id": item.id,
                "row_type": "legacy",
                "legacy_spu_code": item.legacy_spu_code,
                "legacy_sku_code": item.legacy_sku_code,
                "spu_code": "",
                "sku_code": "",
                "product_name": item.product_name,
                "category_node": item.category_node_id,
                "category_name": item.category_node.name if item.category_node else "",
                "color_code": item.color_code,
                "specification": item.specification,
                "purchase_price": item.purchase_price,
                "attribute_code": item.attribute_code,
                "status": item.status,
                "status_name": status_labels.get(item.status, item.status),
                "error_message": item.error_message,
            }
        )
    for item in sku_queryset:
        spu = item.spu
        rows.append(
            {
                "id": item.id,
                "row_type": "sku",
                "legacy_spu_code": spu.legacy_spu_code,
                "legacy_sku_code": item.legacy_sku_code,
                "spu_code": spu.spu_code,
                "sku_code": item.sku_code,
                "product_name": item.product_name or spu.product_name,
                "category_node": spu.category_node_id,
                "category_name": spu.category_node.name if spu.category_node else spu.category,
                "color_code": item.color_code,
                "specification": item.specification,
                "purchase_price": item.purchase_price,
                "attribute_code": spu.season_code,
                "status": ProductLegacyItem.Status.GENERATED,
                "status_name": status_labels[ProductLegacyItem.Status.GENERATED],
                "error_message": "",
            }
        )

    if search:
        needle = search.casefold()
        rows = [
            row
            for row in rows
            if any(
                needle in str(row.get(field) or "").casefold()
                for field in (
                    "legacy_spu_code",
                    "legacy_sku_code",
                    "spu_code",
                    "sku_code",
                    "product_name",
                    "category_name",
                    "color_code",
                    "specification",
                    "purchase_price",
                    "status",
                    "status_name",
                )
            )
        ]

    page, page_size = pagination_query(request)
    paginator = Paginator(rows, page_size)
    if page > paginator.num_pages:
        return error_response(ErrorCode.NOT_FOUND, "Requested page does not exist.", status=404)
    page_obj = paginator.page(page)
    payload = {
        "count": paginator.count,
        "next": _product_detail_page_url(request, page_obj.next_page_number(), page_size)
        if page_obj.has_next()
        else None,
        "previous": _product_detail_page_url(request, page_obj.previous_page_number(), page_size)
        if page_obj.has_previous()
        else None,
        "results": ProductDetailRowSerializer(page_obj.object_list, many=True).data,
    }
    return success_response(payload)


@api_view(["POST", "DELETE"])
@permission_classes([IsProductMasterReadOrManage])
def product_sku_image(request, pk):
    """Upload or clear one tenant-scoped SKU image.

    The endpoint accepts only PNG/JPEG magic bytes and records the attachment
    metadata alongside the SKU.  It deliberately does not expose an arbitrary
    client-provided path.
    """
    permission_code = "products.master.view" if request.method == "GET" else "products.master.manage"
    queryset = filter_product_skus(
        request.user,
        ProductSKU.objects.filter(tenant=request.user.tenant),
        permission_code,
    )
    item = get_object_or_404(queryset, pk=pk)
    if request.method == "DELETE":
        item.image_url = None
        item.save(update_fields=["image_url", "updated_at"])
        return success_response({"deleted": True})
    upload = request.FILES.get("file")
    if upload is None:
        return error_response(ErrorCode.VALIDATION_ERROR, "Image file is required.", status=400)
    name = os.path.basename(upload.name or "")
    extension = os.path.splitext(name)[1].lower()
    payload = upload.read()
    is_png = extension == ".png" and payload.startswith(b"\x89PNG\r\n\x1a\n")
    is_jpeg = extension in {".jpg", ".jpeg"} and payload.startswith(b"\xff\xd8\xff")
    if not (is_png or is_jpeg):
        return error_response(ErrorCode.VALIDATION_ERROR, "Only valid PNG/JPEG images are accepted.", status=400)
    key = f"product-images/tenant-{request.user.tenant_id}/sku-{item.id}-{uuid.uuid4().hex}{extension}"
    saved_path = default_storage.save(key, ContentFile(payload))
    relative_url = f"/media/{saved_path.replace(os.sep, '/') }"
    item.image_url = relative_url
    item.save(update_fields=["image_url", "updated_at"])
    AttachmentFile.objects.create(
        tenant=request.user.tenant,
        file_name=name,
        file_path=saved_path,
        file_type=upload.content_type or ("image/png" if is_png else "image/jpeg"),
        file_size=len(payload),
        uploaded_by=request.user,
        business_type="product_sku_image",
        business_id=str(item.id),
        is_private=False,
    )
    return success_response(ProductSKUSerializer(item).data)


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
    # ``csv_text`` is the documented API field; ``csv`` remains accepted for
    # older clients (the original 商品明细 page used that shorter key).
    csv_text = str(request.data.get("csv_text") or request.data.get("csv") or "").lstrip("\ufeff")
    if not csv_text.strip():
        return error_response(ErrorCode.VALIDATION_ERROR, "��ѡ���������Ʒ���ݵ� CSV �ļ���", status=400)
    reader = csv.DictReader(io.StringIO(csv_text))
    aliases = {
        "legacy_spu_code": ("旧SPU编码", "旧 SPU 编码", "��SPU����", "old_spu_code", "legacy_spu_code"),
        "legacy_sku_code": ("旧SKU编码", "旧 SKU 编码", "��SKU����", "old_sku_code", "legacy_sku_code"),
        "product_name": ("商品名称", "��Ʒ����", "product_name"),
        "category_code": ("分类编码", "�������", "category_code"),
        "attribute_code": ("属性码", "属性代码", "������", "attribute_code"),
        "color_code": ("颜色", "颜色编码", "��ɫ", "��ɫ����", "color_code"),
        "specification": ("规格", "���", "specification"),
        "purchase_price": ("采购价格", "采购价", "purchase_price"),
    }
    def value(row, key):
        return next((str(row.get(name) or "").strip() for name in aliases[key] if str(row.get(name) or "").strip()), "")
    created = updated = 0
    errors = []
    for line_no, row in enumerate(reader, 2):
        old_sku = value(row, "legacy_sku_code")
        name = value(row, "product_name")
        if not old_sku or not name:
            errors.append({"line": line_no, "message": "��SKU�������Ʒ���Ʋ���Ϊ��"})
            continue
        purchase_price = value(row, "purchase_price")
        if purchase_price:
            try:
                purchase_price = Decimal(purchase_price)
            except (InvalidOperation, ValueError):
                errors.append({"line": line_no, "message": "采购价格必须是有效数字"})
                continue
        category = None
        category_code = value(row, "category_code")
        if category_code:
            category = ProductCategory.objects.filter(tenant=request.user.tenant, level=3, code=category_code).first()
        _, was_created = ProductLegacyItem.objects.update_or_create(
            tenant=request.user.tenant, legacy_sku_code=old_sku,
            defaults={"legacy_spu_code": value(row, "legacy_spu_code"), "product_name": name,
                      "category_node": category, "attribute_code": value(row, "attribute_code") or "0",
                      "color_code": value(row, "color_code"), "specification": value(row, "specification"),
                      "purchase_price": purchase_price or None,
                      "status": ProductLegacyItem.Status.PENDING, "error_message": ""},
        )
        created += int(was_created); updated += int(not was_created)
    return success_response({"created": created, "updated": updated, "errors": errors}, status=201)


def _synchronize_legacy_spu_name(spu, item):
    """Converge the generated SPU name without mutating legacy/SKU names."""
    if not item.legacy_spu_code:
        rows = [item]
    else:
        rows = list(
            ProductLegacyItem.objects.filter(
                tenant_id=spu.tenant_id,
                legacy_spu_code=item.legacy_spu_code,
                category_node_id=spu.category_node_id,
            ).order_by("id")
        )
    color_names = {
        str(code): name
        for code, name in ProductColor.objects.filter(
            tenant_id=spu.tenant_id,
            is_active=True,
        ).values_list("code", "name")
        if code and name
    }
    desired, _evidence = consensus_spu_product_name(
        rows,
        reference_name=spu.product_name,
        color_name_by_code=color_names,
    )
    if desired and desired != spu.product_name:
        spu.product_name = desired
        spu.save(update_fields=["product_name", "updated_at"])
    return desired


@api_view(["PATCH"])
@permission_classes([IsProductMasterReadOrManage])
def product_legacy_detail(request, pk):
    require_create_scope(request.user, "products.master.manage")
    item = get_object_or_404(ProductLegacyItem, pk=pk, tenant=request.user.tenant)
    was_generated = item.status == ProductLegacyItem.Status.GENERATED and bool(item.generated_sku_id)
    generated_sku = item.generated_sku if was_generated else None
    serializer = ProductLegacyItemSerializer(item, data=request.data, partial=True, context=_serializer_context(request))
    serializer.is_valid(raise_exception=True)
    item = serializer.save(
        status=ProductLegacyItem.Status.GENERATED if was_generated else ProductLegacyItem.Status.PENDING,
        error_message="",
    )
    if was_generated and generated_sku is not None:
        # Editing a generated legacy row updates the existing SKU in place;
        # it never allocates a replacement code or reopens the generation.
        copy_fields = (
            "legacy_sku_code",
            "product_name",
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
        for field in copy_fields:
            setattr(generated_sku, field, getattr(item, field))
        generated_sku.save(update_fields=[*copy_fields, "updated_at"])
    return success_response(ProductLegacyItemSerializer(item).data)


@api_view(["POST"])
@permission_classes([IsProductMasterReadOrManage])
def product_legacy_generate(request, pk):
    require_create_scope(request.user, "products.master.manage")
    item = get_object_or_404(ProductLegacyItem, pk=pk, tenant=request.user.tenant)
    category = item.category_node
    if not category or category.level not in {ProductCategory.Level.L2, ProductCategory.Level.L3} or not category.is_active:
        return error_response(ErrorCode.VALIDATION_ERROR, "��ѡ�����õ�ĩ�����ࡣ", status=400)
    if not item.color_code:
        return error_response(ErrorCode.VALIDATION_ERROR, "��ѡ����ɫ��", status=400)
    dimensions = category.spec_dimensions or [{"code": "spec"}]
    spec_values = {dimensions[0].get("code", "spec"): item.specification or "0"}
    try:
        with transaction.atomic():
            spu = None
            if item.legacy_spu_code:
                spu = ProductSPU.objects.filter(tenant=request.user.tenant, legacy_spu_code=item.legacy_spu_code).first()
            if not spu:
                if category.level == ProductCategory.Level.L3:
                    season_code = item.attribute_code if item.attribute_code in {entry["code"] for entry in SEASONS} else "1"
                    spu_serializer = ProductSPUSerializer(
                        data={
                            "product_name": item.product_name,
                            "category_node": category.id,
                            "season_code": season_code,
                            "legacy_spu_code": item.legacy_spu_code,
                            "product_type": "standard",
                        },
                        context=_serializer_context(request),
                    )
                    spu_serializer.is_valid(raise_exception=True)
                    spu = spu_serializer.save(tenant=request.user.tenant)
                else:
                    # Older imports often stop at an L2 category.  Preserve
                    # those rows rather than rejecting the whole batch; the
                    # generated identifiers are explicitly marked legacy.
                    parent = category.parent
                    spu = ProductSPU.objects.create(
                        tenant=request.user.tenant,
                        spu_code=f"LEGACY-{item.id}",
                        legacy_spu_code=item.legacy_spu_code,
                        product_name=item.product_name,
                        category=category.name,
                        category_node=category,
                        product_type=ProductSPU.ProductType.STANDARD,
                        season_code=item.attribute_code or "0",
                        l1_code=parent.parent.code if parent and parent.parent_id else "",
                        l2_code=parent.code if parent else category.code,
                        l3_code="",
                    )
            if item.generated_sku_id and item.generated_sku and item.generated_sku.spu_id == spu.id:
                sku = item.generated_sku
            elif item.legacy_sku_code:
                # A previous attempt may have persisted the SKU before the
                # staging-row link was written (for example after a manual
                # repair). Reattach that SKU for the same SPU/legacy code
                # instead of allocating a second variant.
                sku = (
                    ProductSKU.objects.select_for_update()
                    .filter(
                        tenant=request.user.tenant,
                        spu=spu,
                        legacy_sku_code=item.legacy_sku_code,
                    )
                    .first()
                )
                if sku is None and category.level == ProductCategory.Level.L3:
                    sku_serializer = ProductSKUSerializer(
                        data={
                            "spu": spu.id,
                            "color_code": item.color_code,
                            "spec_values": spec_values,
                            "legacy_sku_code": item.legacy_sku_code,
                        },
                        context=_serializer_context(request),
                    )
                    sku_serializer.is_valid(raise_exception=True)
                    sku = sku_serializer.save(tenant=request.user.tenant)
                elif sku is None:
                    base_code = f"{spu.spu_code}-{item.color_code}-{item.specification or '0'}"
                    sku = ProductSKU.objects.create(
                        tenant=request.user.tenant,
                        spu=spu,
                        sku_code=allocate_legacy_sku_code(
                            tenant=request.user.tenant,
                            base_code=base_code,
                            legacy_sku_code=item.legacy_sku_code,
                        ),
                        legacy_sku_code=item.legacy_sku_code,
                        product_name=item.product_name,
                        color_code=item.color_code,
                        specification=item.specification or "",
                        size=item.specification or "",
                    )
            elif category.level == ProductCategory.Level.L3:
                sku_serializer = ProductSKUSerializer(
                    data={
                        "spu": spu.id,
                        "color_code": item.color_code,
                        "spec_values": spec_values,
                        "legacy_sku_code": item.legacy_sku_code,
                    },
                    context=_serializer_context(request),
                )
                sku_serializer.is_valid(raise_exception=True)
                sku = sku_serializer.save(tenant=request.user.tenant)
            else:
                # ProductLegacyItem.legacy_sku_code is required, so this
                # branch is retained only as a defensive fallback.
                base_code = f"{spu.spu_code}-{item.color_code}-{item.specification or '0'}"
                sku = ProductSKU.objects.create(
                    tenant=request.user.tenant,
                    spu=spu,
                    sku_code=allocate_legacy_sku_code(
                        tenant=request.user.tenant,
                        base_code=base_code,
                        legacy_sku_code=item.legacy_sku_code,
                    ),
                    legacy_sku_code=item.legacy_sku_code,
                    product_name=item.product_name,
                    color_code=item.color_code,
                    specification=item.specification or "",
                    size=item.specification or "",
                )
            copy_fields = (
                "product_name",
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
            for field in copy_fields:
                setattr(sku, field, getattr(item, field))
            sku.legacy_sku_code = item.legacy_sku_code
            sku.save(update_fields=[*copy_fields, "legacy_sku_code", "updated_at"])
            item.status = ProductLegacyItem.Status.GENERATED; item.generated_spu = spu; item.generated_sku = sku; item.error_message = ""
            item.save(update_fields=["status", "generated_spu", "generated_sku", "error_message", "updated_at"])
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
    require_create_scope(request.user, "products.master.manage")
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
