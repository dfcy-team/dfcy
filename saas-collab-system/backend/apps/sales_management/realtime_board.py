"""Bounded, read-only aggregates for the sales realtime board."""
from datetime import date, timedelta
from decimal import Decimal
import logging
from types import SimpleNamespace

from django.conf import settings
from django.db import DatabaseError, transaction
from django.db.models import Count, Exists, F, Max, Min, OuterRef, Q, Sum, Window
from django.utils import timezone
from django.db.models.functions import Coalesce, RowNumber
from rest_framework.exceptions import ValidationError
from rest_framework.views import APIView

from apps.common.responses import success_response
from apps.permissions.api_permissions import DeclaredApplicationPermission
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from apps.commerce.models import SalesOrderItem
from apps.reports.advertising_dataset import _metric, advertising_queryset, filter_advertising_stores
from apps.permissions.models import DataScope
from apps.masterdata.models import StoreMaster
from apps.sales_management.reporting import _local_day_expression
from apps.sales_management.scopes import filter_sales_queryset
from apps.sales_management.views import (
    ZERO,
    _apply_dimensions,
    _decimal_string,
)
from apps.commerce.models import SalesOrder
from .board_products import attach_product_rankings


MAX_DATE_SPAN_DAYS = 31
logger = logging.getLogger(__name__)


def _board_filters(request):
    allowed = {"date_from", "date_to", "platform", "store_id", "currency", "region"}
    if set(request.query_params) - allowed:
        raise ValidationError({"filters": "大屏只支持国家、平台、店铺、币种和起止日期筛选。"})
    if any(len(request.query_params.getlist(key)) != 1 for key in request.query_params):
        raise ValidationError({"filters": "每个筛选项只能提供一个值。"})
    params = request.query_params.copy()
    # Match the workspace's configured business calendar used by the sales dashboard.
    from zoneinfo import ZoneInfo

    today = timezone.localdate(timezone=ZoneInfo(settings.SUPPLY_CHAIN_TIME_ZONE))
    start_raw = params.get("date_from") or today.isoformat()
    end_raw = params.get("date_to") or today.isoformat()
    try:
        start, end = date.fromisoformat(start_raw), date.fromisoformat(end_raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"date_from": "Expected ISO dates in YYYY-MM-DD format."}) from exc
    if start > end:
        raise ValidationError({"date_to": "date_to must be on or after date_from."})
    if (end - start).days + 1 > MAX_DATE_SPAN_DAYS:
        raise ValidationError({"date_to": f"Date range may not exceed {MAX_DATE_SPAN_DAYS} days."})
    params["date_from"], params["date_to"] = start.isoformat(), end.isoformat()

    store_id = params.get("store_id")
    if store_id and (not store_id.isascii() or not store_id.isdecimal() or int(store_id) <= 0):
        raise ValidationError({"store_id": "Store ID must be a positive integer."})
    if params.get("currency"):
        params["currency"] = params["currency"].strip().upper()
        if not params["currency"].isascii() or not params["currency"].isalnum() or len(params["currency"]) > 8:
            raise ValidationError({"currency": "Currency must be a valid code."})
    if params.get("platform"):
        params["platform"] = params["platform"].strip().lower()
    if params.get("region"):
        params["region"] = params["region"].strip().upper()
        if not params["region"].isascii() or not params["region"].isalpha() or len(params["region"]) not in (2, 3):
            raise ValidationError({"region": "国家/地区代码必须是 2 或 3 位英文字母。"})
    return params, start, end


