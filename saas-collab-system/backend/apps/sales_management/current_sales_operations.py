"""Current-day, store-local sales summaries from ingested facts."""
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import DatabaseError, transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.commerce.models import SalesOrderItem
from apps.masterdata.models import StoreMaster
from apps.permissions.services import check_user_permission
from apps.reports.advertising_dataset import advertising_queryset
from apps.sales_management.observed_roi import _valid_expense, roi_values
from apps.sales_management.views import _decimal_string


MAX_GROUPS = 5000
MAX_PAGE_SIZE = 50
MAX_PAGE = 10000
MAX_STORE_ID = 9_223_372_036_854_775_807
ZERO = Decimal("0")


def _params(request, now):
    allowed = {"period", "view", "page", "page_size", "sort", "platform", "store_id", "region", "currency"}
    query = request.query_params
    if set(query) - allowed or any(len(query.getlist(key)) != 1 for key in query):
        raise ValidationError({"filters": "current 模式仅支持视图、分页、排序、平台、店铺、国家和币种参数，每项只能提供一次。"})
    if query.get("period") != "current":
        raise ValidationError({"period": "period 仅支持 current。"})
    view = query.get("view", "stores")
    if view != "stores":
        raise ValidationError({"view": "current 模式仅支持 stores 视图。"})
    sort = query.get("sort", "sales_desc")
    if sort not in {"sales_desc", "orders_desc"}:
        raise ValidationError({"sort": "current 模式仅支持 sales_desc 或 orders_desc。"})
    store_id = query.get("store_id")
    if store_id and (not store_id.isascii() or not store_id.isdecimal() or len(store_id) > 19 or not 1 <= int(store_id) <= MAX_STORE_ID):
        raise ValidationError({"store_id": "store_id 必须为正整数。"})
    currency = query.get("currency", "").strip().upper()
    if currency and (not currency.isascii() or not currency.isalnum() or len(currency) > 8):
        raise ValidationError({"currency": "币种代码无效。"})
    region = query.get("region", "").strip().upper()
    if region and (len(region) not in {2, 3} or not region.isascii() or not region.isalpha()):
        raise ValidationError({"region": "国家代码必须为 2 或 3 个英文字母。"})
    platform = query.get("platform", "").strip().lower()
    try:
        page_raw, size_raw = query.get("page", "1"), query.get("page_size", "20")
        if not page_raw.isascii() or not page_raw.isdecimal() or not size_raw.isascii() or not size_raw.isdecimal():
            raise ValueError
        page, page_size = int(page_raw), int(size_raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"page": "分页参数必须为整数。"}) from exc
    if not 1 <= page <= MAX_PAGE or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValidationError({"page": f"page 范围为 1 到 {MAX_PAGE}，page_size 范围为 1 到 {MAX_PAGE_SIZE}。"})
    return {
        "period": "current", "view": view, "sort": sort, "page": page, "page_size": page_size,
        "platform": platform or None, "store_id": int(store_id) if store_id else None,
        "region": region or None, "currency": currency or None, "now": now,
    }


def _local_windows(stores, now):
    result = {}
    for store_id, zone_name in stores:
        try:
            zone = ZoneInfo(zone_name)
        except (ValueError, KeyError) as exc:
            raise ValidationError({"store_id": "Store timezone is invalid."}) from exc
        local_now = now.astimezone(zone)
        start = datetime.combine(local_now.date(), time.min, tzinfo=zone).astimezone(UTC)
        result[store_id] = (start, local_now.date())
    return result


