from django.core.paginator import Paginator
from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes

from apps.common.query import pagination_query
from apps.common.responses import success_response
from apps.permissions.ui_p5_scopes import filter_product_skus

from .models import ProductLegacyItem, ProductSKU
from .serializers import ProductDetailRowSerializer
from .permissions import IsProductMasterReadOrManage


def _search(queryset, value, fields):
    if not value:
        return queryset
    condition = Q(pk__in=[])
    for field in fields:
        condition |= Q(**{f"{field}__icontains": value})
    return queryset.filter(condition)


def _page_url(request, number, page_size):
    if number is None:
        return None
    params = request.query_params.copy()
    params["page"] = number
    params["page_size"] = page_size
    return request.build_absolute_uri(f"{request.path}?{params.urlencode()}")


@api_view(["GET"])
@permission_classes([IsProductMasterReadOrManage])
def product_detail_collection(request):
    """Tenant-scoped, paginated old/new SPU-SKU relation rows."""

    tenant = request.user.tenant
    search = request.query_params.get("search", "").strip()
    legacy = ProductLegacyItem.objects.filter(tenant=tenant).exclude(
        status=ProductLegacyItem.Status.GENERATED,
    ).select_related("category_node")
    legacy = _search(
        legacy,
        "" if search.casefold() in {"待转换", "pending", "生成失败", "error"} else search,
        ("legacy_spu_code", "legacy_sku_code", "product_name", "category_node__name", "color_code", "specification", "purchase_price", "status"),
    )
    skus = ProductSKU.objects.filter(tenant=tenant).select_related("spu", "spu__category_node")
    skus = filter_product_skus(request.user, skus, "products.master.view")
    skus = _search(
        skus,
        "" if search.casefold() in {"已生成", "generated"} else search,
        ("legacy_sku_code", "sku_code", "product_name", "spu__legacy_spu_code", "spu__spu_code", "spu__product_name", "spu__category", "spu__category_node__name", "color_code", "specification", "purchase_price"),
    )
    labels = {
        ProductLegacyItem.Status.PENDING: "待转换",
        ProductLegacyItem.Status.GENERATED: "已生成",
        ProductLegacyItem.Status.ERROR: "生成失败",
    }
    rows = [
        {
            "id": item.id, "row_type": "legacy", "legacy_spu_code": item.legacy_spu_code,
            "legacy_sku_code": item.legacy_sku_code, "spu_code": "", "sku_code": "",
            "product_name": item.product_name, "category_node": item.category_node_id,
            "category_name": item.category_node.name if item.category_node else "",
            "color_code": item.color_code, "specification": item.specification,
            "purchase_price": item.purchase_price, "attribute_code": item.attribute_code,
            "status": item.status, "status_name": labels.get(item.status, item.status),
            "error_message": item.error_message,
        }
        for item in legacy
    ]
    rows.extend(
        {
            "id": item.id, "row_type": "sku", "legacy_spu_code": item.spu.legacy_spu_code,
            "legacy_sku_code": item.legacy_sku_code, "spu_code": item.spu.spu_code,
            "sku_code": item.sku_code, "product_name": item.product_name or item.spu.product_name,
            "category_node": item.spu.category_node_id,
            "category_name": item.spu.category_node.name if item.spu.category_node else item.spu.category,
            "color_code": item.color_code, "specification": item.specification,
            "purchase_price": item.purchase_price, "attribute_code": item.spu.season_code,
            "status": ProductLegacyItem.Status.GENERATED, "status_name": labels[ProductLegacyItem.Status.GENERATED],
            "error_message": "",
        }
        for item in skus
    )
    if search:
        needle = search.casefold()
        rows = [row for row in rows if any(needle in str(row.get(field) or "").casefold() for field in (
            "legacy_spu_code", "legacy_sku_code", "spu_code", "sku_code", "product_name",
            "category_name", "color_code", "specification", "purchase_price", "status", "status_name",
        ))]
    page, page_size = pagination_query(request)
    paginator = Paginator(rows, page_size)
    page_obj = paginator.get_page(page)
    return success_response({
        "count": paginator.count,
        "next": _page_url(request, page_obj.next_page_number(), page_size) if page_obj.has_next() else None,
        "previous": _page_url(request, page_obj.previous_page_number(), page_size) if page_obj.has_previous() else None,
        "results": ProductDetailRowSerializer(page_obj.object_list, many=True).data,
    })