def realtime_board_payload(request):
    params, start, end = _board_filters(request)
    scoped_request = SimpleNamespace(
        user=request.user,
        query_params=params,
        _permission_resolution_cache=getattr(request, "_permission_resolution_cache", None),
    )
    orders = SalesOrder.objects.filter(tenant=request.user.tenant)
    orders = filter_sales_queryset(
        request.user, "sales_management.view", orders,
        permission_cache=scoped_request._permission_resolution_cache,
    )
    scoped_orders = orders
    conflict_params = params.copy()
    conflict_params.pop("region", None)
    conflict_request = SimpleNamespace(
        user=request.user,
        query_params=conflict_params,
        _permission_resolution_cache=scoped_request._permission_resolution_cache,
    )
    country_check_orders = _apply_dimensions(orders, conflict_request, date_field="created_at_utc")
    orders = _apply_dimensions(country_check_orders, scoped_request, date_field=None)
    valid_orders = orders.exclude(normalized_status="cancelled")

    groups = {}
    for row in orders.order_by().values("currency").annotate(
        order_count=Count("pk"),
        valid_order_count=Count("pk", filter=~Q(normalized_status="cancelled")),
        sales_amount=Sum("order_total_amount", filter=~Q(normalized_status="cancelled")),
    ):
        group = _empty_group(row["currency"])
        group.update({
            "sales_amount": _decimal_string(row["sales_amount"] or ZERO),
            "order_count": int(row["order_count"] or 0),
            "valid_order_count": int(row["valid_order_count"] or 0),
        })
        groups[row["currency"]] = group

    for row in SalesOrderItem.objects.filter(sales_order__in=valid_orders).order_by().values(
        "sales_order__currency"
    ).annotate(units=Sum("quantity")):
        target = groups.setdefault(row["sales_order__currency"], _empty_group(row["sales_order__currency"]))
        target["units_sold"] = int(row["units"] or 0)

    from zoneinfo import ZoneInfo
    hourly = start == end == timezone.localdate(timezone=ZoneInfo(settings.SUPPLY_CHAIN_TIME_ZONE))
    for group in groups.values():
        group["trend_granularity"] = "hour" if hourly else "day"
        group["trend_note"] = "按店铺当地小时汇总已拉取数据；无观测小时不补零，有在途数据，后续同步后将更新。" if hourly else "按店铺当地日期汇总。"
    local_day = _local_day_expression(orders, "created_at_utc", "store__timezone", hourly=hourly)
    for row in orders.order_by().annotate(local_day=local_day).values("currency", "local_day").annotate(
        order_count=Count("pk"),
        sales_amount=Sum("order_total_amount", filter=~Q(normalized_status="cancelled")),
    ):
        target = groups.setdefault(row["currency"], _empty_group(row["currency"]))
        target["trend"].append({
            "date": row["local_day"].strftime("%H:00") if hourly else row["local_day"].isoformat(),
            "sales_amount": _decimal_string(row["sales_amount"] or ZERO),
            "order_count": int(row["order_count"] or 0),
        })

    if hourly:
        history_params = params.copy()
        history_params["date_from"] = (start - timedelta(days=7)).isoformat()
        history_params["date_to"] = (start - timedelta(days=1)).isoformat()
        history = _apply_dimensions(scoped_orders, SimpleNamespace(query_params=history_params, user=request.user), date_field="created_at_utc")
        history_day = _local_day_expression(history, "created_at_utc", "store__timezone")
        for row in history.order_by().annotate(bucket=history_day).values("currency", "bucket").annotate(
            order_count=Count("pk"),
            sales_amount=Sum("order_total_amount", filter=~Q(normalized_status="cancelled")),
        ):
            group = groups.setdefault(row["currency"], _empty_group(row["currency"]))
            group.setdefault("recent_trend", []).append({"date": row["bucket"].isoformat(), "sales_amount": _decimal_string(row["sales_amount"] or ZERO), "order_count": row["order_count"]})
        history_params["date_from"] = history_params["date_to"]
        yesterday = _apply_dimensions(scoped_orders, SimpleNamespace(query_params=history_params, user=request.user), date_field="created_at_utc")
        yesterday_hour = _local_day_expression(yesterday, "created_at_utc", "store__timezone", hourly=True)
        for row in yesterday.order_by().annotate(bucket=yesterday_hour).values("currency", "bucket").annotate(
            order_count=Count("pk"), sales_amount=Sum("order_total_amount", filter=~Q(normalized_status="cancelled")),
        ):
            group = groups.setdefault(row["currency"], _empty_group(row["currency"]))
            group.setdefault("previous_hourly_trend", []).append({"date": row["bucket"].strftime("%H:00"), "sales_amount": _decimal_string(row["sales_amount"] or ZERO), "order_count": row["order_count"]})
        for group in groups.values():
            group["trend_granularity"] = "hour"
            group["trend_note"] = "按店铺当地时间展示已拉取数据；有在途数据，后续同步后将更新。空缺小时不代表零成交。"
            for key in ("recent_trend", "previous_hourly_trend"):
                group.setdefault(key, []).sort(key=lambda row: row["date"])

    store_rankings = orders.order_by().values(
        "currency", "store_id", "store__name", "store__country_code"
    ).annotate(
        sales_amount=Sum("order_total_amount", filter=~Q(normalized_status="cancelled"), default=ZERO),
        order_count=Count("pk"),
    ).annotate(rank=Window(
        expression=RowNumber(), partition_by=[F("currency")], order_by=[F("sales_amount").desc(), F("store_id").asc()]
    ), order_rank=Window(
        expression=RowNumber(), partition_by=[F("currency")], order_by=[F("order_count").desc(), F("store_id").asc()]
    )).filter(Q(rank__lte=10) | Q(order_rank__lte=10)).order_by("currency", "rank")
    for row in store_rankings:
        group = groups.setdefault(row["currency"], _empty_group(row["currency"]))
        ranking = group.setdefault("store_rankings", {"sales_amount": [], "order_count": []})
        item = {
            "store_id": row["store_id"],
            "store_name": row["store__name"],
            "country_code": row["store__country_code"],
            "sales_amount": _decimal_string(row["sales_amount"] or ZERO),
            "order_count": int(row["order_count"] or 0),
        }
        if row["rank"] <= 10:
            group["store_ranking"].append(item)
            ranking["sales_amount"].append(item)
        if row["order_rank"] <= 10:
            ranking["order_count"].append({**item, "_rank": row["order_rank"]})
    for group in groups.values():
        ranked = group.get("store_rankings", {}).get("order_count", [])
        ranked.sort(key=lambda item: item["_rank"])
        for item in ranked:
            del item["_rank"]

    sku_rows = SalesOrderItem.objects.filter(sales_order__in=valid_orders).order_by().annotate(
        board_sku=Coalesce("internal_sku__sku_code", "seller_sku"),
    ).values(
        "sales_order__currency", "board_sku"
    ).annotate(
        sales_amount=Sum("line_total_amount"),
        units_sold=Sum("quantity"),
        name=Max("item_name_snapshot"),
        mapped_count=Count("pk", filter=Q(internal_sku__isnull=False)),
        line_count=Count("pk"),
        mapped_sku_id=Max("internal_sku_id"),
        site_min=Min("sales_order__store__country_code"),
        site_max=Max("sales_order__store__country_code"),
        inventory_type_value=Max("internal_sku__inventory_type"),
    ).annotate(rank=Window(
        expression=RowNumber(), partition_by=[F("sales_order__currency")], order_by=[F("sales_amount").desc(), F("board_sku").asc()]
    ), units_rank=Window(
        expression=RowNumber(), partition_by=[F("sales_order__currency")], order_by=[F("units_sold").desc(), F("board_sku").asc()]
    )).filter(Q(rank__lte=10) | Q(units_rank__lte=10)).order_by("sales_order__currency", "rank")
    for row in sku_rows:
        currency = row["sales_order__currency"]
        target = groups.setdefault(currency, _empty_group(currency))
        ranking = target.setdefault("sku_rankings", {"sales_amount": [], "units_sold": []})
        item = {
            "sku": row["board_sku"] or "",
            "name": row["name"] or row["board_sku"] or "",
            "sales_amount": _decimal_string(row["sales_amount"] or ZERO),
            "units_sold": int(row["units_sold"] or 0),
            "internal_sku_id": row["mapped_sku_id"] if row["mapped_count"] == row["line_count"] else None,
            "inventory_site": row["site_min"] if row["site_min"] == row["site_max"] else None,
            "inventory_type": row["inventory_type_value"],
            "product_classification_note": "按销售明细 SKU 聚合；未映射/未分类商品不作推断。",
        }
        if row["rank"] <= 10:
            target["sku_ranking"].append(item)
            ranking["sales_amount"].append(item)
        if row["units_rank"] <= 10:
            ranking["units_sold"].append({**item, "_rank": row["units_rank"]})
    for group in groups.values():
        ranked = group.get("sku_rankings", {}).get("units_sold", [])
        ranked.sort(key=lambda item: item["_rank"])
        for item in ranked:
            del item["_rank"]

    attach_product_rankings(valid_orders, groups, request.user.tenant_id)

    # Advertising requires an independent analytics grant. Even with that grant,
    # shop_daily currently has no completeness watermark suitable for a rate.
    ads_allowed = check_user_permission(
        request.user, "analytics.view", cache=getattr(request, "_permission_resolution_cache", None)
    )
    if ads_allowed:
        _attach_advertising(request, orders, groups, start, end, params, country_check_orders=country_check_orders)
    else:
        reason = "暂无广告数据查看权限。"
        status = "permission_missing"
        for group in groups.values():
            group["ad_status"], group["ad_reason"] = status, reason
    for group in groups.values():
        group["trend"].sort(key=lambda item: item["date"])
        group["store_ranking"] = group["store_ranking"][:10]
        group["product_classification_note"] = (
            "商品维度金额按有效订单行金额汇总，不含订单层运费等金额；"
            "系统 SPU/SKU 使用内部映射，类目使用商品系统类目树，未映射与未分类分开统计。"
        )

    from .board_inventory import attach_board_inventory
    try:
        # Isolate optional inventory reads even under an enclosing DB transaction.
        with transaction.atomic():
            attach_board_inventory(request, groups)
    except DatabaseError:
        logger.warning("Sales board inventory read unavailable", exc_info=True)
        for group in groups.values():
            from .board_inventory import _rows as inventory_rows
            for row in inventory_rows(group):
                row["inventory"] = {
                    "available_qty": None, "status": "unavailable", "label": "库存读取暂不可用",
                    "basis": "同站点已匹配仓共享库存", "warehouses": [],
                    "coverage_days": None, "coverage_reason": "库存数据暂不可用，暂不计算",
                }

    from .cny_summary import cny_summary
    for group in groups.values():
        group["ad_sales_amount"] = group.get("ad_rate_sales_amount")
    currency_groups = [groups[currency] for currency in sorted(groups)]
    return {
        "filters": {
            "date_from": start.isoformat(),
            "date_to": end.isoformat(),
            "platform": params.get("platform") or None,
            "store_id": params.get("store_id") or None,
            "currency": params.get("currency") or None,
            "region": params.get("region") or None,
        },
        "currency_groups": currency_groups,
        "cny_summary": cny_summary(request, currency_groups, "sales_amount", "ad_sales_amount", "ad_spend"),
        "product_classification_note": "商品维度按销售行汇总，不区分主商品/套装组成；使用商品系统类目树，并单列未映射与未分类。",
        "notices": [],
    }


