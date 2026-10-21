"""Shared published contract registry for the four business domains."""
from datetime import date

from rest_framework.exceptions import ValidationError
from . import readonly_advertising, readonly_finance, readonly_sales_inventory

MODULES = (readonly_sales_inventory, readonly_finance, readonly_advertising)
CONTRACTS = {code: contract for module in MODULES for code, contract in module.CONTRACTS.items()}
NOTES = {
    "sales_overview": "按业务日期、平台、店铺、币种汇总非取消订单金额和订单数；不是扣退款后的净销售额。",
    "store_sales": "按业务日期、平台、店铺、币种汇总非取消订单金额和订单数。退款由退款退货数据块单独读取。",
    "sku_sales": "按日期、店铺、SKU、币种汇总非取消订单商品行，不扣退款。",
    "inventory_workbench": "按站点、仓库、来源 SKU 取最新快照；未由源系统提供的数量见 provided_quantity_fields，不能将默认 0 当成已采集值。",
    "inventory_snapshots": "历史库存快照；数量采集完整性见 provided_quantity_fields。",
    "prices": "店铺商品价格快照：原价、促销价、有效价；不是供应商采购报价。",
    "sales_exports": "已存在的销售导出任务状态与行数；不触发导出，不提供内部文件路径。商品明细请读取 sales_order_items。",
    "sales_data_quality": "历史销售同步质量检查；同步运行计数另见 sales_sync_runs。",
    "inventory_inbounds": "仓储入库单行，不代表全部库存变动流水。",
    "inventory_shipments": "仓储发运单行，不代表调拨或盘点流水。",
    "finance_imports": "历史财务 CSV 导入批次的类型与成功/跳过行数；不触发导入。",
    "finance_analytics": "按账期、平台、币种汇总账单原额、已确认匹配金额和未解决异常；不混合币种。",
    "finance_transactions": "平台财务费用明细；raw_amount 为源金额，signed_amount 为标准化带符号金额，不能与账单总额重复相加。",
    **readonly_advertising.NOTES,
}
PENDING_REASONS = readonly_advertising.PENDING_REASONS

DATE_FIELDS = {
    "sales_orders": "business_date", "sales_overview": "business_date", "store_sales": "business_date",
    "sku_sales": "business_date", "sales_returns": "requested_at_utc__date",
    "sales_order_items": "sales_order__business_date", "sales_return_items": "refund_return__requested_at_utc__date",
    "operating_orders_v2": "order_date", "operating_order_items": "order__order_date",
    "inventory_snapshots": "snapshot_at_utc__date", "inventory_workbench": "snapshot_at_utc__date",
    "inventory_inbounds": "updated_at_utc__date", "inventory_shipments": "updated_at_utc__date",
    "inventory_alerts": "triggered_at__date", "replenishment_suggestions": "suggested_date",
    "sales_exports": "requested_at__date", "sales_sync_runs": "started_at__date",
    "sales_data_quality": "sync_log__started_at__date", "prices": "imported_at__date",
    "advertising_overview": "report_date", "advertising_performance": "report_date", "advertising_tiktok_spend": "date",
    "finance_imports": "created_at__date", "finance_analytics": "period_start", "platform_statements": "period_start",
    "withdrawal_records": "requested_at__date", "bank_receipts": "receipt_date",
    "reconciliation_matches": "statement__period_start", "reconciliation_exceptions": "created_at__date",
    "finance_transactions": "business_date",
}


def filter_fields(resource):
    """Only named contract dimensions can become caller-controlled filters."""
    fields = CONTRACTS[resource][1]
    result = {field: field for field in ("id", "store_id", "warehouse_id", "sales_order_id", "refund_return_id", "currency") if field in fields}
    if "internal_sku_id" in fields:
        result["sku_id"] = "internal_sku_id"
    elif "sku_id" in fields:
        result["sku_id"] = "sku_id"
    if resource == "sales_order_items":
        result["store_id"] = "sales_order__store_id"
    elif resource == "sales_return_items":
        result["store_id"] = "refund_return__store_id"
    return result


def apply_filters(queryset, resource, params):
    allowed = filter_fields(resource)
    unknown = set(params) - set(allowed) - {"limit", "cursor", "date_from", "date_to"}
    if unknown:
        raise ValidationError({"filters": "Unsupported query parameters: " + ", ".join(sorted(unknown))})
    for name, field in allowed.items():
        if name not in params:
            continue
        value = params[name]
        if name.endswith("_id") or name == "id":
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise ValidationError({name: "Must be a positive integer."})
            if not 0 < value <= 9223372036854775807:
                raise ValidationError({name: "Must be a positive integer."})
        elif not value or len(value) > 12:
            raise ValidationError({name: "Invalid currency."})
        queryset = queryset.filter(**{field: value})
    dates = {}
    for name in ("date_from", "date_to"):
        if name in params:
            try:
                dates[name] = date.fromisoformat(params[name])
            except (TypeError, ValueError):
                raise ValidationError({name: "Use YYYY-MM-DD."})
    if len(dates) == 2 and dates["date_from"] > dates["date_to"]:
        raise ValidationError({"date_to": "Must not precede date_from."})
    for name, value in dates.items():
        queryset = queryset.filter(**{DATE_FIELDS[resource] + ("__gte" if name == "date_from" else "__lte"): value})
    return queryset


def query(resource, tenant_id):
    for module in MODULES:
        if resource in module.CONTRACTS:
            return module.query(resource, tenant_id)
    raise KeyError(resource)


def transform(resource, item):
    for module in MODULES:
        if resource in module.CONTRACTS and hasattr(module, "transform"):
            module.transform(resource, item)
