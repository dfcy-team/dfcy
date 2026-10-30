"""On-demand, bounded product decline ranking for the sales board."""
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Count, F, FloatField, Max, Q, Sum
from django.db.models.functions import Cast
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.views import APIView

from apps.commerce.models import SalesOrder, SalesOrderItem
from apps.common.responses import success_response
from apps.permissions.api_permissions import DeclaredApplicationPermission
from apps.permissions.services import check_user_permission
from apps.sales_management.reporting import _local_day_expression
from apps.sales_management.scopes import filter_sales_queryset
from apps.sales_management.views import _decimal_string


MAX_DAYS = 31
MAX_STORE_ID = 9_223_372_036_854_775_807


def _params(request):
    allowed = {"date_from", "date_to", "platform", "region", "store_id", "currency", "metric"}
    if set(request.query_params) - allowed or any(
        len(request.query_params.getlist(key)) != 1 for key in request.query_params
    ):
        raise ValidationError({"filters": "仅支持日期、平台、地区、店铺、币种和排行指标筛选，每项只能提供一次。"})
    yesterday = timezone.localdate(timezone=ZoneInfo(settings.SUPPLY_CHAIN_TIME_ZONE)) - timedelta(days=1)
    try:
        end = date.fromisoformat(request.query_params.get("date_to") or yesterday.isoformat())
        start = date.fromisoformat(request.query_params.get("date_from") or end.isoformat())
    except (TypeError, ValueError) as exc:
        raise ValidationError({"date_from": "日期必须使用 YYYY-MM-DD 格式。"}) from exc
    if start < date(1970, 1, 2):
        raise ValidationError({"date_from": "日期超出可查询范围。"})
    if start > end:
        raise ValidationError({"date_to": "结束日期不能早于开始日期。"})
    if end > timezone.now().astimezone(UTC).date() + timedelta(days=1):
        raise ValidationError({"date_to": "结束日期超出允许查询范围。"})
    days = (end - start).days + 1
    if days > MAX_DAYS:
        raise ValidationError({"date_to": f"日期范围最多 {MAX_DAYS} 天。"})

    store_id = request.query_params.get("store_id", "")
    if store_id and (
        not store_id.isascii() or not store_id.isdecimal() or len(store_id) > 19
        or not 1 <= int(store_id) <= MAX_STORE_ID
    ):
        raise ValidationError({"store_id": "store_id 必须为正整数。"})
    currency = request.query_params.get("currency", "").strip().upper()
    if not currency or not currency.isascii() or not currency.isalnum() or len(currency) > 8:
        raise ValidationError({"currency": "必须指定有效币种代码。"})
    metric = request.query_params.get("metric", "amount")
    if metric not in {"amount", "percent"}:
        raise ValidationError({"metric": "metric 仅支持 amount 或 percent。"})
    platform = request.query_params.get("platform", "").strip().lower()
    region = request.query_params.get("region", "").strip().upper()
    if region and (len(region) not in {2, 3} or not region.isascii() or not region.isalpha()):
        raise ValidationError({"region": "国家代码必须为 2 或 3 个英文字母。"})
    previous_to = start - timedelta(days=1)
    previous_from = start - timedelta(days=days)
    return {
        "date_from": start, "date_to": end, "previous_from": previous_from,
        "previous_to": previous_to, "days": days, "platform": platform or None,
        "region": region or None, "store_id": int(store_id) if store_id else None,
        "currency": currency, "metric": metric,
    }


def _diagnosis(current, previous):
    return {
        "status": "suspected_decline",
        "title": "昨日商品 GMV 较前一日下降超过 30%",
        "steps": [
            {"label": "昨日 GMV", "value": _decimal_string(current), "status": "evidence"},
            {"label": "前一日 GMV", "value": _decimal_string(previous), "status": "evidence"},
            {"label": "买家数", "value": None, "status": "missing"},
            {"label": "访客流量", "value": None, "status": "missing"},
        ],
        "missing": ["买家数", "访客数", "转化率", "库存", "促销及价格变化"],
    }


