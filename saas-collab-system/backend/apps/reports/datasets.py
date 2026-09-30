"""Bounded, permission-scoped report queries over business facts; no arbitrary SQL."""
import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from django.core.cache import cache
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Max, Min, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.commerce.models import InventorySnapshot, RefundReturn, SalesOrder, SalesOrderItem
from apps.finance.models import PlatformFinanceTransaction
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from apps.permissions.ui_p6_scopes import analytics_dimension_configs, filter_finance_queryset, permission_scope_configs
from apps.products.models import ProductCostVersion
from apps.sales_management.scopes import filter_sales_queryset
from apps.sales_management.views import _apply_dimensions, _inventory_latest, _inventory_source
from apps.sales_management.reporting import _local_day_expression
from apps.integrations.models import SyncRun

VERSION = "reports-v2"
MAX_GROUPS = 500
CACHE_SECONDS = 60

def field(label, source, kind="dimension", definition=""):
    return {"label": label, "source": source, "kind": kind, "definition": definition}

STORE = {"platform": field("平台", "platform__platform_type"), "store_id": field("店铺", "store_id"), "region": field("站点", "region"), "currency": field("币种", "currency")}
DATASETS = {
    "sales": {"name": "订单销售分析", "module": "销售管理", "permissions": ["sales_management.view", "analytics.view", "sales_management.stores.view"], "report_type": "sales_details", "path": "/sales-management/orders",
        "dimensions": {**STORE, "date": field("订单业务日期", "business_date"), "status": field("订单状态", "normalized_status")},
        "metrics": {"order_count": field("订单总量", Count("pk"), "count"), "valid_order_count": field("非取消订单量", Count("pk", filter=~Q(normalized_status="cancelled")), "count"), "cancelled_order_count": field("取消订单量", Count("pk", filter=Q(normalized_status="cancelled")), "count"), "gross_sales": field("非取消订单销售额", Sum("order_total_amount", filter=~Q(normalized_status="cancelled"), default=Decimal(0)), "money", "订单总金额，不含取消订单；不等于商品行销售额。")},
        "defaults": {"dimensions": ["store_id", "currency"], "metrics": ["order_count", "valid_order_count", "gross_sales"]}, "note": "订单按店铺时区筛选，金额按原币分组。销售额包含订单运费和税费，不用于计算完整利润。"},
    "sales_skus": {"name": "SKU 商品销售分析", "module": "销售管理", "permissions": ["sales_management.skus.view", "sales_management.view", "analytics.view"], "report_type": "sales_details", "path": "/sales-management/orders",
        "dimensions": {"platform": field("平台", "sales_order__platform__platform_type"), "store_id": field("店铺", "sales_order__store_id"), "region": field("站点", "sales_order__region"), "currency": field("币种", "currency"), "date": field("订单业务日期", "sales_order__business_date"), "sku": field("平台 SKU", "seller_sku"), "internal_sku": field("内部 SKU", "internal_sku__sku_code")},
        "metrics": {"order_count": field("非取消订单量", Count("sales_order_id", distinct=True), "count"), "units_sold": field("非取消商品销量", Sum("quantity"), "count"), "gross_sales": field("非取消商品销售额", Sum("line_total_amount"), "money", "商品行金额；不同于订单总金额。"), "unmapped_count": field("未关联商品行数", Count("pk", filter=Q(internal_sku__isnull=True)), "count")},
        "defaults": {"dimensions": ["store_id", "sku", "currency"], "metrics": ["units_sold", "gross_sales", "unmapped_count"]}, "note": "排除取消订单；未关联商品保留平台 SKU。订单数按每个分组去重，不能将跨 SKU 的订单数相加。"},
    "refunds": {"name": "退款退货分析", "module": "销售管理", "permissions": ["sales_management.returns.view", "sales_management.view", "analytics.view"], "report_type": "sales_details", "path": "/sales-management/returns",
        "dimensions": {**STORE, "region": field("站点", "store__country_code"), "date": field("申请日期（店铺时区）", TruncDate("requested_at_utc", tzinfo=UTC)), "status": field("售后状态", "normalized_status")},
        "metrics": {"case_count": field("售后申请量", Count("pk"), "count"), "requested_amount": field("退款申请金额", Sum("refund_amount"), "money"), "completed_amount": field("已完成退款金额", Sum("refund_amount", filter=Q(normalized_status="completed"), default=Decimal(0)), "money", "仅 completed 状态；accepted 不视为资金退款完成。"), "unlinked_count": field("未关联订单量", Count("pk", filter=Q(sales_order__isnull=True)), "count")},
        "defaults": {"dimensions": ["store_id", "status", "currency"], "metrics": ["case_count", "requested_amount", "completed_amount", "unlinked_count"]}, "note": "申请金额与已完成退款金额分列；已完成状态仍需通过结算或银行流水核对资金到账。"},
    "inventory": {"name": "库存快照分析", "module": "库存管理", "permissions": ["sales_management.view", "analytics.view"], "report_type": "analytics_summary", "path": "/analytics/inventory",
        "dimensions": {"warehouse_id": field("仓库", "warehouse_id"), "site_code": field("站点", "site_code"), "sku": field("来源 SKU", "source_sku"), "internal_sku": field("内部 SKU", "internal_sku__sku_code"), "inventory_type": field("商品类型", "internal_sku__inventory_type")},
        "metrics": {"sku_count": field("仓库 SKU 数", Count("pk"), "count"), "on_hand": field("在手库存", Sum("on_hand_qty"), "count"), "available": field("可用库存", Sum("available_qty"), "count"), "reserved": field("锁定库存", Sum("reserved_qty"), "count"), "unmapped_count": field("未关联 SKU 数", Count("pk", filter=Q(internal_sku__isnull=True)), "count"), "out_count": field("缺货 SKU 数", Count("pk", filter=Q(available_qty__lte=0)), "count")},
        "defaults": {"dimensions": ["warehouse_id", "site_code"], "metrics": ["sku_count", "on_hand", "available", "unmapped_count"]}, "note": "每个站点、仓库、来源 SKU 取截止时点最后一条快照，默认排除已知虚拟商品。快照差额不代表出入库流水。"},
    "finance": {"name": "平台流水与费用分析", "module": "财务中心", "permissions": ["finance.view"], "report_type": "finance_summary", "path": "/finance/statements",
        "dimensions": {"platform": field("平台", "platform"), "store_id": field("店铺", "store_id"), "currency": field("币种", "currency"), "date": field("业务日期", "business_date"), "fee_category": field("费用分类", "fee_category"), "match_status": field("匹配状态", "match_status"), "fee_name": field("来源费用名称", "raw_fee_name")},
        "metrics": {"transaction_count": field("流水条数", Count("pk"), "count"), "signed_amount": field("流水净额", Sum("signed_amount"), "money", "保留来源正负号；不是完整利润。"), "unmatched_count": field("未匹配流水数", Count("pk", filter=Q(match_status__in=["unmatched", "conflict"])), "count"), "unknown_count": field("未分类流水数", Count("pk", filter=Q(fee_category="other")), "count")},
        "defaults": {"dimensions": ["fee_category", "currency"], "metrics": ["transaction_count", "signed_amount", "unmatched_count", "unknown_count"]}, "note": "只分析已采集流水，不代表完整结算收入、利润或银行回款。其他费用须核对来源名称后分类。"},
}
DATASETS["inventory_value"] = {**DATASETS["inventory"], "name": "库存估值与成本覆盖", "module": "财务中心", "report_type": "finance_summary", "extra_permissions": ["finance.view", "products.cost.view"],
    "dimensions": {**DATASETS["inventory"]["dimensions"], "currency": field("成本币种", "cost_currency")},
    "metrics": {**DATASETS["inventory"]["metrics"], "valued_count": field("有已确认成本 SKU 数", Count("pk", filter=Q(unit_cost__isnull=False)), "count"), "missing_cost_count": field("缺已确认成本 SKU 数", Count("pk", filter=Q(unit_cost__isnull=True)), "count"), "zero_cost_count": field("已确认零成本 SKU 数", Count("pk", filter=Q(unit_cost=0)), "count"), "inventory_value": field("已覆盖库存货值", Sum(ExpressionWrapper(F("on_hand_qty") * F("unit_cost"), output_field=DecimalField(max_digits=24, decimal_places=4))), "money", "在手数量乘截止时点、对应仓库的已确认成本；缺成本单列，不按零补齐。")},
    "defaults": {"dimensions": ["warehouse_id", "currency"], "metrics": ["sku_count", "valued_count", "missing_cost_count", "inventory_value"]}, "note": "库存与成本均按截止时点查询；仅估值有已确认成本的库存，未知成本币种单列。此结果不是订单利润或财务总账余额。"}

