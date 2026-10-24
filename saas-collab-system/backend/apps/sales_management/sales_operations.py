"""Bounded, read-only sales operations summaries."""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Count, Max, Q, Sum
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.views import APIView

from apps.commerce.models import SalesOrder, SalesOrderItem
from apps.common.responses import success_response
from apps.masterdata.models import StoreMaster
from apps.permissions.api_permissions import DeclaredApplicationPermission
from apps.permissions.services import check_user_permission
from apps.sales_management.reporting import _local_day_expression
from apps.sales_management.scopes import filter_sales_queryset
from apps.sales_management.views import _decimal_string


MAX_DAYS = 31
MAX_PAGE_SIZE = 50
MAX_PAGE = 10_000
MAX_STORE_ID = 9_223_372_036_854_775_807
ZERO = Decimal("0")


def _params(request):
    allowed = {"date_from", "date_to", "platform", "store_id", "currency", "region", "view", "page", "page_size"}
    if set(request.query_params) - allowed or any(len(request.query_params.getlist(key)) != 1 for key in request.query_params):
        raise ValidationError({"filters": "仅支持起止日期、平台、店铺、币种、视图和分页参数，每项只能提供一次。"})
    today = timezone.localdate(timezone=ZoneInfo(settings.SUPPLY_CHAIN_TIME_ZONE))
    yesterday = today - timedelta(days=1)
    try:
        end = date.fromisoformat(request.query_params.get("date_to") or yesterday.isoformat())
        start = date.fromisoformat(request.query_params.get("date_from") or end.isoformat())
    except (TypeError, ValueError) as exc:
        raise ValidationError({"date_from": "日期必须使用 YYYY-MM-DD 格式。"}) from exc
    if start < date(1970, 1, 2):
        raise ValidationError({"date_from": "日期超出可查询范围。"})
    if start > end:
        raise ValidationError({"date_to": "结束日期不能早于开始日期。"})
    if end > yesterday:
        raise ValidationError({"date_to": "只支持已完成日期。"})
    if (end - start).days + 1 > MAX_DAYS:
        raise ValidationError({"date_to": f"日期范围最多 {MAX_DAYS} 天。"})
    view = request.query_params.get("view", "stores")
    if view not in {"stores", "products"}:
        raise ValidationError({"view": "view 仅支持 stores 或 products。"})
    store_id = request.query_params.get("store_id")
    if store_id and (
        not store_id.isascii() or not store_id.isdecimal() or len(store_id) > 19
        or not 1 <= int(store_id) <= MAX_STORE_ID
    ):
        raise ValidationError({"store_id": "store_id 必须为正整数。"})
    if view == "products" and not store_id:
        raise ValidationError({"store_id": "商品视图必须指定单个店铺。"})
    currency = request.query_params.get("currency", "").strip().upper()
    if currency and (not currency.isascii() or not currency.isalnum() or len(currency) > 8):
        raise ValidationError({"currency": "币种代码无效。"})
    platform = request.query_params.get("platform", "").strip().lower()
    region = request.query_params.get("region", "").strip().upper()
    if region and (len(region) not in {2, 3} or not region.isascii() or not region.isalpha()):
        raise ValidationError({"region": "国家代码必须为 2 或 3 个英文字母。"})
    try:
        page_raw = request.query_params.get("page", "1")
        size_raw = request.query_params.get("page_size", "20")
        if not page_raw.isascii() or not page_raw.isdecimal() or not size_raw.isascii() or not size_raw.isdecimal():
            raise ValueError("ASCII decimal integers required")
        page, page_size = int(page_raw), int(size_raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"page": "分页参数必须为整数。"}) from exc
    if page < 1 or page > MAX_PAGE or page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise ValidationError({"page": f"page 范围为 1 到 {MAX_PAGE}，page_size 范围为 1 到 {MAX_PAGE_SIZE}。"})
    days = (end - start).days + 1
    previous_end, previous_start = start - timedelta(days=1), start - timedelta(days=days)
    return {
        "date_from": start, "date_to": end,
        "previous_from": previous_start, "previous_to": previous_end,
        "platform": platform or None, "store_id": int(store_id) if store_id else None,
        "currency": currency or None, "view": view, "page": page, "page_size": page_size,
        "region": region or None,
    }


def _orders(request, params):
    orders = SalesOrder.objects.filter(tenant=request.user.tenant)
    cache = getattr(request, "_permission_resolution_cache", None)
    orders = filter_sales_queryset(request.user, "sales_management.view", orders, permission_cache=cache)
    if params["view"] == "products":
        if not check_user_permission(request.user, "sales_management.skus.view", cache=cache):
            raise PermissionDenied("缺少商品销售查看权限。")
        # Sequential filtering yields the intersection of both grants' row scopes.
        orders = filter_sales_queryset(request.user, "sales_management.skus.view", orders, permission_cache=cache)
    if params["platform"]:
        orders = orders.filter(platform__platform_type=params["platform"])
    if params["store_id"]:
        orders = orders.filter(store_id=params["store_id"])
    if params["currency"]:
        orders = orders.filter(currency=params["currency"])
    if params["region"]:
        orders = orders.filter(store__country_code__iexact=params["region"])
    return orders


