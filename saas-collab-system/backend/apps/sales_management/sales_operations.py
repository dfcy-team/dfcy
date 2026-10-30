"""Bounded, read-only sales operations summaries."""
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Case, Count, DecimalField, F, Max, Q, Sum, When
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.views import APIView

from apps.commerce.models import SalesOrder, SalesOrderItem
from apps.common.responses import success_response
from apps.masterdata.models import StoreMaster
from apps.permissions.api_permissions import DeclaredApplicationPermission
from apps.permissions.services import check_user_permission
from apps.sales_management.reporting import _local_day_expression
from apps.sales_management.observed_roi import roi_values, shop_roi_fields
from apps.sales_management.scopes import filter_sales_queryset
from apps.sales_management.views import _decimal_string


MAX_DAYS = 31
MAX_PAGE_SIZE = 50
MAX_PAGE = 10_000
MAX_STORE_ID = 9_223_372_036_854_775_807
ZERO = Decimal("0")


def _params(request):
    allowed = {"date_from", "date_to", "platform", "store_id", "currency", "region", "view", "page", "page_size", "sort", "status", "product_id"}
    if set(request.query_params) - allowed or any(len(request.query_params.getlist(key)) != 1 for key in request.query_params):
        raise ValidationError({"filters": "仅支持起止日期、平台、店铺、币种、视图、商品 ID 和分页参数，每项只能提供一次。"})
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
    sort = request.query_params.get("sort", "sales_desc")
    valid_sorts = {"sales_desc", "change_asc", "loss_desc", "orders_desc"}
    if view == "products":
        valid_sorts.add("units_desc")
    if sort not in valid_sorts:
        raise ValidationError({"sort": "sort 参数不受支持。"})
    status = request.query_params.get("status", "all")
    if view != "products" and status != "all":
        raise ValidationError({"status": "异常筛选仅适用于商品视图。"})
    if status not in {"all", "declines", "unobserved"}:
        raise ValidationError({"status": "status 仅支持 all、declines 或 unobserved。"})
    if status == "declines" and (end - start).days != 0:
        raise ValidationError({"status": "下降筛选仅支持单日范围；请选择一天后重试。"})
    product_id = request.query_params.get("product_id")
    if product_id is not None and (view != "products" or not store_id):
        raise ValidationError({"product_id": "精确商品筛选仅支持指定店铺的商品视图。"})
    if product_id is not None and (not product_id or len(product_id) > 255 or not product_id.isascii() or any(ord(char) < 32 for char in product_id)):
        raise ValidationError({"product_id": "product_id 无效。"})
    currency = request.query_params.get("currency", "").strip().upper()
    if currency and (not currency.isascii() or not currency.isalnum() or len(currency) > 8):
        raise ValidationError({"currency": "币种代码无效。"})
    if product_id is not None and not currency:
        raise ValidationError({"currency": "精确商品筛选必须指定单一币种。"})
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
    # Exact-product drills are a single target; a stale parent-page offset must
    # never hide that target after SQL has narrowed the aggregate.
    return {
        "date_from": start, "date_to": end,
        "previous_from": previous_start, "previous_to": previous_end,
        "platform": platform or None, "store_id": int(store_id) if store_id else None,
        "currency": currency or None, "view": view, "page": 1 if product_id is not None else page, "page_size": page_size,
        "sort": sort, "status": status,
        "region": region or None,
        "product_id": product_id,
    }


