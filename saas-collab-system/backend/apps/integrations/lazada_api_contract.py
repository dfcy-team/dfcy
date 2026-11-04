"""Explicit read-only LazOP operations; paths and credentials are never client input."""
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime

from rest_framework.exceptions import ValidationError


@dataclass(frozen=True)
class Operation:
    name: str
    label: str
    group: str
    path: str
    required: tuple = ()
    optional: tuple = ()
    enabled: bool = True


OPERATIONS = (
    Operation("seller", "卖家身份", "店铺", "/seller/get"),
    Operation("products", "商品与库存", "商品", "/products/get", (), ("filter", "limit", "offset", "created_after", "created_before", "update_after", "update_before", "sku_seller_list")),
    Operation("product", "商品详情", "商品", "/product/item/get", ("item_id",), ("seller_sku",)),
    Operation("orders", "销售订单", "订单", "/orders/get", ("created_after", "created_before"), ("limit", "offset", "status", "sort_direction")),
    Operation("order", "订单详情", "订单", "/order/get", ("order_id",)),
    Operation("order_items", "订单商品", "订单", "/order/items/get", ("order_id",)),
    Operation("orders_items", "批量订单商品", "订单", "/orders/items/get", ("order_ids",)),
    Operation("finance", "财务流水", "财务", "/finance/transaction/details/get", ("start_time", "end_time"), ("limit", "offset", "trans_type", "trade_order_id", "trade_order_line_id")),
    Operation("payouts", "结算账单", "财务", "/finance/payout/status/get", ("created_after",)),
    Operation("account_transactions", "店铺资金流水（含广告充值）", "财务", "/finance/transaction/accountTransactions/query", ("start_time", "end_time", "page_num", "page_size"), ("transaction_type", "sub_transaction_type", "transaction_number")),
    Operation("tracking", "包裹轨迹", "物流", "/logistic/order/trace", ("order_id",)),
    Operation("shipment_providers", "可用物流商", "物流", "/order/shipment/providers/get", ("getShipmentProvidersReq",)),
    Operation("returns", "售后列表", "售后", "/reverse/getreverseordersforseller", (), ("page_size", "page_no")),
    Operation("return_detail", "售后详情", "售后", "/order/reverse/return/detail/list", ("reverse_order_id",)),
    Operation("return_history", "售后沟通历史", "售后", "/order/reverse/return/history/list", ("reverse_order_line_id",), ("page_size", "page_number")),
    Operation("return_reasons", "售后原因", "售后", "/order/reverse/reason/list", ("reverse_order_line_id",), ("request_type",)),
    Operation("ad_overview", "广告消耗汇总", "广告", "/sponsor/solutions/report/getReportOverview", ("startDate", "endDate", "lastStartDate", "lastEndDate", "bizCode", "useRtTable")),
    Operation("ad_metrics", "广告指标", "广告", "/sponsor/solutions/report/getReportOverviewMetric", ("startDate", "endDate", "bizCode", "useRtTable", "metricType")),
    Operation("smax_ad_overview", "Sponsored Max 广告汇总", "广告", "/sponsor/solution/smax/report/getReportOverview", ("startDate", "endDate", "lastStartDate", "lastEndDate", "useRtTable")),
    Operation("smax_ad_metrics", "Sponsored Max 每日指标", "广告", "/sponsor/solution/smax/report/getReportOverviewMetric", ("startDate", "endDate", "useRtTable", "metricType")),
    Operation("ad_terms", "广告协议状态（不签署）", "广告", "/sponsor/solutions/account/getAccountSignInfo"),
    Operation("campaigns", "广告计划", "广告", "/sponsor/solutions/campaign/searchCampaignList", ("startDate", "endDate", "pageNo", "pageSize", "bizCode"), ("onlineStatus",)),
    Operation("campaign", "广告计划详情", "广告", "/sponsor/solutions/campaign/getCampaign", ("campaignId", "bizCode")),
    Operation("smax_campaigns", "Sponsored Max计划（接口路径待官方确认）", "广告", "", enabled=False),
    Operation("vouchers", "优惠券列表", "营销", "/promotion/vouchers/get", ("voucher_type",), ("cur_page", "page_size", "name", "status")),
    Operation("voucher", "优惠券详情（参数契约与样本待验证）", "营销", "/promotion/voucher/get", enabled=False),
    Operation("free_shipping", "包邮活动", "营销", "/promotion/freeshippings/get", (), ("offset", "limit", "status")),
    Operation("free_shipping_detail", "包邮活动详情（参数契约与样本待验证）", "营销", "/promotion/freeshipping/get", enabled=False),
    Operation("flexi", "多件多折活动", "营销", "/promotion/flexicombo/list", (), ("offset", "limit", "status")),
    Operation("flexi_detail", "多件多折详情", "营销", "/promotion/flexicombo/details", ("id",)),
    Operation("reviews", "商品评价", "评价", "/review/seller/list", ("item_id",), ("order_id", "page_size", "current", "start_time", "end_time", "content_filter", "status_filter")),
)
BY_NAME = {item.name: item for item in OPERATIONS}