def _aggregated_orders(request, orders, params):
    # Local business dates can differ from UTC by at most one day. This broad
    # envelope keeps the SQL facts bounded before the timezone-aware date expression.
    utc_start = datetime.combine(params["previous_from"] - timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    utc_end = datetime.combine(params["date_to"] + timedelta(days=2), datetime.min.time(), tzinfo=UTC)
    orders = orders.filter(created_at_utc__gte=utc_start, created_at_utc__lt=utc_end)
    local_day = _local_day_expression(orders, "created_at_utc", "store__timezone")
    orders = orders.annotate(local_day=local_day).filter(
        Q(local_day__gte=params["date_from"], local_day__lte=params["date_to"])
        | Q(local_day__gte=params["previous_from"], local_day__lte=params["previous_to"])
    )
    period = Q(local_day__gte=params["date_from"], local_day__lte=params["date_to"])
    previous = Q(local_day__gte=params["previous_from"], local_day__lte=params["previous_to"])
    return orders, period, previous


def _percent(current, previous):
    if current is None or previous is None or Decimal(previous or 0) <= 0:
        return None
    return _decimal_string((Decimal(current or 0) - Decimal(previous)) * Decimal("100") / Decimal(previous))


def _ad_fields(request):
    if not check_user_permission(request.user, "analytics.view", cache=getattr(request, "_permission_resolution_cache", None)):
        return None, None, "暂无广告数据查看权限。"
    # shop_daily does not have a completeness watermark, so expense and ROI remain unknown.
    return None, None, "店铺广告日报缺少完整性校验，无法确认广告费覆盖。"


def _payload(request):
    p = _params(request)
    base = _orders(request, p)
    orders, period, previous = _aggregated_orders(request, base, p)
    current_valid = ~Q(normalized_status="cancelled")
    spend, _, ad_reason = _ad_fields(request)
    product_items = None
    if p["view"] == "products":
        product_items = SalesOrderItem.objects.filter(sales_order__in=orders).exclude(
            Q(platform_product_id__isnull=True) | Q(platform_product_id="")
        ).order_by()
        product_items = product_items.annotate(local_day=_local_day_expression(
            product_items, "sales_order__created_at_utc", "sales_order__store__timezone",
        ))
        item_period = Q(local_day__gte=p["date_from"], local_day__lte=p["date_to"]) & ~Q(sales_order__normalized_status="cancelled")
        item_previous = Q(local_day__gte=p["previous_from"], local_day__lte=p["previous_to"]) & ~Q(sales_order__normalized_status="cancelled")
    currency_groups = []
    if product_items is None:
        currency_query = orders.order_by().values("currency").annotate(
            sales=Sum("order_total_amount", filter=period & current_valid),
            prev_sales=Sum("order_total_amount", filter=previous & current_valid),
        ).filter(Q(sales__isnull=False) | Q(prev_sales__isnull=False)).order_by("currency")
    else:
        currency_query = product_items.values("sales_order__currency").annotate(
            sales=Sum("line_total_amount", filter=item_period),
            prev_sales=Sum("line_total_amount", filter=item_previous),
        ).filter(Q(sales__isnull=False) | Q(prev_sales__isnull=False)).order_by("sales_order__currency")
    for agg in currency_query:
        cur, prev = agg["sales"], agg["prev_sales"]
        currency = agg.get("currency", agg.get("sales_order__currency"))
        currency_groups.append({
            "currency": currency, "sales_amount": None if cur is None else _decimal_string(cur),
            "previous_sales_amount": None if prev is None else _decimal_string(prev),
            "change_percent": _percent(cur, prev), "ad_spend": spend, "roi": None,
            "roi_delta": None, "ad_reason": ad_reason,
        })

    if p["view"] == "stores":
        grouped = orders.order_by().values("store_id", "store__name", "store__country_code", "currency").annotate(
            sales=Sum("order_total_amount", filter=period & current_valid),
            prev_sales=Sum("order_total_amount", filter=previous & current_valid),
            order_count=Count("pk", filter=period & current_valid),
            previous_orders=Count("pk", filter=previous & current_valid),
        ).filter(Q(sales__isnull=False) | Q(prev_sales__isnull=False)).order_by("-sales", "store_id", "currency")
    else:
        grouped = product_items.values(
            "sales_order__store_id", "sales_order__store__name", "sales_order__store__country_code",
            "sales_order__currency", "platform_product_id",
        ).annotate(
            sales=Sum("line_total_amount", filter=item_period),
            prev_sales=Sum("line_total_amount", filter=item_previous),
            order_count=Count("sales_order_id", filter=item_period, distinct=True),
            units_sold=Sum("quantity", filter=item_period),
            product_name=Max("item_name_snapshot"),
        ).filter(Q(sales__isnull=False) | Q(prev_sales__isnull=False)).order_by("-sales", "sales_order__store_id", "sales_order__currency", "platform_product_id")

    count = grouped.count()
    start = (p["page"] - 1) * p["page_size"]
    page_rows = list(grouped[start:start + p["page_size"]])
    rows = []
    for g in page_rows:
        product = p["view"] == "products"
        store_id = g["sales_order__store_id"] if product else g["store_id"]
        currency = g["sales_order__currency"] if product else g["currency"]
        current, prev = g["sales"], g["prev_sales"]
        row = {
            "store_id": store_id,
            "store_name": g["sales_order__store__name"] if product else g["store__name"],
            "country": g["sales_order__store__country_code"] if product else g["store__country_code"],
            "currency": currency, "sales_amount": None if current is None else _decimal_string(current),
            "previous_sales_amount": None if g["prev_sales"] is None else _decimal_string(prev),
            "change_percent": _percent(current, g["prev_sales"]),
            "observation_status": "missing_current" if current is None else "observed",
            "order_count": None if current is None else int(g["order_count"] or 0),
            "units_sold": (None if current is None else int(g.get("units_sold") or 0)) if product else 0,
            "ad_spend": spend, "roi": None, "roi_delta": None, "ad_reason": ad_reason,
        }
        if product:
            decline = current is not None and g["prev_sales"] and Decimal(current) < Decimal(g["prev_sales"]) * Decimal("0.7")
            row.update({"product_id": g["platform_product_id"], "product_name": g["product_name"] or "",
                        "diagnosis": _diagnosis(current, g["prev_sales"]) if p["date_from"] == p["date_to"] and p["date_to"] == timezone.localdate(timezone=ZoneInfo(settings.SUPPLY_CHAIN_TIME_ZONE)) - timedelta(days=1) and decline else None})
        rows.append(row)
    if p["view"] == "stores" and rows:
        store_ids = [r["store_id"] for r in rows]
        unit_map = {
            (r["sales_order__store_id"], r["sales_order__currency"]): int(r["units"] or 0)
            for r in SalesOrderItem.objects.filter(
                sales_order__in=orders.filter(local_day__gte=p["date_from"], local_day__lte=p["date_to"]).exclude(normalized_status="cancelled"),
                sales_order__store_id__in=store_ids,
            ).order_by().values("sales_order__store_id", "sales_order__currency").annotate(units=Sum("quantity"))
        }
        for row in rows:
            row["units_sold"] = None if row["sales_amount"] is None else unit_map.get((row["store_id"], row["currency"]), 0)
    notices = []
    if p["view"] == "products":
        notices.append("未提供平台商品 ID 的销售行已排除，避免将无关商品合并。")
        notices.append("未采集买家数、访客数、转化率和库存；销量变化不能用于推断这些指标。")
        notices.append("下降诊断仅适用于昨日单日；其他历史区间仅展示销售比较。")
    return {
        "filters": {"date_from": p["date_from"].isoformat(), "date_to": p["date_to"].isoformat(),
                    "previous_from": p["previous_from"].isoformat(), "previous_to": p["previous_to"].isoformat(),
                    "region": p["region"], "platform": p["platform"], "store_id": p["store_id"],
                    "currency": p["currency"], "view": p["view"]},
        "currency_groups": currency_groups, "rows": rows, "page": p["page"], "page_size": p["page_size"],
        "has_next": start + p["page_size"] < count, "truncated": False,
        "notices": notices + ["来源数据完整性未验证；仅前期有记录的对象保留，本期显示未观测，不按零或下降100%处理。"], "generated_at": timezone.now().isoformat(),
    }


def _diagnosis(current, previous):
    return {
        "status": "suspected_decline", "title": "昨日商品 GMV 较前一日下降超过 30%",
        "steps": [
            {"label": "昨日 GMV", "value": _decimal_string(current), "status": "evidence"},
            {"label": "前一日 GMV", "value": _decimal_string(previous), "status": "evidence"},
            {"label": "买家数", "value": None, "status": "missing"},
            {"label": "访客流量", "value": None, "status": "missing"},
        ],
        "missing": ["买家数", "访客数", "转化率", "库存", "促销及价格变化"],
    }


class SalesOperationsView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "sales_management.view"

    def get(self, request):
        return success_response(_payload(request))