def _payload(request):
    # One UTC instant anchors every store's local-day boundary and the response timestamp.
    now = timezone.now().astimezone(UTC)
    p = _params(request, now)
    from apps.sales_management.sales_operations import _orders

    orders = _orders(request, p)
    # All possible store-local midnights are within this conservative UTC window.
    broad_start = now - timedelta(days=2)
    broad = orders.filter(created_at_utc__gte=broad_start, created_at_utc__lt=now)
    candidate_ids = list(broad.order_by().values_list("store_id", flat=True).distinct()[:MAX_GROUPS + 1])
    if len(candidate_ids) > MAX_GROUPS:
        raise ValidationError({"filters": f"current 模式最多支持 {MAX_GROUPS} 个候选店铺。"})
    stores = list(StoreMaster.objects.filter(tenant=request.user.tenant, pk__in=candidate_ids).values_list("id", "timezone"))
    windows = _local_windows(stores, now)
    branches = {}
    for store_id, (start, _day) in windows.items():
        branches.setdefault(start, []).append(store_id)
    current_filter = Q(pk__in=[])
    for start, ids in branches.items():
        current_filter |= Q(store_id__in=ids, created_at_utc__gte=start, created_at_utc__lt=now)
    current_orders = broad.filter(current_filter).exclude(normalized_status="cancelled").order_by()
    grouped = list(current_orders.values(
        "store_id", "store__name", "store__country_code", "currency",
    ).annotate(
        sales=Sum("order_total_amount"), order_count=Count("pk"),
    ).order_by("currency", "store_id")[:MAX_GROUPS + 1])
    if len(grouped) > MAX_GROUPS:
        raise ValidationError({"filters": f"current 模式最多支持 {MAX_GROUPS} 个店铺币种汇总。"})

    ad_expenses, ad_reason = {}, None
    if grouped:
        if not check_user_permission(request.user, "analytics.view", cache=getattr(request, "_permission_resolution_cache", None)):
            ad_reason = "暂无广告数据查看权限。"
        else:
            ids = sorted({row["store_id"] for row in grouped})
            ad_days = [windows[sid][1] for sid in ids]
            try:
                with transaction.atomic():
                    ads = advertising_queryset(request, {"date_from": min(ad_days), "date_to": max(ad_days)}, "analytics.view")
                    ads = ads.filter(store_id__in=ids)
                    for ad in ads.values("store_id", "currency", "report_date").annotate(expense=Sum(_valid_expense())):
                        if ad["report_date"] == windows.get(ad["store_id"], (None, None))[1]:
                            key = (ad["store_id"], ad["currency"])
                            previous = ad_expenses.get(key)
                            value = ad["expense"]
                            if value is not None:
                                ad_expenses[key] = (previous or ZERO) + Decimal(value)
            except PermissionDenied:
                ad_expenses, ad_reason = {}, '暂无该范围广告数据查看权限，无法计算 ROI。'
            except (DatabaseError, ValidationError):
                ad_expenses, ad_reason = {}, "广告数据暂不可用，无法计算 ROI。"

    currency_totals = {}
    for row in grouped:
        code = row["currency"]
        summary = currency_totals.setdefault(code, {"sales": ZERO, "spend": ZERO, "roi_sales": ZERO, "has_sales": False, "has_spend": False})
        amount = Decimal(row["sales"] or 0)
        summary["sales"] += amount
        summary["has_sales"] = True
        spend = ad_expenses.get((row["store_id"], code))
        if spend is not None:
            summary["spend"] += spend
            if spend > ZERO:
                summary["roi_sales"] += amount
            summary["has_spend"] = True
    currency_groups = []
    for code, summary in sorted(currency_totals.items()):
        spend_arg = summary["spend"] if summary["has_spend"] else None
        gmv_arg = summary["roi_sales"] if summary["has_spend"] else None
        spend, roi, _delta, reason = roi_values(gmv_arg, None, (spend_arg, None))
        if ad_reason:
            reason = ad_reason
        elif roi is not None:
            reason += '；汇总 ROI 仅按同币种有广告费记录的店铺计算。'
        currency_groups.append({
            "currency": code, "sales_amount": _decimal_string(summary["sales"]),
            "previous_sales_amount": None, "change_percent": None,
            "ad_spend": spend, "roi": roi, "roi_delta": None, "ad_reason": reason,
        })

    def order_key(row):
        metric = row["order_count"] if p["sort"] == "orders_desc" else row["sales"]
        return (row["currency"], -(Decimal(metric or 0)), row["store_id"])

    grouped.sort(key=order_key)
    offset = (p["page"] - 1) * p["page_size"]
    page_rows = grouped[offset:offset + p["page_size"] + 1]
    has_next = len(page_rows) > p["page_size"]
    page_rows = page_rows[:p["page_size"]]
    page_ids = [row["store_id"] for row in page_rows]
    unit_map = {}
    if page_rows:
        page_orders = current_orders.filter(store_id__in=page_ids)
        for unit in SalesOrderItem.objects.filter(sales_order__in=page_orders).order_by().values(
            "sales_order__store_id", "sales_order__currency",
        ).annotate(units=Sum("quantity")):
            unit_map[(unit["sales_order__store_id"], unit["sales_order__currency"])] = int(unit["units"] or 0)

    rows = []
    for row in page_rows:
        key = (row["store_id"], row["currency"])
        spend_arg = ad_expenses.get(key)
        spend, roi, _delta, reason = roi_values(row["sales"], None, (spend_arg, None))
        if ad_reason:
            reason = ad_reason
        rows.append({
            "store_id": row["store_id"], "store_name": row["store__name"],
            "country": row["store__country_code"], "currency": row["currency"],
            "business_date": windows[row['store_id']][1].isoformat(),
            "sales_amount": _decimal_string(row["sales"]), "order_count": int(row["order_count"]),
            "units_sold": unit_map.get(key, 0), "previous_sales_amount": None,
            "change_percent": None, "roi_delta": None, "ad_spend": spend, "roi": roi,
            "ad_reason": reason,
        })

    beijing_today = now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
    notices = ["当前数据为各店铺当地今日零点至生成时刻的已入库订单；未生成同点历史比较。"]
    if not p["currency"]:
        notices.append("金额按币种分组显示，未进行跨币种换算。")
    return {
        "period": "current", "comparison_available": False,
        "filters": {"date_from": beijing_today, "date_to": beijing_today,
                    "previous_from": None, "previous_to": None, "region": p["region"],
                    "platform": p["platform"], "store_id": p["store_id"], "currency": p["currency"],
                    "view": "stores", "sort": p["sort"], "period": "current"},
        "rows": rows, "currency_groups": currency_groups, "has_next": has_next,
        "page": p["page"], "page_size": p["page_size"], "notices": notices,
        "generated_at": now.isoformat(),
    }
