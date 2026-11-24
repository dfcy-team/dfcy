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
from apps.masterdata.exchange_rates import tenant_cny_rates
from apps.masterdata.models import StoreMaster
from apps.permissions.api_permissions import DeclaredApplicationPermission
from apps.permissions.services import check_user_permission
from apps.sales_management.reporting import _local_day_expression
from apps.sales_management.observed_roi import roi_values, shop_roi_fields
from apps.sales_management.cny_summary import cny_summary
from apps.sales_management.scopes import filter_sales_queryset
from apps.sales_management.views import _decimal_string


MAX_DAYS = 31
MAX_PAGE_SIZE = 50
MAX_PAGE = 10_000
MAX_STORE_ID = 9_223_372_036_854_775_807
ZERO = Decimal("0")


def _params(request):
    allowed = {"date_from", "date_to", "platform", "store_id", "currency", "region", "view", "page", "page_size", "sort", "status", "product_id", "evidence"}
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
    store_keys = store_id.split(",") if store_id else []
    if len(store_keys) > 100 or any(
        not key.isascii() or not key.isdecimal() or len(key) > 19
        or not 1 <= int(key) <= MAX_STORE_ID for key in store_keys
    ):
        raise ValidationError({"store_id": "请选择最多 100 个有效店铺。"})
    if view == "products" and len(store_keys) != 1:
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
    evidence = request.query_params.get("evidence", "0")
    if evidence not in {"0", "1"} or (evidence == "1" and (view != "products" or not product_id)):
        raise ValidationError({"evidence": "排查依据必须指定单个商品。"})
    return {
        "date_from": start, "date_to": end,
        "previous_from": previous_start, "previous_to": previous_end,
        "platform": platform or None, "store_id": int(store_keys[0]) if len(store_keys) == 1 else None,
        "store_ids": list(dict.fromkeys(map(int, store_keys))) if len(store_keys) > 1 else [],
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
    if params.get("store_ids"):
        orders = orders.filter(store_id__in=params["store_ids"])
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

    currency_groups = []
    if product_items is None:
        totals = {}
        for store in grouped:
            total = totals.setdefault(store["currency"], {
                "currency": store["currency"], "sales": None, "prev_sales": None,
                "order_count": 0, "roi_gmv": None, "previous_roi_gmv": None,
            })
            current_spend, previous_spend = ad_expenses.get((store["store_id"], store["currency"]), (None, None))
            for field, roi_field, expense in (
                ("sales", "roi_gmv", current_spend), ("prev_sales", "previous_roi_gmv", previous_spend),
            ):
                amount = store[field]
                if amount is not None:
                    total[field] = (total[field] or ZERO) + amount
                    if expense is not None and expense > ZERO:
                        total[roi_field] = (total[roi_field] or ZERO) + amount
            total["order_count"] += store["order_count"]
        currency_query = [totals[code] for code in sorted(totals)]
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
            spend, roi, roi_delta, ad_reason = roi_values(agg["roi_gmv"], agg["previous_roi_gmv"], group_expenses)
            if roi is not None:
                ad_reason += '；汇总ROI仅采用已有广告费的店铺GMV，不等于全部店铺GMV除以部分广告费。'
            if ad_permission_reason:
                ad_reason = ad_permission_reason
        else:
            spend, roi, roi_delta, ad_reason = None, None, None, "商品级广告费未采集，无法计算 ROI。"
        currency_groups.append({
            "currency": currency, "sales_amount": None if cur is None else _decimal_string(cur),
            "previous_sales_amount": None if prev is None else _decimal_string(prev),
            "order_count": int(agg.get("order_count") or 0) if product_items is None else None,
            "change_percent": _percent(cur, prev), "ad_spend": spend, "roi": roi,
            "roi_delta": roi_delta, "ad_reason": ad_reason,
        })

    grouped = grouped.annotate(sales_delta=F("sales") - F("prev_sales"), loss_amount=F("prev_sales") - F("sales"))
    if p["view"] == "products":
        if p["status"] == "declines":
            grouped = grouped.filter(sales__isnull=False, prev_sales__gt=0, sales__lt=F("prev_sales") * Decimal("0.7"))
        elif p["status"] == "unobserved":
            grouped = grouped.filter(sales__isnull=True, prev_sales__isnull=False)

    rates = tenant_cny_rates(request.user.tenant)
    currency_field = "currency" if p["view"] == "stores" else "sales_order__currency"
    ordering = []
    sort = p["sort"]
    if sort in {"sales_desc", "loss_desc"}:
        metric = "sales" if sort == "sales_desc" else "loss_amount"
        if not p["currency"]:
            # A decimal reciprocal also avoids integer division on SQLite.
            cny_value = Case(*[
                When(**{currency_field: code}, then=F(metric) * (Decimal(1) / info["rate"]))
                for code, info in rates.items() if info["rate"] and info["rate"] > 0
            ], default=None, output_field=DecimalField(max_digits=38, decimal_places=12))
            grouped = grouped.annotate(cny_sort_value=cny_value)
            ordering.extend([F("cny_sort_value").desc(nulls_last=True), currency_field])
        ordering.append(F(metric).desc(nulls_last=True))
    elif sort == "change_asc":
        grouped = grouped.annotate(change_ratio=Case(
            When(prev_sales__gt=0, sales__isnull=False,
                 then=F("sales_delta") * Decimal("100.0") / F("prev_sales")),
            default=None, output_field=DecimalField(max_digits=38, decimal_places=12),
        ))
        ordering.append(F("change_ratio").asc(nulls_last=True))
    elif sort == "orders_desc":
        ordering.append(F("order_count").desc(nulls_last=True))
    elif sort == "units_desc":
        ordering.append(F("units_sold").desc(nulls_last=True))
    ordering.extend(["store_id" if p["view"] == "stores" else "sales_order__store_id"])
    if p["view"] == "products":
        ordering.extend(["platform_product_id", currency_field])
    else:
        ordering.append("currency")
    grouped = grouped.order_by(*ordering)

    start = (p["page"] - 1) * p["page_size"]
    page_rows = list(grouped[start:start + p["page_size"] + 1])
    has_next = len(page_rows) > p["page_size"]
    page_rows = page_rows[:p["page_size"]]
    from apps.listings.models import PlatformProductDetail

    product_images = {}
    if p["view"] == "products" and page_rows:
        scope = Q()
        for platform_id, store_id, product_id in {
            (row["platform_id"], row["sales_order__store_id"], row["platform_product_id"])
            for row in page_rows
        }:
            scope |= Q(platform_id=platform_id, store_id=store_id, platform_product_id=product_id)
        images = PlatformProductDetail.objects.filter(scope, tenant_id=request.user.tenant_id).exclude(
            platform_image_url="",
        ).order_by("platform_variant_id", "pk").values_list(
            "platform_id", "store_id", "platform_product_id", "platform_image_source", "platform_image_url",
        )
        for platform_id, store_id, product_id, source, url in images:
            main, variants = product_images.setdefault((platform_id, store_id, product_id), ({}, {}))
            (main if source == "product" else variants).setdefault(url, None)
    rows = []
    for g in page_rows:
        product = p["view"] == "products"
        store_id = g["sales_order__store_id"] if product else g["store_id"]
        currency = g["sales_order__currency"] if product else g["currency"]
        images = []
        if product:
            main, variants = product_images.get((g["platform_id"], store_id, g["platform_product_id"]), ({}, {}))
            images = list(dict.fromkeys([*main, *variants]))
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
                        "platform_image_url": images[0] if images else "",
                        "platform_image_urls": images,
                        "_platform_id": g["platform_id"], "_variant_count": g["variant_count"],
                        "_platform_variant_id": g["image_variant_id"],
                        "diagnosis": _diagnosis(current, g["prev_sales"], g["order_count"]) if p["date_from"] == p["date_to"] and p["date_to"] == timezone.localdate(timezone=ZoneInfo(settings.SUPPLY_CHAIN_TIME_ZONE)) - timedelta(days=1) and decline else None})
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
    from .tiktok_spend import attach_tiktok_basis
    attach_tiktok_basis(request, rows, currency_groups)
    if p["view"] == "products" and request.query_params.get("evidence") == "1":
        _diagnosis_evidence(request, p, rows)
    notices = []
    if p["view"] == "products":
        notices.append("未提供平台商品 ID 的销售行已排除，避免将无关商品合并。")
        notices.append("下单数按商品、店铺和日期统计去重订单，排除取消订单；未接入商品访客数据，销量变化不能用于推断访客数、转化率或库存。")
        notices.append("下降诊断仅适用于昨日单日；其他历史区间仅展示销售比较。")
        if p["status"] == "declines":
            notices.append("当前仅显示本期有记录、前期基线大于零且下降超过 30% 的商品；币种汇总保持完整筛选范围。")
        elif p["status"] == "unobserved":
            notices.append("当前仅显示前期有记录而本期未观测的商品；币种汇总保持完整筛选范围。")
    if not p["currency"]:
        notices.append("金额按人民币折算后排序，无法折算的金额排在末尾。")
    summary_groups = currency_groups
    if p["view"] == "stores":
        # ROI numerator is scoped to stores with an observed expense.
        for group in summary_groups:
            group["ad_sales_amount"] = _decimal_string(totals[group["currency"]].get("roi_gmv"))
    return {
        "filters": {"date_from": p["date_from"].isoformat(), "date_to": p["date_to"].isoformat(),
                    "previous_from": p["previous_from"].isoformat(), "previous_to": p["previous_to"].isoformat(),
                    "region": p["region"], "platform": p["platform"], "store_id": p["store_id"], **({"store_ids": p["store_ids"]} if p["store_ids"] else {}),
                    "currency": p["currency"], "view": p["view"], "sort": p["sort"], "status": p["status"],
                    "product_id": p["product_id"]},
        "currency_groups": currency_groups, "cny_summary": cny_summary(
            request, summary_groups, "sales_amount", "ad_sales_amount" if p["view"] == "stores" else None, rates=rates,
        ), "rows": rows, "page": p["page"], "page_size": p["page_size"],
        "has_next": has_next, "truncated": False, "summary_scope": "all_filtered_stores",
        "notices": notices + ["来源数据完整性未验证；仅前期有记录的对象保留，本期显示未观测，不按零或下降100%处理。"], "generated_at": timezone.now().isoformat(),
    }