def _orders(request, params):
    orders = SalesOrder.objects.filter(tenant=request.user.tenant)
    if getattr(request, "delivery_store_ids", None) is not None:
        orders = orders.filter(store_id__in=request.delivery_store_ids)
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
    # Keep the fact column bare so the store/date index can bound every read.
    utc_start = datetime.combine(params["previous_from"] - timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    utc_end = datetime.combine(params["date_to"] + timedelta(days=2), datetime.min.time(), tzinfo=UTC)
    orders = orders.filter(created_at_utc__gte=utc_start, created_at_utc__lt=utc_end)
    period, previous = Q(pk__in=[]), Q(pk__in=[])
    scoped_ids = orders.order_by().values("store_id").distinct()
    stores = StoreMaster.objects.filter(tenant=request.user.tenant, pk__in=scoped_ids).values_list("id", "timezone")
    windows = {}
    for sid, name in stores:
        try:
            zone = ZoneInfo(name)
        except (ValueError, KeyError) as exc:
            raise ValidationError({"store_id": "Store timezone is invalid."}) from exc
        boundary = tuple(datetime.combine(day, datetime.min.time(), tzinfo=zone).astimezone(UTC) for day in
                         (params["date_from"], params["date_to"] + timedelta(days=1), params["previous_from"], params["previous_to"] + timedelta(days=1)))
        windows.setdefault(boundary, []).append(sid)
    for (begin, finish, old_begin, old_finish), ids in windows.items():
        period |= Q(store_id__in=ids, created_at_utc__gte=begin, created_at_utc__lt=finish)
        previous |= Q(store_id__in=ids, created_at_utc__gte=old_begin, created_at_utc__lt=old_finish)
    return orders.filter(period | previous), period, previous


def _percent(current, previous):
    if current is None or previous is None or Decimal(previous or 0) <= 0:
        return None
    return _decimal_string((Decimal(current or 0) - Decimal(previous)) * Decimal("100") / Decimal(previous))


def _payload(request):
    if request.query_params.get("period") == "current":
        from apps.sales_management.current_sales_operations import _payload as current_payload

        return current_payload(request)
    p = _params(request)
    base = _orders(request, p)
    orders, period, previous = _aggregated_orders(request, base, p)
    current_valid = ~Q(normalized_status="cancelled")
    if p["view"] == "stores":
        ad_expenses, ad_permission_reason = shop_roi_fields(request, orders, p)
    else:
        ad_expenses, ad_permission_reason = {}, None
    product_items = None
    if p["view"] == "products":
        product_items = SalesOrderItem.objects.filter(sales_order__in=orders).exclude(
            Q(platform_product_id__isnull=True) | Q(platform_product_id="")
        ).order_by()
        if p["product_id"] is not None:
            product_items = product_items.filter(platform_product_id=p["product_id"])
        product_items = product_items.annotate(local_day=_local_day_expression(
            product_items, "sales_order__created_at_utc", "sales_order__store__timezone",
        ))
        item_period = Q(local_day__gte=p["date_from"], local_day__lte=p["date_to"]) & ~Q(sales_order__normalized_status="cancelled")
        item_previous = Q(local_day__gte=p["previous_from"], local_day__lte=p["previous_to"]) & ~Q(sales_order__normalized_status="cancelled")
    # Currency summaries keep full sales totals, while ROI uses only the stores
    # with positive observed advertising expense in the corresponding period.
    roi_sales = {}
    if p['view'] == 'stores' and ad_expenses:
        current_pairs, previous_pairs = Q(pk__in=[]), Q(pk__in=[])
        for (sid, code), expenses in ad_expenses.items():
            if expenses[0] is not None and expenses[0] > ZERO:
                current_pairs |= Q(store_id=sid, currency=code)
            if expenses[1] is not None and expenses[1] > ZERO:
                previous_pairs |= Q(store_id=sid, currency=code)
        roi_sales = {r['currency']: r for r in orders.order_by().values('currency').annotate(
            roi_gmv=Sum('order_total_amount', filter=period & current_valid & current_pairs),
            previous_roi_gmv=Sum('order_total_amount', filter=previous & current_valid & previous_pairs),
        )}
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
        group_expenses = (None, None)
        if product_items is None:
            current_expenses = [values[0] for (sid, cur), values in ad_expenses.items() if cur == currency and values[0] is not None]
            previous_expenses = [values[1] for (sid, cur), values in ad_expenses.items() if cur == currency and values[1] is not None]
            group_expenses = (
                sum(current_expenses, ZERO) if current_expenses else None,
                sum(previous_expenses, ZERO) if previous_expenses else None,
            )
            matched = roi_sales.get(currency, {})
            spend, roi, roi_delta, ad_reason = roi_values(matched.get('roi_gmv'), matched.get('previous_roi_gmv'), group_expenses)
            if roi is not None:
                ad_reason += '；汇总ROI仅采用已有广告费的店铺GMV，不等于全部店铺GMV除以部分广告费。'
            if ad_permission_reason:
                ad_reason = ad_permission_reason
        else:
            spend, roi, roi_delta, ad_reason = None, None, None, "商品级广告费未采集，无法计算 ROI。"
        currency_groups.append({
            "currency": currency, "sales_amount": None if cur is None else _decimal_string(cur),
            "previous_sales_amount": None if prev is None else _decimal_string(prev),
            "change_percent": _percent(cur, prev), "ad_spend": spend, "roi": roi,
            "roi_delta": roi_delta, "ad_reason": ad_reason,
        })

    if p["view"] == "stores":
        grouped = orders.order_by().values("store_id", "store__name", "store__country_code", "currency").annotate(
            sales=Sum("order_total_amount", filter=period & current_valid),
            prev_sales=Sum("order_total_amount", filter=previous & current_valid),
            order_count=Count("pk", filter=period & current_valid),
            previous_orders=Count("pk", filter=previous & current_valid),
        ).filter(Q(sales__isnull=False) | Q(prev_sales__isnull=False))
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
            tenant_id=Max("sales_order__tenant_id"), platform_id=Max("sales_order__platform_id"),
            image_variant_id=Max("platform_variant_id"), variant_count=Count("platform_variant_id", distinct=True),
        ).filter(Q(sales__isnull=False) | Q(prev_sales__isnull=False))

    grouped = grouped.annotate(sales_delta=F("sales") - F("prev_sales"), loss_amount=F("prev_sales") - F("sales"))
    if p["view"] == "products":
        if p["status"] == "declines":
            grouped = grouped.filter(sales__isnull=False, prev_sales__gt=0, sales__lt=F("prev_sales") * Decimal("0.7"))
        elif p["status"] == "unobserved":
            grouped = grouped.filter(sales__isnull=True, prev_sales__isnull=False)

    # Amounts in different currencies are not comparable. Keep them grouped by
    # currency unless the caller explicitly narrows the query to one currency.
    ordering = []
    if not p["currency"]:
        ordering.append("currency" if p["view"] == "stores" else "sales_order__currency")
    sort = p["sort"]
    if sort == "sales_desc":
        ordering.append(F("sales").desc(nulls_last=True))
    elif sort == "change_asc":
        grouped = grouped.annotate(change_ratio=Case(
            When(prev_sales__gt=0, sales__isnull=False,
                 then=F("sales_delta") * Decimal("100.0") / F("prev_sales")),
            default=None, output_field=DecimalField(max_digits=38, decimal_places=12),
        ))
        ordering.append(F("change_ratio").asc(nulls_last=True))
    elif sort == "loss_desc":
        ordering.append(F("loss_amount").desc(nulls_last=True))
    elif sort == "orders_desc":
        ordering.append(F("order_count").desc(nulls_last=True))
    elif sort == "units_desc":
        ordering.append(F("units_sold").desc(nulls_last=True))
    ordering.extend(["store_id" if p["view"] == "stores" else "sales_order__store_id"])
    if p["view"] == "products":
        ordering.append("platform_product_id")
    else:
        ordering.append("currency")
    grouped = grouped.order_by(*ordering)

    start = (p["page"] - 1) * p["page_size"]
    page_rows = list(grouped[start:start + p["page_size"] + 1])
    has_next = len(page_rows) > p["page_size"]
    page_rows = page_rows[:p["page_size"]]
    image_keys = {(row["tenant_id"], row["platform_id"], row["sales_order__store_id"], row["image_variant_id"]) for row in page_rows if p["view"] == "products" and row.get("variant_count") == 1 and row.get("image_variant_id")}
    from apps.listings.models import PlatformProductDetail
    image_by_key = {(image.tenant_id, image.platform_id, image.store_id, image.platform_variant_id): image.platform_image_url
        for image in PlatformProductDetail.objects.filter(tenant_id=request.user.tenant_id, platform_id__in={key[1] for key in image_keys}, store_id__in={key[2] for key in image_keys}, platform_variant_id__in={key[3] for key in image_keys}).only("tenant_id", "platform_id", "store_id", "platform_variant_id", "platform_image_url")}
    rows = []
    for g in page_rows:
        product = p["view"] == "products"
        store_id = g["sales_order__store_id"] if product else g["store_id"]
        currency = g["sales_order__currency"] if product else g["currency"]
        current, prev = g["sales"], g["prev_sales"]
        if product:
            spend, roi, roi_delta, ad_reason = None, None, None, "商品级广告费未采集，无法计算 ROI。"
        else:
            spend, roi, roi_delta, ad_reason = roi_values(
                current, prev, ad_expenses.get((store_id, currency), (None, None)),
            )
            if ad_permission_reason:
                ad_reason = ad_permission_reason
        row = {
            "store_id": store_id,
            "store_name": g["sales_order__store__name"] if product else g["store__name"],
            "country": g["sales_order__store__country_code"] if product else g["store__country_code"],
            "currency": currency, "sales_amount": None if current is None else _decimal_string(current),
            "previous_sales_amount": None if g["prev_sales"] is None else _decimal_string(prev),
            "change_percent": _percent(current, g["prev_sales"]),
            "sales_delta": None if g["sales_delta"] is None else _decimal_string(g["sales_delta"]),
            "loss_amount": None if g["loss_amount"] is None else _decimal_string(g["loss_amount"]),
            "observation_status": "missing_current" if current is None else "observed",
            "order_count": None if current is None else int(g["order_count"] or 0),
            "units_sold": (None if current is None else int(g.get("units_sold") or 0)) if product else 0,
            "ad_spend": spend, "roi": roi, "roi_delta": roi_delta, "ad_reason": ad_reason,
        }
        if product:
            decline = current is not None and g["prev_sales"] and Decimal(current) < Decimal(g["prev_sales"]) * Decimal("0.7")
            row.update({"product_id": g["platform_product_id"], "product_name": g["product_name"] or "",
                        "platform_image_url": image_by_key.get((g["tenant_id"], g["platform_id"], g["sales_order__store_id"], g["image_variant_id"]), "") if g.get("variant_count") == 1 and g.get("image_variant_id") else "",
                        "diagnosis": _diagnosis(current, g["prev_sales"]) if p["date_from"] == p["date_to"] and p["date_to"] == timezone.localdate(timezone=ZoneInfo(settings.SUPPLY_CHAIN_TIME_ZONE)) - timedelta(days=1) and decline else None})
        rows.append(row)
    if p["view"] == "stores" and rows:
        store_ids = [r["store_id"] for r in rows]
        unit_map = {
            (r["sales_order__store_id"], r["sales_order__currency"]): int(r["units"] or 0)
            for r in SalesOrderItem.objects.filter(
                sales_order__in=orders.filter(period).exclude(normalized_status="cancelled"),
                sales_order__store_id__in=store_ids,
            ).order_by().values("sales_order__store_id", "sales_order__currency").annotate(units=Sum("quantity"))
        }
        for row in rows:
            row["units_sold"] = None if row["sales_amount"] is None else unit_map.get((row["store_id"], row["currency"]), 0)
    from .observed_advertising import attach_operations_advertising
    attach_operations_advertising(
        request, p, orders, period, previous, currency_groups, rows,
        ad_expenses, ad_permission_reason,
    )
    notices = []
    if p["view"] == "products":
        notices.append("未提供平台商品 ID 的销售行已排除，避免将无关商品合并。")
        notices.append("未采集买家数、访客数、转化率和库存；销量变化不能用于推断这些指标。")
        notices.append("下降诊断仅适用于昨日单日；其他历史区间仅展示销售比较。")
        if p["status"] == "declines":
            notices.append("当前仅显示本期有记录、前期基线大于零且下降超过 30% 的商品；币种汇总保持完整筛选范围。")
        elif p["status"] == "unobserved":
            notices.append("当前仅显示前期有记录而本期未观测的商品；币种汇总保持完整筛选范围。")
    if not p["currency"]:
        notices.append("按币种分别排序，范围合计不随异常筛选改变。")
    return {
        "filters": {"date_from": p["date_from"].isoformat(), "date_to": p["date_to"].isoformat(),
                    "previous_from": p["previous_from"].isoformat(), "previous_to": p["previous_to"].isoformat(),
                    "region": p["region"], "platform": p["platform"], "store_id": p["store_id"],
                    "currency": p["currency"], "view": p["view"], "sort": p["sort"], "status": p["status"],
                    "product_id": p["product_id"]},
        "currency_groups": currency_groups, "rows": rows, "page": p["page"], "page_size": p["page_size"],
        "has_next": has_next, "truncated": False, "summary_scope": "all_filtered_stores",
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