FILTER_KEYS = {"date_from", "date_to", "platform", "platforms", "store_id", "store_ids", "region", "currency", "sku", "warehouse_id", "site_code", "include_virtual", "unmapped_only", "inventory_type", "raw_fee_name", "status", "fee_category", "match_status", "external_order_id"}
DATASET_FILTERS = {
    "sales": ["date_from", "date_to", "platform", "store_id", "region", "currency", "sku", "status", "external_order_id", "unmapped_only"],
    "sales_skus": ["date_from", "date_to", "platform", "store_id", "region", "currency", "sku", "unmapped_only"],
    "refunds": ["date_from", "date_to", "platform", "store_id", "region", "currency", "sku", "status", "external_order_id", "unmapped_only"],
    "finance": ["date_from", "date_to", "platform", "store_id", "currency", "fee_category", "match_status", "external_order_id", "raw_fee_name"],
    "inventory": ["date_to", "warehouse_id", "site_code", "sku", "inventory_type", "unmapped_only"],
    "inventory_value": ["date_to", "warehouse_id", "site_code", "sku", "currency", "inventory_type", "unmapped_only", "cost_status"],
}

def selected_permission(user, dataset):
    if not user or not user.is_authenticated or not user.is_active or user.user_type != "internal":
        raise PermissionDenied("需要内部用户权限。")
    for code in dataset.get("extra_permissions", []):
        if not check_user_permission(user, code) or not get_permission_data_scopes(user, code):
            raise PermissionDenied(f"需要 {code} 权限及数据范围。")
    for code in dataset["permissions"]:
        if check_user_permission(user, code) and get_permission_data_scopes(user, code):
            return code
    raise PermissionDenied("没有此数据集的业务查看权限及数据范围。")