def _diagnosis(current, previous, order_count):
    return {
        "status": "suspected_decline", "title": "昨日商品 GMV 较前一日下降超过 30%",
        "steps": [
            {"label": "昨日 GMV", "value": _decimal_string(current), "status": "evidence"},
            {"label": "前一日 GMV", "value": _decimal_string(previous), "status": "evidence"},
            {"label": "下单数", "value": int(order_count or 0), "status": "evidence"},
            {"label": "商品访客数", "value": None, "status": "missing"},
        ],
        "order_count_basis": "按商品、店铺及日期去重，排除取消订单",
        "missing": ["商品访客数", "转化率", "库存", "促销及价格变化"],
    }


def _add_ad_metric(bucket, field, raw):
    try:
        value = Decimal(str(raw))
    except Exception:
        return
    if value.is_finite() and value >= 0:
        bucket["total"] += value
        bucket["count"] += 1


def _unique_sku_candidates(candidates):
    return {key: next(iter(ids)) for key, ids in candidates.items() if len(ids) == 1}


def _wms_snapshot_step(fact):
    known = "available_qty" in (fact["provided_quantity_fields"] or [])
    return {
        "label": f"WMS共享库存 · {fact['site_code']} · {fact['warehouse__name']} · {fact['source_sku']}",
        "value": fact["available_qty"] if known else None,
        "status": "evidence" if known else "missing",
        "snapshot_at": fact["snapshot_at_utc"].isoformat(),
    }