def _payload(request, p):
    cache = getattr(request, "_permission_resolution_cache", None)
    if not check_user_permission(request.user, "sales_management.skus.view", cache=cache):
        raise PermissionDenied("缺少商品销售查看权限。")
    orders = SalesOrder.objects.filter(tenant=request.user.tenant)
    # Intersect both grants' row scopes, matching the sales operations workspace.
    orders = filter_sales_queryset(request.user, "sales_management.view", orders, permission_cache=cache)
    orders = filter_sales_queryset(request.user, "sales_management.skus.view", orders, permission_cache=cache)
    if p["platform"]:
        orders = orders.filter(platform__platform_type=p["platform"])
    if p["store_id"]:
        orders = orders.filter(store_id=p["store_id"])
    if p["region"]:
        orders = orders.filter(store__country_code__iexact=p["region"])
    orders = orders.filter(currency=p["currency"])

    # Limit timestamp scanning to the requested and previous local date windows.
    utc_start = datetime.combine(p["previous_from"] - timedelta(days=1), time.min, tzinfo=UTC)
    utc_end = datetime.combine(p["date_to"] + timedelta(days=2), time.min, tzinfo=UTC)
    orders = orders.filter(created_at_utc__gte=utc_start, created_at_utc__lt=utc_end)
    # Resolve completion against the selected stores' own clocks. Keep the
    # store-zone probe inside the bounded timestamp envelope above.
    zone_names = orders.order_by().values_list("store__timezone", flat=True).distinct().iterator(chunk_size=500)
    for zone_name in zone_names:
        try:
            local_today = timezone.now().astimezone(ZoneInfo(zone_name)).date()
        except Exception as exc:
            raise ValidationError({"date_to": "店铺时区无效，无法确认日期是否结束。"}) from exc
        if p["date_to"] >= local_today:
            raise ValidationError({"date_to": "日期尚未在筛选范围内所有店铺结束，请选择历史日期。"})
    local_day = _local_day_expression(orders, "created_at_utc", "store__timezone")
    orders = orders.annotate(local_day=local_day).filter(
        Q(local_day__gte=p["previous_from"], local_day__lte=p["previous_to"])
        | Q(local_day__gte=p["date_from"], local_day__lte=p["date_to"])
    )
    items = SalesOrderItem.objects.filter(sales_order__in=orders).exclude(
        Q(platform_product_id__isnull=True) | Q(platform_product_id="")
    ).exclude(sales_order__normalized_status="cancelled").order_by()
    items = items.annotate(local_day=_local_day_expression(
        items, "sales_order__created_at_utc", "sales_order__store__timezone",
    ))
    current_period = Q(local_day__gte=p["date_from"], local_day__lte=p["date_to"])
    previous_period = Q(local_day__gte=p["previous_from"], local_day__lte=p["previous_to"])
    grouped = items.values(
        "sales_order__store_id", "sales_order__store__name", "sales_order__store__country_code",
        "sales_order__store__timezone", "sales_order__currency", "platform_product_id",
    ).annotate(
        sales=Sum("line_total_amount", filter=current_period),
        previous_sales=Sum("line_total_amount", filter=previous_period),
        product_name=Max("item_name_snapshot"),
        tenant_id=Max("sales_order__tenant_id"), platform_id=Max("sales_order__platform_id"),
        image_variant_id=Max("platform_variant_id"), variant_count=Count("platform_variant_id", distinct=True),
    ).filter(
        sales__isnull=False, previous_sales__isnull=False, previous_sales__gt=0,
        sales__lt=F("previous_sales"),
    )
    # Selection and ordering happen after full SQL aggregation across all products.
    order_fields = ["-decline_amount", "sales_order__store_id", "platform_product_id"]
    if p["metric"] == "percent":
        # Ratios are computed in SQL so the complete filtered set is ranked before LIMIT.
        from django.db.models import ExpressionWrapper
        grouped = grouped.annotate(
            decline_amount=F("previous_sales") - F("sales"),
            # Explicit floating casts avoid SQLite's integer division during tests;
            # monetary output still uses Decimal arithmetic in Python.
            decline_ratio=ExpressionWrapper(
                Cast(F("previous_sales") - F("sales"), FloatField())
                / Cast(F("previous_sales"), FloatField()),
                output_field=FloatField(),
            ),
        )
        order_fields = ["-decline_ratio", "sales_order__store_id", "platform_product_id"]
    else:
        grouped = grouped.annotate(decline_amount=F("previous_sales") - F("sales"))
    selected = list(grouped.order_by(*order_fields)[:10])
    from apps.listings.models import PlatformProductDetail
    image_keys = {(row["tenant_id"], row["platform_id"], row["sales_order__store_id"], row["image_variant_id"]) for row in selected if row["variant_count"] == 1 and row["image_variant_id"]}
    images = {(image.tenant_id, image.platform_id, image.store_id, image.platform_variant_id): image.platform_image_url
        for image in PlatformProductDetail.objects.filter(tenant_id=request.user.tenant_id, platform_id__in={key[1] for key in image_keys}, store_id__in={key[2] for key in image_keys}, platform_variant_id__in={key[3] for key in image_keys}).only("tenant_id", "platform_id", "store_id", "platform_variant_id", "platform_image_url")}
    rows = []
    for row in selected:
        current, previous = row["sales"], row["previous_sales"]
        change = (Decimal(current) - Decimal(previous)) * Decimal("100") / Decimal(previous)
        rows.append({
            "store_id": row["sales_order__store_id"],
            "store_name": row["sales_order__store__name"],
            "country": row["sales_order__store__country_code"],
            "currency": row["sales_order__currency"],
            "product_id": row["platform_product_id"],
            "product_name": row["product_name"] or "",
            "platform_image_url": images.get((row["tenant_id"], row["platform_id"], row["sales_order__store_id"], row["image_variant_id"]), "") if row["variant_count"] == 1 and row["image_variant_id"] else "",
            "sales_amount": _decimal_string(current),
            "previous_sales_amount": _decimal_string(previous),
            "change_percent": _decimal_string(change),
            "decline_amount": _decimal_string(Decimal(previous) - Decimal(current)),
            "diagnosis": _diagnosis(current, previous) if (
                p["date_from"] == p["date_to"]
                and p["date_to"] == timezone.now().astimezone(ZoneInfo(row["sales_order__store__timezone"])).date() - timedelta(days=1)
                and change < Decimal("-30")
            ) else None,
        })
    return {
        "filters": {
            "date_from": p["date_from"].isoformat(), "date_to": p["date_to"].isoformat(),
            "previous_from": p["previous_from"].isoformat(), "previous_to": p["previous_to"].isoformat(),
            "platform": p["platform"], "region": p["region"], "store_id": p["store_id"],
            "currency": p["currency"], "metric": p["metric"],
        },
        "rows": rows,
        "notices": [
            "仅比较两个期间均有销售记录且前期金额大于零的商品；缺失期间不按零处理。",
            "下降诊断仅适用于昨日单日；其他历史区间仅展示销售比较。",
            "诊断展示销售金额证据及未采集指标，不代表下降原因。",
        ],
    }


class BoardDeclinesView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "sales_management.view"

    def get(self, request):
        return success_response(_payload(request, _params(request)))