def normalize_config(raw):
    if not isinstance(raw, dict) or set(raw) - {"dataset", "dimensions", "metrics", "filters", "chart", "chart_metric", "pivot", "ordering"} or not isinstance(raw.get("dataset"), str):
        raise ValidationError("报表配置格式不正确。")
    dataset = DATASETS.get(raw.get("dataset"))
    if not dataset:
        raise ValidationError("请选择可用的数据集。")
    config = {"dataset": raw["dataset"], "dimensions": raw.get("dimensions", dataset["defaults"]["dimensions"]), "metrics": raw.get("metrics", dataset["defaults"]["metrics"]), "filters": raw.get("filters", {}), "chart": raw.get("chart", "table"), "pivot": raw.get("pivot", ""), "ordering": raw.get("ordering", "")}
    for key, allowed, maximum in [("dimensions", dataset["dimensions"], 6), ("metrics", dataset["metrics"], 8)]:
        values = config[key]
        if not isinstance(values, list) or not values or len(values) > maximum or any(not isinstance(v, str) or v not in allowed for v in values) or len(set(values)) != len(values):
            raise ValidationError({key: "请选择有效且不重复的维度或指标。"})
    filters = config["filters"]
    allowed_filters = set(DATASET_FILTERS[config["dataset"]])
    if config["dataset"].startswith("inventory"):
        allowed_filters.add("include_virtual")
    else:
        allowed_filters.update({"platforms", "store_ids"})
    if not isinstance(filters, dict) or set(filters) - allowed_filters:
        raise ValidationError({"filters": "存在不支持的筛选条件。"})
    if any(not isinstance(v, (str, int, bool)) or len(str(v)) > 300 or "\x00" in str(v) for v in filters.values()):
        raise ValidationError({"filters": "筛选值格式不正确。"})
    for key in ("date_from", "date_to"):
        if filters.get(key):
            try:
                date.fromisoformat(str(filters[key]))
            except ValueError as exc:
                raise ValidationError({key: "日期格式应为 YYYY-MM-DD。"}) from exc
    if filters.get("date_from") and filters.get("date_to") and filters["date_from"] > filters["date_to"]:
        raise ValidationError("开始日期不能晚于结束日期。")
    for key in ("store_id", "warehouse_id"):
        if filters.get(key) and (not str(filters[key]).isascii() or not str(filters[key]).isdigit() or not 0 < int(filters[key]) < 2**63):
            raise ValidationError({key: "标识应为正整数。"})
    if filters.get("store_ids") and any(not v.isascii() or not v.isdigit() or not 0 < int(v) < 2**63 for v in str(filters["store_ids"]).split(",")):
        raise ValidationError({"store_ids": "店铺标识应为逗号分隔的正整数。"})
    if "include_virtual" in filters and str(filters["include_virtual"]).lower() not in {"true", "false", "1", "0"}:
        raise ValidationError({"include_virtual": "请选择是否包含虚拟商品。"})
    if "unmapped_only" in filters and str(filters["unmapped_only"]).lower() not in {"true", "false", "1", "0"}:
        raise ValidationError({"unmapped_only": "请选择是否只看未关联商品。"})
    if filters.get("inventory_type") not in (None, "", "physical", "virtual", "unknown"):
        raise ValidationError({"inventory_type": "商品类型不正确。"})
    if filters.get("cost_status") not in (None, "", "missing", "confirmed", "zero"):
        raise ValidationError({"cost_status": "成本状态不正确。"})
    if any(not isinstance(config[key], str) for key in ("chart", "pivot", "ordering")) or config["chart"] not in {"table", "bar", "line", "pivot"} or config["pivot"] not in ["", *config["dimensions"]]:
        raise ValidationError("图表或透视维度不正确。")
    if config["ordering"] and config["ordering"].lstrip("-") not in config["dimensions"] + config["metrics"]:
        raise ValidationError("排序字段不正确。")
    if raw.get("chart_metric") is not None:
        if raw["chart_metric"] not in config["metrics"]:
            raise ValidationError("图表指标不在已选指标范围内。")
        config["chart_metric"] = raw["chart_metric"]
    # Currency is mandatory whenever a monetary measure is requested.
    if any(dataset["metrics"][key]["kind"] == "money" for key in config["metrics"]) and "currency" not in config["dimensions"]:
        config["dimensions"] = [*config["dimensions"], "currency"]
    if len(config["dimensions"]) > 6:
        raise ValidationError({"dimensions": "最多选择 6 个维度，金额报表须预留币种维度。"})
    return config