def _diagnosis_evidence(request, params, rows):
    """Attach authorized shop ad facts and latest mapped WMS stock in batches."""
    if not rows:
        return
    from apps.reports.advertising_dataset import advertising_queryset
    from apps.listings.models import PlatformProductDetail
    from apps.sales_management.views import _inventory_latest, _inventory_source
    from django.db import DatabaseError, transaction
    from datetime import datetime, time, timedelta
    from zoneinfo import ZoneInfo
    from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

    # Evidence is requested explicitly for one product, including products
    # that did not trigger yesterday's decline rule.
    for row in rows:
        if not row.get("diagnosis"):
            row["diagnosis"] = {
                "status": "reference", "title": "商品经营排查",
                "steps": [
                    {"label": "本期 GMV", "value": row.get("sales_amount"), "status": "evidence"},
                    {"label": "前期 GMV", "value": row.get("previous_sales_amount"), "status": "evidence"},
                    {"label": "下单数", "value": row.get("order_count"), "status": "evidence"},
                ],
                "missing": ["商品访客数", "转化率", "库存", "促销及价格变化"],
            }
    diagnosis_rows = [r for r in rows if r.get("diagnosis")]
    if not diagnosis_rows:
        for row in rows:
            row.pop("_platform_id", None)
            row.pop("_variant_count", None)
            row.pop("_platform_variant_id", None)
        return
    platform_types = dict(StoreMaster.objects.filter(
        tenant=request.user.tenant, pk__in={r["store_id"] for r in diagnosis_rows},
    ).values_list("pk", "platform__platform_type"))
    store_ids = {r["store_id"] for r in diagnosis_rows}
    ad_by_store = {}
    ad_unavailable = False
    try:
        with transaction.atomic():
            ads = advertising_queryset(request, {"date_from": params["date_to"], "date_to": params["date_to"]}, "analytics.view")
            for record in ads.filter(store_id__in=store_ids).values("store_id", "currency", "data"):
                bucket = ad_by_store.setdefault((record["store_id"], record["currency"]), {field: {"total": Decimal("0"), "count": 0, "complete": True} for field in ("clicks", "direct_conversions", "broad_conversions")})
                for field in ("clicks", "direct_conversions", "broad_conversions"):
                    metric = bucket[field]
                    before = metric["count"]
                    _add_ad_metric(metric, "total", record["data"].get(field))
                    if metric["count"] == before:
                        metric["complete"] = False
                bucket["_rows"] = bucket.get("_rows", 0) + 1
            for bucket in ad_by_store.values():
                for field in ("clicks", "direct_conversions", "broad_conversions"):
                    metric = bucket[field]
                    bucket[field] = metric["total"] if metric["complete"] and metric["count"] == bucket["_rows"] else None
    except (PermissionDenied, ValidationError, DatabaseError):
        # A missing analytics grant or temporarily unavailable dataset must not
        # suppress sales observations.
        ad_by_store = {}
        ad_unavailable = True

    identities = {}
    for row in diagnosis_rows:
        if row.get("_platform_id") is not None and row.get("product_id"):
            identities[(row["_platform_id"], row["store_id"], row["product_id"])] = row
    mapped = {}
    if identities:
        try:
            with transaction.atomic():
                details = PlatformProductDetail.objects.filter(
                    tenant=request.user.tenant,
                    store_id__in={key[1] for key in identities},
                    platform_id__in={key[0] for key in identities},
                    platform_product_id__in={key[2] for key in identities},
                ).values("platform_id", "store_id", "platform_product_id", "platform_variant_id", "platform_sku", "variant", "internal_sku_id", "internal_sku__sku_code", "internal_sku__product_type")
                candidates = {}
                for detail in details:
                    key = (detail["platform_id"], detail["store_id"], detail["platform_product_id"])
                    candidates.setdefault(key, []).append(detail)
                mapped = {key: value for key, value in candidates.items() if key in identities}
        except (DatabaseError, PermissionDenied):
            mapped = {}

    sku_ids = {d["internal_sku_id"] for variants in mapped.values() for d in variants if d["internal_sku_id"] is not None}
    from apps.products.models import ProductBundleComponent
    bundle_ids = {v["internal_sku_id"] for variants in mapped.values() for v in variants
                  if v.get("internal_sku__product_type") == "bundle"}
    components = {}
    if bundle_ids:
        for component in ProductBundleComponent.objects.filter(
            tenant=request.user.tenant, bundle_sku_id__in=bundle_ids,
            component_sku__tenant=request.user.tenant,
        ).values("bundle_sku_id", "component_sku_id", "quantity"):
            components.setdefault(component["bundle_sku_id"], []).append(component)
        sku_ids.update(c["component_sku_id"] for cs in components.values() for c in cs)
    stock_by_sku = {}
    if sku_ids:
        try:
            with transaction.atomic():
                local_day = params["date_to"]
                cutoff = datetime.combine(local_day + timedelta(days=1), time.min, tzinfo=ZoneInfo(settings.SUPPLY_CHAIN_TIME_ZONE)).astimezone(ZoneInfo("UTC"))
                source = _inventory_source(request, "sales_management.view").filter(snapshot_at_utc__lt=cutoff)
                latest = _inventory_latest(source).filter(internal_sku_id__in=sku_ids).select_related("warehouse").values(
                    "internal_sku_id", "source_sku", "warehouse_id", "warehouse__name", "site_code",
                    "available_qty", "provided_quantity_fields", "snapshot_at_utc",
                )
                for fact in latest:
                    stock_by_sku.setdefault(fact["internal_sku_id"], []).append(fact)
        except (PermissionDenied, ValidationError, DatabaseError):
            stock_by_sku = {}

    bundle_stock = {}
    for bundle_id, recipe in components.items():
        warehouses = {(f["site_code"], f["warehouse_id"]) for c in recipe
                      for f in stock_by_sku.get(c["component_sku_id"], [])}
        results = []
        for site, warehouse in sorted(warehouses):
            capacities, times = [], []
            warehouse_name = ""
            for component in recipe:
                facts = [f for f in stock_by_sku.get(component["component_sku_id"], [])
                         if (f["site_code"], f["warehouse_id"]) == (site, warehouse)]
                if not facts or any("available_qty" not in (f["provided_quantity_fields"] or []) for f in facts):
                    break
                warehouse_name = facts[0]["warehouse__name"]
                capacities.append(max(0, sum(f["available_qty"] for f in facts)) // component["quantity"])
                times.extend(f["snapshot_at_utc"] for f in facts)
            if len(capacities) == len(recipe):
                results.append(dict(internal_sku_id=bundle_id, site_code=site, warehouse_id=warehouse,
                    warehouse__name=warehouse_name, source_sku="组件可组装",
                    available_qty=min(capacities), provided_quantity_fields=["available_qty"],
                    snapshot_at_utc=min(times)))
        bundle_stock[bundle_id] = results

    price_by_product = {}
    price_status = "unavailable"
    try:
        from apps.permissions.services import check_user_permission
        if check_user_permission(request.user, "influencers.catalog.view"):
            from apps.influencers.models import SkuPriceSnapshot
            from apps.influencers.scopes import filter_queryset, require_scope
            require_scope(request.user, "influencers.catalog.view")
            prices = filter_queryset(request.user, SkuPriceSnapshot.objects.filter(
                tenant=request.user.tenant, listing__store_id__in=store_ids,
                listing__external_product_id__in={r["product_id"] for r in diagnosis_rows},
            ), "influencers.catalog.view").order_by("external_sku", "variant_id", "-source_updated_at", "-id")
            for price in prices.values("listing__store_id", "listing__external_product_id",
                    "external_sku", "variant_id", "variant_name", "original_price", "promotion_price",
                    "effective_price", "currency", "source_updated_at"):
                key = (price["listing__store_id"], price["listing__external_product_id"])
                price_by_product.setdefault(key, []).append(price)
            price_status = "missing"
    except (PermissionDenied, ValidationError, DatabaseError):
        price_status = "unavailable"

    for row in diagnosis_rows:
        diagnosis = row.get("diagnosis")
        if not diagnosis:
            continue
        diagnosis["platform"] = platform_types.get(row["store_id"], "")
        diagnosis["sections"] = []
        if diagnosis["platform"] == "tiktok":
            diagnosis["traffic_status"] = "not_collected"
            from apps.sales_management.tiktok_product_evidence import product_traffic_section, video_section
            video = video_section(request.user, store_id=row["store_id"], product_id=row["product_id"],
                date_from=params["date_from"], date_to=params["date_to"])
            diagnosis["traffic_status"] = video["status"]
            product_traffic = product_traffic_section(request.user, store_id=row["store_id"], product_id=row["product_id"],
                date_from=params["date_from"], date_to=params["date_to"])
            diagnosis["sections"] = [
                video,
                product_traffic,
            ]
            diagnosis["steps"] = [s for s in diagnosis["steps"] if s["label"] != "商品访客数"]
            diagnosis["missing"] = [m for m in diagnosis.get("missing", []) if m not in ("商品访客数", "转化率")]
            if product_traffic["status"] != "available":
                diagnosis["missing"].append("商品整体流量")
            try:
                from apps.reports.tiktok_ads_services import daily_spend_report
                report = daily_spend_report(request.user, {
                    "store_id": row["store_id"], "date_from": params["date_from"],
                    "date_to": params["date_to"], "page": 1, "page_size": 20,
                })
                overview = report.get("gmv_max_overview") or []
                diagnosis["gmv_max"] = [
                    {k: item.get(k) for k in ["currency", "cost", "gross_revenue", "orders", "roi", "complete", "stored_days", "expected_days"]}
                    for item in overview
                ]
                diagnosis["gmv_max_status"] = "available" if overview else "missing"
            except (NotFound, PermissionDenied, ValidationError, DatabaseError):
                diagnosis["gmv_max_status"] = "unavailable"
        ad = ad_by_store.get((row["store_id"], row["currency"]))
        if ad:
            diagnosis["steps"].extend([
                {"label": "店铺广告点击（非商品数据）", "value": ad["clicks"], "status": "shop_auxiliary" if ad["clicks"] is not None else "missing"},
                {"label": "店铺广告直接归因转化（非商品数据）", "value": ad["direct_conversions"], "status": "shop_auxiliary" if ad["direct_conversions"] is not None else "missing"},
                {"label": "店铺广告广泛归因转化（非商品数据）", "value": ad["broad_conversions"], "status": "shop_auxiliary" if ad["broad_conversions"] is not None else "missing"},
            ])
            diagnosis["shop_ad_data"] = True
            diagnosis["shop_ad_label"] = "以下为所属店铺广告数据，不代表该商品；转化率分母未确认，未计算转化率。"
        else:
            diagnosis["shop_ad_data"] = False
        variants = mapped.get((row.get("_platform_id"), row["store_id"], row["product_id"]), [])
        details = []
        unique_skus = set()
        qty_by_sku = {}
        for variant in variants:
            sku_id = variant["internal_sku_id"]
            if sku_id is not None:
                unique_skus.add(sku_id)
            is_bundle = variant.get("internal_sku__product_type") == "bundle"
            facts = bundle_stock.get(sku_id, []) if is_bundle else stock_by_sku.get(sku_id, [])
            valid_facts = [f for f in facts if "available_qty" in (f["provided_quantity_fields"] or [])]
            qty = sum((f["available_qty"] or 0) for f in valid_facts) if valid_facts else None
            is_bundle = variant.get("internal_sku__product_type") == "bundle"
            if sku_id is not None and qty is not None:
                qty_by_sku.setdefault(sku_id, qty)
            is_bundle = variant.get("internal_sku__product_type") == "bundle"
            entry = {
                "variant_id": variant.get("platform_variant_id"),
                "shared_inventory": sum(v["internal_sku_id"] == sku_id for v in variants) > 1 if sku_id else False,
                "variant": variant.get("variant") or variant.get("platform_variant_id") or "未命名规格",
                "platform_sku": variant.get("platform_sku") or "",
                "internal_sku": variant.get("internal_sku__sku_code") or "",
                "available_qty": qty,
                "warehouses": [{"warehouse": f.get("warehouse__name"), "source_sku": f.get("source_sku"), "available_qty": f.get("available_qty"), "snapshot_at": f["snapshot_at_utc"].isoformat()} for f in valid_facts],
                "snapshot_at": max((f["snapshot_at_utc"] for f in valid_facts), default=None).isoformat() if valid_facts else None,
                "inventory_basis": "按当前组件配方、同仓库存换算可组装数量，组件可能与其他规格共享" if is_bundle else "WMS 可用库存",
                "status": "evidence" if qty is not None and len(valid_facts) == len(facts) else ("partial" if qty is not None else "missing"),
            }
            details.append(entry)
        resources = {}
        for variant in variants:
            sku = variant["internal_sku_id"]
            resources[sku] = {c["component_sku_id"] for c in components.get(sku, [])} if sku in bundle_ids else {sku}
        resource_owner = {}
        shared_components = False
        for sku, ids in resources.items():
            for resource in ids:
                if resource in resource_owner and resource_owner[resource] != sku:
                    shared_components = True
                resource_owner[resource] = sku
        qtys = list(qty_by_sku.values())
        diagnosis["variant_details"] = details
        complete = bool(variants) and all(v["internal_sku_id"] is not None and v["internal_sku_id"] in qty_by_sku for v in variants) and all(d["status"] == "evidence" for d in details)
        diagnosis["inventory_summary"] = {"quantity": sum(qtys) if qtys and not shared_components else None,
            "shared_components": shared_components,
            "status": "shared_components" if shared_components else ("complete" if complete else ("known_subtotal" if qtys else "missing"))}
        missing = diagnosis.get("missing", [])
        if complete:
            diagnosis["missing"] = [m for m in missing if "库存" not in m]
        elif "库存" not in missing:
            missing.append("库存")
        prices = price_by_product.get((row["store_id"], row["product_id"]), [])
        diagnosis["price_status"] = "reference" if prices else price_status
        diagnosis["price_details"] = [dict(p, source_label="当前参考价格，未验证历史价格变化") for p in prices]
        for detail in details:
            matches = [p for p in prices if p["variant_id"] == detail["variant_id"]
                       and p["external_sku"] == detail["platform_sku"]]
            detail["price"] = matches[0] if len(matches) == 1 else None
        diagnosis["steps"].append({
            "label": "商品 SKU 去重共享可用库存合计" if complete else "商品 SKU 已知共享可用库存小计",
            "value": diagnosis["inventory_summary"]["quantity"],
            "status": "evidence" if complete else "missing",
        })
    for row in rows:
        row.pop("_platform_id", None)
        row.pop("_variant_count", None)
        row.pop("_platform_variant_id", None)


class SalesOperationsView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "sales_management.view"

    def get(self, request):
        return success_response(_payload(request))