def _empty_group(currency):
    return {
        "currency": currency,
        "sales_amount": "0",
        "order_count": 0,
        "valid_order_count": 0,
        "units_sold": 0,
        "ad_spend": None,
        "ad_clicks": None,
        "ad_clicks_observed_count": 0,
        "ad_clicks_partial": False,
        "ad_rate": None,
        "store_roi": None,
        "ad_status": "unverified",
        "ad_reason": "广告数据待齐，暂不计算费率。",
        "trend": [],
        "store_ranking": [],
        "sku_ranking": [],
        "ad_coverage": {"covered_store_count": 0, "expected_store_count": 0,
                        "covered_day_count": 0, "expected_day_count": 0},
        "ad_rate_sales_amount": None,
        "product_classification_note": "销量为销售明细数量，不区分主商品/套装组成；未映射分类不作推断。",
    }


def _attach_advertising(request, orders, groups, start, end, params, *, country_check_orders=None):
    # Intersect the two permissions at the store layer. This includes permitted stores
    # with advertising spend even when they had no sales in the selected period.
    candidate_stores = StoreMaster.objects.filter(tenant=request.user.tenant)
    if params.get("store_id"):
        candidate_stores = candidate_stores.filter(pk=params["store_id"])
    if params.get("platform"):
        candidate_stores = candidate_stores.filter(platform__platform_type=params["platform"])
    if params.get("region"):
        candidate_stores = candidate_stores.filter(country_code=params["region"])
    sales_scopes = get_permission_data_scopes(
        request.user, "sales_management.view", resource_code="sales_management.sales",
        cache=getattr(request, "_permission_resolution_cache", None),
    )
    if not request.user.is_superuser and not any(scope["scope_type"] == DataScope.ScopeType.ALL for scope in sales_scopes):
        sales_allowed = Q(pk__in=[])
        for scope in sales_scopes:
            if scope["scope_type"] != DataScope.ScopeType.CUSTOM:
                continue
            config = scope.get("config") or {}
            branch = Q()
            constrained = False
            for key, field in (("store_ids", "pk"), ("platforms", "platform__platform_type"), ("regions", "country_code")):
                values = config.get(key) or []
                if values:
                    branch &= Q(**{f"{field}__in": values})
                    constrained = True
            if constrained:
                sales_allowed |= branch
        candidate_stores = candidate_stores.filter(sales_allowed)

    allowed_store_ids = list(filter_advertising_stores(request.user, candidate_stores).order_by().values_list("id", flat=True))
    filters = {"date_from": start.isoformat(), "date_to": end.isoformat(), "platform": "shopee"}
    if params.get("currency"):
        filters["currency"] = params["currency"]
    authorized_ads = advertising_queryset(request, filters, "analytics.view")
    if not allowed_store_ids:
        for group in groups.values():
            group["ad_status"] = "scope_empty"
            group["ad_reason"] = "销售与 analytics 数据范围没有共同店铺。"
        return

    facts = authorized_ads.filter(
        kind="shop_daily", store_id__in=allowed_store_ids
    )
    ad_store_currency = list(StoreMaster.objects.filter(
        tenant=request.user.tenant, id__in=allowed_store_ids, platform__platform_type="shopee"
    ).order_by().values_list("id", "currency"))
    rows = list(facts.order_by().values("store_id", "currency", "report_date").annotate(
        ad_spend=Sum(_metric("expense")),
        valid_expense_count=Count(_metric("expense")),
        ad_clicks=Sum(_metric("clicks")),
        valid_clicks_count=Count(_metric("clicks")),
        fact_count=Count("pk"),
    ).order_by("store_id", "report_date", "currency"))

    country_check_orders = country_check_orders if country_check_orders is not None else orders
    country_conflicts = country_check_orders.filter(
        store_id__in=allowed_store_ids, platform__platform_type="shopee"
    ).exclude(normalized_status="cancelled").exclude(region="").filter(
        ~Q(region__iexact=F("store__country_code"))
    ).filter(currency=OuterRef("currency"))
    country_conflict_currencies = set()
    scoped_sales_by_currency = {}
    for row in orders.filter(platform__platform_type="shopee").order_by().values(
        "store_id", "currency"
    ).annotate(
        valid_order_count=Count("pk", filter=~Q(normalized_status="cancelled")),
        amount=Sum("order_total_amount", filter=~Q(normalized_status="cancelled")),
        has_country_conflict=Exists(country_conflicts.order_by().values("pk")[:1]),
    ):
        if row["valid_order_count"]:
            if row["store_id"] in allowed_store_ids:
                scoped_sales_by_currency[row["currency"]] = (
                    scoped_sales_by_currency.get(row["currency"], ZERO) + Decimal(row["amount"] or 0)
                )
        if row["has_country_conflict"]:
            country_conflict_currencies.add(row["currency"])

    by_currency = {}
    for row in rows:
        target = by_currency.setdefault(row["currency"], {"amount": Decimal("0"), "covered": set(), "valid_count": 0, "count": 0, "clicks": 0, "clicks_count": 0})
        target["count"] += row["fact_count"]
        target["covered"].add((row["store_id"], row["report_date"].isoformat()))
        target["valid_count"] += row["valid_expense_count"]
        if row["ad_spend"] is not None:
            target["amount"] += Decimal(row["ad_spend"] or 0)
        if row["ad_clicks"] is not None:
            target["clicks"] += row["ad_clicks"]
        target["clicks_count"] += row["valid_clicks_count"]

    date_count = (end - start).days + 1
    for currency, group in groups.items():
        group["ad_store_ids"] = sorted({store_id for store_id, code in ad_store_currency if code == currency})
        expected_pairs = {
            (store_id, (start + timedelta(days=offset)).isoformat())
            for store_id, store_currency_code in ad_store_currency if store_currency_code == currency
            for offset in range(date_count)
        }
        observed = by_currency.get(currency, {"amount": Decimal("0"), "covered": set(), "valid_count": 0, "count": 0, "clicks": 0, "clicks_count": 0})
        covered = expected_pairs & observed["covered"]
        coverage = group["ad_coverage"]
        coverage["covered_store_count"] = len({store for store, _ in covered})
        coverage["expected_store_count"] = len({store for store, _ in expected_pairs})
        coverage["covered_day_count"] = len({day for _, day in covered})
        coverage["expected_day_count"] = date_count
        group["ad_spend"] = _decimal_string(observed["amount"]) if observed["valid_count"] else None
        group["ad_clicks"] = observed["clicks"] if observed["clicks_count"] else None
        group["ad_clicks_observed_count"] = observed["clicks_count"]
        group["ad_clicks_partial"] = bool(observed["clicks_count"] and observed["clicks_count"] < observed["count"])
        group["ad_rate_sales_amount"] = _decimal_string(scoped_sales_by_currency.get(currency, ZERO))
        group["ad_rate_platform_scope"] = "已授权 Shopee 店铺"
        from zoneinfo import ZoneInfo
        business_today = timezone.localdate(timezone=ZoneInfo(settings.SUPPLY_CHAIN_TIME_ZONE))
        comparable = currency not in country_conflict_currencies
        if comparable and observed["valid_count"]:
            denominator = Decimal(group["ad_rate_sales_amount"])
            group["ad_rate"] = _decimal_string(observed["amount"] / denominator * 100) if denominator else None
            group["store_roi"] = _decimal_string(denominator / observed["amount"]) if observed["amount"] else None
            complete = bool(expected_pairs and expected_pairs <= observed["covered"]
                            and observed["valid_count"] == observed["count"])
            group["ad_status"] = "reference_unverified" if end < business_today and complete else "estimated"
            group["ad_reason"] = ("按已入库日报计算，后续补采可能调整。" if group["ad_status"] == "reference_unverified"
                                  else "按当前已入库广告数据暂估；部分费用字段、店铺或日期尚未拉取，补采后可能调整。")
        else:
            group["ad_status"] = "partial" if observed["covered"] else "unavailable"
            if currency in country_conflict_currencies:
                group["ad_status"] = "unavailable"
                group["ad_reason"] = "订单国家与店铺国家不一致，广告费率与整店 ROI 暂不计算。"
            elif end >= business_today:
                group["ad_reason"] = "当日广告数据尚未齐全，暂不计算费率。"
            else:
                group["ad_reason"] = "广告数据待齐，暂不计算费率。"


class RealtimeBoardView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "sales_management.view"

    def get(self, request):
        return success_response(realtime_board_payload(request))