def scope_fingerprint(user, dataset, permission):
    codes = sorted(set([permission, *dataset.get("extra_permissions", [])]))
    return {code: get_permission_data_scopes(user, code) for code in codes}

def _analytics_scope(user, queryset, dataset_id, permission):
    if permission != "analytics.view":
        return filter_sales_queryset(user, permission, queryset)
    configs = analytics_dimension_configs(user, permission)
    if configs is None:
        return queryset
    allowed = Q(pk__in=[])
    mapping = {"platform": "platform__platform_type", "store_id": "store_id", "country": "store__country_code" if dataset_id == "refunds" else "region"}
    for config in configs:
        # SKU/product scopes constrain order lines; warehouse-only scopes cannot grant orders.
        condition = Q()
        for key, value in config.items():
            if key in mapping:
                condition &= Q(**{mapping[key]: value})
            elif key in {"sku_id", "product_id"}:
                prefix = "items__internal_sku_id" if key == "sku_id" else "items__internal_sku__spu_id" if dataset_id == "refunds" else "items__internal_spu_id"
                condition &= Q(**{prefix: value})
            else:
                condition &= Q(pk__in=[])
        allowed |= condition
    return queryset.filter(pk__in=Subquery(queryset.filter(allowed).values("pk")))

def source_queryset(request, config, permission):
    name, filters = config["dataset"], config["filters"]
    user = request.user
    if name in {"sales", "sales_skus", "refunds"}:
        model = RefundReturn if name == "refunds" else SalesOrder
        qs = _analytics_scope(user, model.objects.filter(tenant=user.tenant), name, permission)
        qs = _apply_dimensions(qs, request, date_field="requested_at_utc" if name == "refunds" else "created_at_utc", region_field="store__country_code" if name == "refunds" else "region")
        if filters.get("status"):
            qs = qs.filter(normalized_status=filters["status"])
        if filters.get("external_order_id"):
            qs = qs.filter(**{"sales_order__external_order_id" if name == "refunds" else "external_order_id": filters["external_order_id"]})
        if name == "sales_skus":
            qs = SalesOrderItem.objects.filter(tenant=user.tenant, sales_order__in=qs.exclude(normalized_status="cancelled"))
            if permission == "analytics.view":
                configs = analytics_dimension_configs(user, permission)
                if configs is not None:
                    allowed = Q(pk__in=[])
                    for branch in configs:
                        condition = Q()
                        fields = {"platform": "sales_order__platform__platform_type", "store_id": "sales_order__store_id", "country": "sales_order__region", "sku_id": "internal_sku_id", "product_id": "internal_spu_id"}
                        for key, value in branch.items():
                            condition &= Q(**{fields[key]: value}) if key in fields else Q(pk__in=[])
                        allowed |= condition
                    qs = qs.filter(allowed)
        if filters.get("sku"):
            prefix = "" if name == "sales_skus" else "items__"
            matched = qs.filter(Q(**{prefix + "seller_sku": filters["sku"]}) | Q(**{prefix + "internal_sku__sku_code": filters["sku"]}))
            qs = qs.filter(pk__in=Subquery(matched.values("pk")))
        if str(filters.get("unmapped_only", "false")).lower() in {"true", "1"}:
            prefix = "" if name == "sales_skus" else "items__"
            matched = qs.filter(**{prefix + "internal_sku__isnull": True})
            qs = qs.filter(pk__in=Subquery(matched.values("pk")))
        return qs.distinct().order_by()
    if name == "finance":
        qs = filter_finance_queryset(user, PlatformFinanceTransaction.objects.filter(tenant=user.tenant), permission)
        for key in ("platform", "store_id", "currency", "fee_category", "match_status", "external_order_id", "raw_fee_name"):
            if filters.get(key):
                qs = qs.filter(**{key: filters[key]})
        for key, lookup in (("platforms", "platform__in"), ("store_ids", "store_id__in")):
            if filters.get(key):
                qs = qs.filter(**{lookup: str(filters[key]).split(",")})
        for key, lookup in (("date_from", "business_date__gte"), ("date_to", "business_date__lte")):
            if filters.get(key):
                qs = qs.filter(**{lookup: filters[key]})
        return qs.order_by()
    source = _inventory_source(request, permission) if permission != "analytics.view" else InventorySnapshot.objects.filter(tenant=user.tenant, source_run_id__in=SyncRun.objects.filter(tenant=user.tenant, sync_job__integration_config__platform="jifeng_wms", sync_job__resource_type="inventory_snapshot").values("pk")).order_by()
    inventory_scope = None
    if permission == "analytics.view":
        configs = analytics_dimension_configs(user, permission)
        if configs is not None:
            allowed = Q(pk__in=[])
            for branch in configs:
                condition = Q()
                fields = {"country": "site_code", "warehouse_id": "warehouse_id", "sku_id": "internal_sku_id", "product_id": "internal_sku__spu_id"}
                for key, value in branch.items():
                    condition &= Q(**{fields[key]: value}) if key in fields else Q(pk__in=[])
                allowed |= condition
            inventory_scope = allowed
    at = datetime.combine(date.fromisoformat(filters["date_to"]) + timedelta(days=1), time.min, tzinfo=UTC) - timedelta(microseconds=1) if filters.get("date_to") else timezone.now()
    qs = _inventory_latest(source.filter(snapshot_at_utc__lte=at))
    if inventory_scope is not None:
        qs = qs.filter(inventory_scope)
    if str(filters.get("include_virtual", "false")).lower() not in {"true", "1"}:
        qs = qs.exclude(internal_sku__inventory_type="virtual")
    for key in ("warehouse_id", "site_code"):
        if filters.get(key):
            qs = qs.filter(**{key: filters[key]})
    if filters.get("sku"):
        qs = qs.filter(Q(source_sku=filters["sku"]) | Q(internal_sku__sku_code=filters["sku"]))
    if str(filters.get("unmapped_only", "false")).lower() in {"true", "1"}:
        qs = qs.filter(internal_sku__isnull=True)
    if filters.get("inventory_type") == "unknown":
        qs = qs.filter(Q(internal_sku__inventory_type__isnull=True) | Q(internal_sku__inventory_type=""))
    elif filters.get("inventory_type"):
        qs = qs.filter(internal_sku__inventory_type=filters["inventory_type"])
    if name == "inventory_value":
        # Cost access uses an explicit product permission; restrict costs and inventory
        # to that scope instead of treating a saved view as a new grant.
        cost_scopes = permission_scope_configs(user, "products.cost.view", {"sku_ids", "spu_ids", "warehouse_ids"})
        if cost_scopes is not None:
            allowed = Q(pk__in=[])
            for branch in cost_scopes:
                fields = {"sku_ids": "internal_sku_id", "spu_ids": "internal_sku__spu_id", "warehouse_ids": "warehouse_id"}
                condition = Q()
                for key, values in branch.items():
                    condition &= Q(**{fields[key] + "__in": values})
                allowed |= condition
            qs = qs.filter(allowed)
        costs = ProductCostVersion.objects.filter(tenant=user.tenant, sku_id=OuterRef("internal_sku_id"), warehouse_id=OuterRef("warehouse_id"), status="confirmed", effective_from__lte=at).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=at)).order_by("-effective_from", "-version_no")
        qs = qs.annotate(unit_cost=Subquery(costs.values("confirmed_cost")[:1]), cost_currency=Subquery(costs.values("currency")[:1]))
        finance_scopes = permission_scope_configs(user, "finance.view", {"platforms", "currencies"})
        if finance_scopes is not None:
            # A platform-limited finance grant cannot reveal warehouse-wide stock.
            allowed = Q(pk__in=[])
            for branch in finance_scopes:
                if "platforms" not in branch:
                    allowed |= Q(cost_currency__in=branch["currencies"]) if "currencies" in branch else Q()
            qs = qs.filter(allowed)
        if filters.get("currency"):
            qs = qs.filter(cost_currency=filters["currency"])
        if filters.get("cost_status") == "missing":
            qs = qs.filter(unit_cost__isnull=True)
        elif filters.get("cost_status") == "confirmed":
            qs = qs.filter(unit_cost__isnull=False)
        elif filters.get("cost_status") == "zero":
            qs = qs.filter(unit_cost=0)
    return qs.order_by()