def prepare_operation(name, payload):
    operation = BY_NAME.get(name)
    if operation is None or not isinstance(payload, dict) or not operation.enabled:
        raise ValidationError("未知只读接口或参数不是对象。")
    if set(payload) - set(operation.required + operation.optional):
        raise ValidationError("包含接口未允许的参数；不能传入令牌、签名、地址或其他接口路径。")
    if any(payload.get(key) in (None, "", []) for key in operation.required):
        raise ValidationError("缺少必填参数：" + ", ".join(operation.required))
    if len(json.dumps(payload, ensure_ascii=False)) > 16384:
        raise ValidationError("单次查询参数过大。")
    for key in ("limit", "page_size", "page_no", "offset", "page_num", "page_number", "cur_page", "pageNo", "pageSize"):
        if key in payload:
            value = payload[key]
            maximum = 500 if key == "limit" else 100 if key in {"page_size", "pageSize"} else 1000000
            if type(value) is not int or not (0 if key == "offset" else 1) <= value <= maximum:
                raise ValidationError("分页参数不合法。")
    if name == "orders_items":
        ids = payload["order_ids"]
        if not isinstance(ids, list) or not 1 <= len(ids) <= 50 or any(not str(i).isdigit() for i in ids):
            raise ValidationError("批量订单号必须为1至50个数字编号。")
    if name == "account_transactions":
        try:
            dates = [payload[key] for key in ("start_time", "end_time")]
            if any(not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}", value) for value in dates):
                raise ValueError
            start, end = (datetime.strptime(value, "%Y%m%d").date() for value in dates)
            if start > end:
                raise ValueError
        except ValueError:
            raise ValidationError("账户交易日期须为有效的 YYYYMMDD，开始日期不能晚于结束日期。") from None
        for key, allowed in {
            "transaction_type": {"Deposit", "Withdrawal", "Payment"},
            "sub_transaction_type": {"Settlement", "Failed Payment", "Returned Payment", "Auto Withdrawal",
                                     "Manual Withdrawal", "Sponsored Solutions Top-up"},
        }.items():
            if key in payload and (not isinstance(payload[key], str) or payload[key] not in allowed):
                raise ValidationError("账户交易类型不在官方支持的筛选范围内。")
        if "transaction_number" in payload and (not isinstance(payload["transaction_number"], str)
                or not payload["transaction_number"].strip() or len(payload["transaction_number"]) > 191):
            raise ValidationError("交易编号须为不超过191字的非空文本。")
    query = {key: json.dumps(value, separators=(",", ":"), ensure_ascii=False)
             if isinstance(value, (dict, list, bool)) else value for key, value in payload.items()}
    return operation, query


def catalog():
    return [dict(asdict(item), method="POST" if item.name == "account_transactions" else "GET",
        verification="未验证（以所选店铺实测为准）") for item in OPERATIONS]
