"""Apifox 3972134 business operations, inspected 2026-10-26.

The catalog is not an authorization grant. OAuth continues through the existing
warehouse credential service; empty documentation folders are not operations.
"""
import json
from dataclasses import asdict, dataclass

from rest_framework.exceptions import ValidationError


@dataclass(frozen=True)
class WarehouseOperation:
    name: str
    label: str
    path: str
    group: str
    write: bool = False
    method: str = "POST"


OPERATIONS = (
    WarehouseOperation("logistics_price", "获取物流费用", "/api/logistics/price", "物流"),
    WarehouseOperation("logistics_offline_page", "获取客户物流渠道", "/api/logistics/offline/page", "物流"),
    WarehouseOperation("logistics_online_page", "获取物流方式信息", "/api/logistics/online/page", "物流"),
    WarehouseOperation("order_create", "创建订单", "/api/order/create", "订单", True),
    WarehouseOperation("order_cancel", "取消订单", "/api/order/cancel", "订单", True),
    WarehouseOperation("order_get", "查询订单", "/api/order/get", "订单"),
    WarehouseOperation("order_page", "分页查询订单", "/api/order/page", "订单"),
    WarehouseOperation("sku_create", "创建商品SKU", "/api/sku/create", "商品", True),
    WarehouseOperation("sku_update", "更新商品SKU", "/api/sku/update", "商品", True),
    WarehouseOperation("sku_detail", "获取商品详情", "/api/sku/detail", "商品"),
    WarehouseOperation("sku_age_list", "查询商品库龄列表", "/api/sku/age/list", "商品"),
    WarehouseOperation("inventory_query", "查询商品库存", "/api/inventory/queryInventory", "库存"),
    WarehouseOperation("inventory_inout", "查询库存流水", "/api/inventory/inout/list", "库存"),
    WarehouseOperation("warehouse_list", "获取用户仓库详情", "/api/warehouse/getList", "仓库"),
    WarehouseOperation("inbound_create", "创建入库单", "/api/inbound/create", "入库", True),
    WarehouseOperation("inbound_cancel", "取消入库单", "/api/inbound/cancel", "入库", True),
    WarehouseOperation("inbound_get", "查询入库单", "/api/inbound/get", "入库"),
    WarehouseOperation("inbound_page", "分页查询标准入库单详情", "/api/inbound/page", "入库"),
    WarehouseOperation("inbound_tracking_update", "更新入库单物流单号", "/api/inbound/tracking/update", "入库", True),
    WarehouseOperation("inbound_print", "打印箱唛", "/api/inbound/printBoxLabel", "入库", True),
    WarehouseOperation("return_create", "创建退货单", "/api/inbound/return/create", "退货", True),
    WarehouseOperation("return_cancel", "取消退货单", "/api/inbound/return/cancel", "退货", True),
    WarehouseOperation("return_get", "查询单个退货单详情", "/api/inbound/return/getSingle", "退货"),
    WarehouseOperation("customer_distribution", "校验客户是否为分销商", "/api/oms/user/distribution", "客户"),
    WarehouseOperation("b2b_outbound_create", "创建B2B出库单", "/api/b2b/outbound/create", "B2B", True),
    WarehouseOperation("b2b_outbound_get", "查询B2B出库单", "/api/b2b/outbound/get", "B2B"),
    WarehouseOperation("b2b_outbound_cancel", "取消B2B出库单", "/api/b2b/outbound/cancel", "B2B", True),
    WarehouseOperation("b2b_inbound_create", "创建B2B入库单", "/api/b2b/inbound/create", "B2B", True),
    WarehouseOperation("b2b_inbound_get", "查询B2B入库单", "/api/b2b/inbound/get", "B2B"),
    WarehouseOperation("b2b_inbound_print", "打印B2B箱唛", "/api/b2b/inbound/print", "B2B", True),
    WarehouseOperation("b2b_inbound_tracking_update", "更新B2B入库单运单号", "/api/b2b/inbound/tracking/update", "B2B", True),
    WarehouseOperation("b2b_inbound_cancel", "取消B2B入库单", "/api/b2b/inbound/cancel", "B2B", True),
    WarehouseOperation("b2b_inventory", "查询箱子库存", "/api/b2b/inventory/queryB2bInventory", "B2B"),
    WarehouseOperation("direct_order_update", "更新直邮订单", "/api/order/y2/updateDetail", "直邮", True),
    WarehouseOperation("direct_order_nullify", "作废直邮订单", "/api/order/y2/nullify", "直邮", True),
    WarehouseOperation("direct_order_create", "创建直邮订单", "/api/order/y2/create", "直邮", True),
    WarehouseOperation("direct_order_label_update", "更新直邮订单运单号、面单", "/api/order/y2/updateLabel", "直邮", True),
    WarehouseOperation("direct_order_detail", "查看直邮订单详情", "/api/order/y2/detail", "直邮", method="GET"),
    WarehouseOperation("direct_order_print", "打印直邮标签", "/api/order/y2/print", "直邮", True),
)
OPERATION_MAP = {operation.name: operation for operation in OPERATIONS}
SENSITIVE_KEYS = {"accesstoken", "refreshtoken", "clientsecret", "clientid", "userid", "sign", "password", "authorization", "cookie"}


def operation_for(name):
    if not isinstance(name, str) or name not in OPERATION_MAP:
        raise ValidationError("未知仓库接口；只允许调用已登记的操作，不能传入URL。")
    return OPERATION_MAP[name]


def prepare_operation(name, payload):
    operation = operation_for(name)
    if not isinstance(payload, (dict, list)):
        raise ValidationError("业务参数必须是JSON对象或数组。")
    try:
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise ValidationError("业务参数不是有效JSON。") from None
    if len(encoded.encode("utf-8")) > 512 * 1024:
        raise ValidationError("业务参数超过512KiB。")

    def inspect(value, depth=0):
        if depth > 20:
            raise ValidationError("业务参数嵌套层级过深。")
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str) or key.replace("_", "").lower() in SENSITIVE_KEYS:
                    raise ValidationError("鉴权字段必须由服务端托管注入，不能放入业务参数。")
                inspect(item, depth + 1)
        elif isinstance(value, list):
            for item in value:
                inspect(item, depth + 1)

    inspect(payload)
    selectors = {"order_get": ("erpNo", "platformOrderNo"), "return_get": ("erpNo", "returnNo", "trackingNo")}
    if name in selectors:
        keys = selectors[name]
        if not isinstance(payload, dict) or len(payload) != 1 or next(iter(payload), None) not in keys:
            raise ValidationError("查询须且只能提供一个单号字段。")
        value = next(iter(payload.values()))
        if not isinstance(value, str) or not value.strip() or len(value) > 191 or any(ord(c) < 32 for c in value):
            raise ValidationError("查询单号必须是有效文本。")
    if operation.method == "GET" and (not isinstance(payload, dict) or any(isinstance(v, (dict, list)) for v in payload.values())):
        raise ValidationError("GET查询参数必须是标量键值对象。")
    return {**asdict(operation), "payload": json.loads(encoded), "execution_enabled": False,
            "validation": "本地结构预检；非仓库参数验收", "requires_confirmation": operation.write}