def query_dataset(request, raw, *, limit=MAX_GROUPS, use_cache=True, export_scope=None):
    config = normalize_config(raw)
    dataset = DATASETS[config["dataset"]]
    permission = selected_permission(request.user, dataset)
    # Pass only validated strings to the existing dimension/date parser.
    from types import SimpleNamespace
    from django.http import QueryDict
    params = QueryDict(mutable=True)
    params.update({k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in config["filters"].items()})
    proxy = SimpleNamespace(user=request.user, query_params=params)
    fingerprint = scope_fingerprint(request.user, dataset, permission)
    key = "report:" + hashlib.sha256(json.dumps([VERSION, request.user.tenant_id, request.user.pk, fingerprint, config, limit], sort_keys=True, default=str).encode()).hexdigest()
    result = cache.get(key) if use_cache else None
    if result is not None:
        return {**result, "cached": True}
    qs = source_queryset(proxy, config, permission)
    if export_scope:
        if config["dataset"] == "finance":
            qs = filter_finance_queryset(request.user, qs, export_scope)
        elif config["dataset"] in {"sales", "refunds", "sales_skus"}:
            fields = {"store_ids": "sales_order__store_id", "platforms": "sales_order__platform__platform_type", "regions": "sales_order__region"} if config["dataset"] == "sales_skus" else {"store_ids": "store_id", "platforms": "platform__platform_type", "regions": "store__country_code" if config["dataset"] == "refunds" else "region"}
            qs = filter_sales_queryset(request.user, export_scope, qs, fields)
        elif config["dataset"] == "inventory_value":
            scopes = permission_scope_configs(request.user, export_scope, {"platforms", "currencies"})
            if scopes is not None:
                allowed = Q(pk__in=[])
                for branch in scopes:
                    if "platforms" not in branch:
                        allowed |= Q(cost_currency__in=branch["currencies"]) if "currencies" in branch else Q()
                qs = qs.filter(allowed)
    aliases = {key: "d_" + key for key in config["dimensions"]}
    expressions = {alias: F(dataset["dimensions"][key]["source"]) if isinstance(dataset["dimensions"][key]["source"], str) else dataset["dimensions"][key]["source"] for key, alias in aliases.items()}
    if "date" in aliases and config["dataset"] in {"sales", "sales_skus", "refunds"}:
        prefix = "sales_order__" if config["dataset"] == "sales_skus" else ""
        timestamp = "requested_at_utc" if config["dataset"] == "refunds" else prefix + "created_at_utc"
        expressions["d_date"] = _local_day_expression(qs, timestamp, prefix + "store__timezone")
    qs = qs.annotate(**expressions)
    grouped = qs.values(*aliases.values()).annotate(**{"m_" + key: dataset["metrics"][key]["source"] for key in config["metrics"]})
    ordering = config["ordering"]
    sort = ("-" if ordering.startswith("-") else "") + (("d_" if ordering.lstrip("-") in aliases else "m_") + ordering.lstrip("-")) if ordering else next(iter(aliases.values()))
    raw_rows = list(grouped.order_by(sort, *[a for a in aliases.values() if a != sort.lstrip("-")])[:limit + 1])
    truncated = len(raw_rows) > limit
    rows = [{**{key: row[alias] for key, alias in aliases.items()}, **{key: str(row["m_" + key]) if isinstance(row["m_" + key], Decimal) else row["m_" + key] for key in config["metrics"]}} for row in raw_rows[:limit]]
    refreshed_field = "sales_order__updated_at_utc" if config["dataset"] == "sales_skus" else "snapshot_at_utc" if config["dataset"].startswith("inventory") else "updated_at" if config["dataset"] == "finance" else "updated_at_utc"
    freshness = qs.aggregate(refreshed_at=Max(refreshed_field))
    result = {"api_status": "connected", "config": config, "rows": rows, "count": len(rows), "truncated": truncated, "limit": limit, "metric_version": VERSION, "refreshed_at": freshness["refreshed_at"], "computed_at": timezone.now(), "cache_seconds": CACHE_SECONDS, "cached": False, "note": dataset["note"], "columns": [{"key": k, "label": dataset["dimensions"].get(k, dataset["metrics"].get(k))["label"], "kind": dataset["dimensions"].get(k, dataset["metrics"].get(k))["kind"]} for k in config["dimensions"] + config["metrics"]]}
    if use_cache:
        cache.set(key, result, CACHE_SECONDS)
    return result

def dataset_catalog(user):
    entries = []
    for key, dataset in DATASETS.items():
        try:
            selected_permission(user, dataset)
        except PermissionDenied:
            continue
        entries.append({"id": key, "filters": DATASET_FILTERS[key], **{k: dataset[k] for k in ("name", "module", "path", "note", "defaults", "report_type")}, "dimensions": [{"key": k, **{p: v[p] for p in ("label", "kind", "definition")}} for k, v in dataset["dimensions"].items()], "metrics": [{"key": k, **{p: v[p] for p in ("label", "kind", "definition")}} for k, v in dataset["metrics"].items()]})
    return entries
