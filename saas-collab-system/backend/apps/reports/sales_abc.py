"""Read-only SKU demand ranking for replenishment."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.db.models import Exists, OuterRef, Q, Subquery, Sum
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError

from apps.commerce.models import RefundReturnItem
from apps.masterdata.models import StoreMaster
from apps.products.models import ProductSKU
from apps.sales_management.scopes import filter_sales_queryset
from apps.common.responses import success_response
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from apps.sales_management.aftersales import READ, visible_cases
from apps.sales_management.aftersales_models import ReturnAllocation

from .datasets import DATASETS, normalize_config, selected_permission, source_queryset
from .permissions import IsDatasetReportViewer
from .scopes import report_scope


def scoped_facts(user, dataset, filters, **kwargs):
    config = normalize_config({"dataset": dataset, "filters": filters})
    permission = selected_permission(user, DATASETS[dataset])
    request = SimpleNamespace(user=user, query_params=filters)
    return source_queryset(request, config, permission, **kwargs)


def authorized_stores(user):
    stores = StoreMaster.objects.filter(tenant=user.tenant)
    for dataset in ("sales_skus", "refunds"):
        permission = selected_permission(user, DATASETS[dataset])
        stores = filter_sales_queryset(
            user, permission, stores,
            {"store_ids": "pk", "platforms": "platform__platform_type", "regions": "country_code"},
        )
    explicit, ids = report_scope(user, "reports.sales", "store_ids", "sales_details")
    if explicit and ids is not None:
        stores = stores.filter(pk__in=ids)
    return stores


@api_view(["GET"])
@permission_classes([IsDatasetReportViewer])
def sales_abc_options(request):
    rows = list(authorized_stores(request.user).order_by("name", "pk").values(
        "pk", "name", "code", "country_code", "platform__platform_type",
    ))
    return success_response({
        "options": [{
            "value": str(row["pk"]),
            "label": " · ".join(filter(None, (row["name"], row["code"], row["country_code"]))),
            "country": row["country_code"],
            "platform": row["platform__platform_type"],
        } for row in rows],
        "countries": sorted({row["country_code"] for row in rows if row["country_code"]}),
        "platforms": sorted({row["platform__platform_type"] for row in rows if row["platform__platform_type"]}),
    })


def rank_rows(rows):
    rows.sort(key=lambda row: (-row["units"], row["sku"]))
    total = sum(row["units"] for row in rows)
    cumulative = 0
    for row in rows:
        units = row["units"]
        row["abc"] = None
        row["cumulative_percent"] = None
        if units > 0:
            row["abc"] = "A" if cumulative * 100 < total * 80 else "B" if cumulative * 100 < total * 95 else "C"
            cumulative += units
            row["cumulative_percent"] = str((Decimal(cumulative) * 100 / total).quantize(Decimal("0.01")))
    return total


def product_rows(user, rows):
    products = {
        product.sku_code: product
        for product in ProductSKU.objects.filter(
            tenant=user.tenant, spu__tenant=user.tenant,
            sku_code__in=[row["sku"] for row in rows],
        ).select_related("spu")
    }
    parents = {}
    metrics = ("units", "ordered_units", "cancelled_units", "refund_requested_units",
               "refund_completed_units", "return_received_units")
    for row in rows:
        product = products.get(row["sku"])
        if product is None:
            continue
        row.update(
            legacy_sku=product.legacy_sku_code,
            spu=product.spu.spu_code,
            legacy_spu=product.spu.legacy_spu_code,
            product_name=product.product_name or product.spu.product_name,
            image_url=product.image_url or "",
        )
        parent = parents.setdefault(product.spu_id, {
            "sku": product.spu.spu_code,
            "spu": product.spu.spu_code,
            "legacy_spu": product.spu.legacy_spu_code,
            "product_name": product.spu.product_name,
            "image_url": "", "children": [],
            **dict.fromkeys(metrics, 0),
        })
        parent["children"].append(row)
        if not parent["image_url"] and row["image_url"]:
            parent["image_url"] = row["image_url"]
        for metric in metrics:
            parent[metric] = None if row[metric] is None else parent[metric] + row[metric]
    result = list(parents.values())
    rank_rows(result)
    return result


def compute_sales_abc(request, filters, *, mode="non_cancelled", export_scope=None):
    sku_search = str(filters.get("sku", "")).strip()
    if len(sku_search) > 160:
        raise ValidationError("SKU 筛选最多支持 160 个字符。")
    filters = {key: str(filters.get(key, "")).strip() for key in ("store_id", "date_from", "date_to", "currency")}
    country = str(request.query_params.get("country", "") if hasattr(request, "query_params") else "").strip().upper()
    platform = str(request.query_params.get("platform", "") if hasattr(request, "query_params") else "").strip().lower()
    if not all(filters[key] for key in ("date_from", "date_to")) or not any((filters["store_id"], country, platform)):
        raise ValidationError("请选择国家、平台或店铺，并设置完整日期范围。")
    stores = authorized_stores(request.user)
    if country:
        stores = stores.filter(country_code=country)
    if platform:
        stores = stores.filter(platform__platform_type=platform)
    if filters["store_id"]:
        stores = stores.filter(pk=filters["store_id"]) if filters["store_id"].isascii() and filters["store_id"].isdigit() else stores.none()

    if mode not in {"non_cancelled", "fulfilled"}:
        raise ValidationError("请选择有效的需求口径。")
    normalize_config({"dataset": "sales_skus", "filters": filters})
    if (date.fromisoformat(filters["date_to"]) - date.fromisoformat(filters["date_from"])).days >= 92:
        raise ValidationError("单次最多查询 92 天。")

    # Currency applies to the item; order and item currencies are separate facts.
    currency = filters.pop("currency").upper()
    lines = scoped_facts(request.user, "sales_skus", filters, include_cancelled=True)
    if sku_search:
        from apps.products.sku_aliases import filter_sku_codes
        lines = filter_sku_codes(lines, tenant_id=request.user.tenant_id, code=sku_search, mode="", store_field="sales_order__store_id")
    if export_scope:
        lines = filter_sales_queryset(request.user, export_scope, lines,
            {"store_ids": "sales_order__store_id", "platforms": "sales_order__platform__platform_type", "regions": "sales_order__region"})
    lines = lines.filter(sales_order__store_id__in=Subquery(stores.values("pk")))
    if currency:
        lines = lines.filter(currency=currency)
    cancelled = Q(sales_order__normalized_status="cancelled")
    included = Q(sales_order__normalized_status__in=["fulfilled", "completed"]) if mode == "fulfilled" else ~cancelled
    grouped = list(lines.values("internal_sku__sku_code").annotate(
        ordered_units=Sum("quantity", default=0),
        units=Sum("quantity", filter=included, default=0),
        cancelled_units=Sum("quantity", filter=cancelled, default=0),
    ))
    refunds = scoped_facts(request.user, "refunds", {"store_id": filters["store_id"]})
    if export_scope:
        refunds = filter_sales_queryset(request.user, export_scope, refunds,
            {"store_ids": "store_id", "platforms": "platform__platform_type", "regions": "store__country_code"})
    refunds = refunds.filter(sales_order_id__in=Subquery(lines.values("sales_order_id")))
    if currency:
        refunds = refunds.filter(currency=currency)
    refund_lines = RefundReturnItem.objects.filter(refund_return_id__in=Subquery(refunds.values("pk"))).exclude(
        refund_return__normalized_status__in=["cancelled", "rejected"],
    )
    linked_refunds = refund_lines.filter(sales_order_item_id__in=Subquery(lines.values("pk")))
    refund_stats = {
        row["sales_order_item__internal_sku__sku_code"]: row
        for row in linked_refunds.order_by().values("sales_order_item__internal_sku__sku_code").annotate(
            refund_requested_units=Sum("quantity", default=0),
            refund_completed_units=Sum("quantity", filter=Q(refund_return__normalized_status="completed"), default=0),
        )
    }
    unlinked = refund_lines.filter(sales_order_item__isnull=True).aggregate(units=Sum("quantity", default=0))
    receipt_access = bool(check_user_permission(request.user, READ) and get_permission_data_scopes(request.user, READ))
    receipts = {}
    if receipt_access:
        cases = visible_cases(request.user).filter(store_id__in=Subquery(stores.values("pk"))).filter(
            Q(refund_id__in=Subquery(refunds.values("pk")))
            | Q(refund_id__isnull=True, order_id__in=Subquery(lines.values("sales_order_id"))),
        )
        receipt_lines = lines.filter(internal_sku__sku_code=OuterRef("case_sku")).filter(
            Q(sales_order_id=OuterRef("case__order_id"))
            | Q(sales_order_id=OuterRef("case__refund__sales_order_id")),
        )
        receipts = dict(ReturnAllocation.objects.filter(
            case_id__in=Subquery(cases.order_by().values("pk")),
            line__receipt__tenant_id=request.user.tenant_id,
            line__receipt__received_at__isnull=False,
        ).filter(Exists(receipt_lines)).order_by().values("case_sku").annotate(units=Sum("quantity")).values_list("case_sku", "units"))

    rows = []
    unmapped_units = 0
    for row in grouped:
        sku = row.pop("internal_sku__sku_code")
        if not sku:
            unmapped_units += row["units"]
            continue
        refund = refund_stats.get(sku, {})
        rows.append({
            "sku": sku, **row,
            "refund_requested_units": refund.get("refund_requested_units", 0),
            "refund_completed_units": refund.get("refund_completed_units", 0),
            "return_received_units": receipts.get(sku, 0) if receipt_access else None,
        })
    ranked_units = rank_rows(rows)
    spu_rows = product_rows(request.user, rows)
    return {
        "sku_rows": rows,
        "spu_rows": spu_rows,
        "ranked_units": ranked_units,
        "unmapped_units": unmapped_units,
        "unlinked_refund_units": unlinked["units"],
        "return_receipts_available": receipt_access,
    }


@api_view(["GET"])
@permission_classes([IsDatasetReportViewer])
def sales_abc(request):
    params = request.query_params
    filters = {key: params.get(key, "").strip() for key in ("store_id", "date_from", "date_to", "currency")}
    data = compute_sales_abc(request, filters, mode=params.get("demand_mode", "non_cancelled"))
    search = params.get("sku", "").strip().casefold()
    if len(search) > 160:
        raise ValidationError("SKU 筛选最多支持 160 个字符。")
    return success_response({**data, "rows": [row for row in data["sku_rows"] if search in row["sku"].casefold()]})
