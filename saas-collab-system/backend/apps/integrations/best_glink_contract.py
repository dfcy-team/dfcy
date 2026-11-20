"""Public GLINK contract snapshot. Request and callback directions stay separate."""
import json
from pathlib import Path
from rest_framework.exceptions import ValidationError

CATALOG = json.loads(Path(__file__).with_name("best_glink_catalog.json").read_text(encoding="utf-8"))
CONTRACTS = {item["name"]: item for item in CATALOG["operations"]}
CALLBACKS = {name: item for name, item in CONTRACTS.items() if item["direction"] == "callback"}


def validate_fields(name, data, *, callback=False):
    contract = CONTRACTS.get(name)
    if not contract or (contract["direction"] == "callback") != callback:
        raise ValidationError("百世接口方向无效。")
    for field in contract["fields"]:
        key = field["name"]
        if not key.isidentifier() or key == "partnerId":
            continue
        value = data.get(key)
        if field["required"] and value in (None, "", []):
            raise ValidationError({key: "百世接口必填字段缺失。"})
        if value is None:
            continue
        if field["list"] and not isinstance(value, list):
            raise ValidationError({key: "须为列表。"})
        if not field["list"] and field["type"] in {"int", "long", "integer"} and (isinstance(value, bool) or not isinstance(value, int)):
            raise ValidationError({key: "须为整数。"})
        if not field["list"] and field["type"] == "boolean" and type(value) is not bool:
            raise ValidationError({key: "须为布尔值。"})
    for key in ("page", "pageSize"):
        value = data.get(key)
        if value is not None and (type(value) is not int or value < 1 or (key == "pageSize" and value > 200)):
            raise ValidationError({key: "分页范围无效。"})
    for key in ("skus", "sku", "asnNumbers", "trackingNumbers", "wmsAsnNumbers", "orderNumbers", "workOrderList"):
        values = data.get(key)
        if isinstance(values, list):
            limit = 200 if name in {"GLINK_QUERY_INVENTORY_NOTIFY", "GLINK_QUERY_INVENTORY_NOTIFY_NEW"} else 100
            if len(values) > limit or any(not isinstance(value, str) or not value.strip() for value in values):
                raise ValidationError({key: "编码列表格式或数量无效。"})
    for key in ("itemList", "orderNumberList", "files", "asnLineItems", "items"):
        if key in data and (not isinstance(data[key], list) or any(not isinstance(row, dict) for row in data[key])):
            raise ValidationError({key: "须为业务明细对象列表。"})
    def complete_pair(prefix):
        return bool(data.get(prefix + "From") and data.get(prefix + "To"))
    rules = {
        "GLINK_QUERY_ITEM_NOTIFY": (("skus",), ("createdTime", "updatedTime")),
        "GLINK_BATCH_QUERY_ASN_NOTIFY": (("asnNumbers", "trackingNumbers", "wmsAsnNumbers", "refNumbers"),
                                         ("createdTime", "lastUpdatedTime", "receiveTime", "putawayCompletedTime")),
        "GLINK_BATCH_QUERY_ORDER_NOTIFY": (("orderNumbers", "extOrderNumbers"), ("createdTime", "shippingTime", "orderedTime")),
        "GLINK_QUERY_WORK_ORDER": (("workOrderList",), ("createdTime", "updatedTime")),
        "GLINK_QUERY_STOCK_LOG_NOTIFY": (("documentNumbers",), ("createdTime",)),
    }
    if name in rules:
        lists, pairs = rules[name]
        if not any(data.get(key) for key in lists) and not any(complete_pair(prefix) for prefix in pairs):
            raise ValidationError("须提供单号/SKU范围或完整起止时间。")
    if name == "GLINK_QUERY_ASN_NOTIFY" and not any(data.get(key) for key in ("asnNumbers", "trackingNumbers", "wmsAsnNumbers")):
        raise ValidationError("入库查询须提供至少一种单号。")
    if name == "GLINK_QUERY_INVENTORY_NOTIFY_NEW" and not data.get("skus") and not (data.get("page") and data.get("pageSize")):
        raise ValidationError("状态库存查询须提供SKU范围或分页参数。")
    if name == "GLINK_CREATE_FILE_NOTIFY":
        modes = set()
        for file in data["files"]:
            if not file.get("fileName") or not file.get("fileType") or bool(file.get("fileUrl")) == bool(file.get("fileBase64")):
                raise ValidationError("附件须有名称、类型且URL与Base64二选一。")
            modes.add("url" if file.get("fileUrl") else "base64")
        if len(modes) != 1:
            raise ValidationError("同一请求不能混用URL和Base64附件。")


def request_template(name):
    sample = CONTRACTS[name]["examples"][0] if CONTRACTS[name]["examples"] else {}
    def strip(value):
        if isinstance(value, dict):
            return {key: strip(item) for key, item in value.items() if key != "partnerId"}
        if isinstance(value, list):
            return [strip(item) for item in value]
        return value
    return strip(sample)


def scope_fields(name):
    names = {field["name"] for field in CONTRACTS[name]["fields"] if field["name"].isidentifier()}
    return ("ownerCode" if name == "GLINK_QUERY_WORK_ORDER" else "customerCode",
            "whCode" if "whCode" in names else "warehouseCode" if "warehouseCode" in names else None)
