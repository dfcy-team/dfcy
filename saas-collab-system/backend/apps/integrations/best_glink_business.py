"""GLINK business responses, with exact customer/warehouse/order matching."""
import json
from datetime import timezone
from zoneinfo import ZoneInfo

from django.utils.dateparse import parse_datetime

from rest_framework.exceptions import ValidationError

from .best_business import count, text
from .best_glink import check_identity


def business_time(value, authorization):
    if value in (None, ""):
        return None
    try:
        parsed = parse_datetime(str(value))
    except ValueError:
        parsed = None
    if parsed is None:
        raise ValidationError("百世业务时间格式无效。")
    if parsed.tzinfo is None:
        zone = authorization.integration_config.platform_config.get("business_time_zone")
        if zone != "Asia/Shanghai":
            return None
        parsed = parsed.replace(tzinfo=ZoneInfo(zone))
    return parsed.astimezone(timezone.utc).isoformat()


def request_payload(authorization, **fields):
    data = {**fields, "customerCode": authorization.integration_config.platform_config["customer_code"],
            "warehouseCode": authorization.external_warehouse_code}
    return {"bizData": json.dumps(data, ensure_ascii=False, separators=(",", ":"))}


def list_value(data, key):
    value = data.get(key)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValidationError("百世响应缺少有效的业务明细列表。")
    return value


def packages(order, authorization):
    check_identity(order, authorization)
    number = text(order.get("orderNumber"))
    status = "CANCELLED" if order.get("status") == "CANCELLED" else text(order.get("stage"))
    base = {"provider": "best_ecapi", "warehouse_order_no": number, "erp_no": number,
        "status": status, "status_label": "已发货" if status == "SHIPPED" else status,
        "tracking_no": order.get("trackingNumber") or "", "carrier": order.get("carrier") or "",
        "shipped_at_utc": business_time(order.get("shippingTime"), authorization) if status == "SHIPPED" else None}
    def items(values):
        return [{"sku": text(item.get("sku")), "quantity": count(item.get("quantity"))} for item in values]
    parcels = order.get("packages")
    if parcels is None:
        parcels = []
    if not isinstance(parcels, list) or any(not isinstance(item, dict) for item in parcels):
        raise ValidationError("百世包裹结构无效。")
    if not parcels:
        return [{**base, "items": items(list_value(order, "items"))}]
    result, seen = [], set()
    for parcel in parcels:
        code = text(parcel.get("packageNumber"))
        if code in seen:
            raise ValidationError("百世包裹编号重复。")
        seen.add(code)
        result.append({**base, "warehouse_order_no": number + "/" + code, "source_order_no": number,
            "package_no": code, "tracking_no": parcel.get("trackingNumber") or base["tracking_no"],
            "items": items(list_value(parcel, "packageContents"))})
    return result


def return_receipt(data, authorization, number):
    records = list_value(data, "asnInfoList")
    if count(data.get("total")) != 1 or len(records) != 1:
        raise ValidationError("百世退货单查询未返回唯一记录。")
    record = records[0]
    check_identity(record, authorization)
    if record.get("asnNumber") != number or record.get("asnType") != "RETURN":
        raise ValidationError("百世单号或入库类型与核对的退货单不一致。")
    result = {"return_no": number, "erp_no": "", "platform_order_no": "", "tracking_no": "",
        "provider_status": text(record.get("stage")), "received_at": None, "lines": []}
    if record.get("putawayStage") != "COMPLETED":
        return result
    result["received_at"] = business_time(record.get("putawayTime"), authorization)
    result["lines"] = [{"sku": text(item.get("sku")), "received_quantity": count(item.get("putawayedQuantity"))}
                       for item in list_value(record, "asnLineItems")]
    return result


def inbound_records(record, authorization):
    check_identity(record, authorization)
    number = text(record.get("asnNumber"))
    # Only confirmed putaway quantities enter the shared receipt facts.
    if record.get("putawayStage") != "COMPLETED":
        return []
    received_at = business_time(record.get("putawayTime"), authorization)
    if received_at is None:
        raise ValidationError("百世上架完成时间缺失或时间口径尚未确认。")
    types = {"RETURN": "return", "SUPPLIER_RECEIPT": "purchase", "PURCHASE": "purchase",
             "TRANSFER_PLAN": "transfer", "TRANSFER_AVAILABLE": "transfer",
             "OTHER_INBOUND": "other", "MANUAL": "other", "FIRST_LEG": "purchase"}
    if record.get("asnType") not in types:
        raise ValidationError("百世入库类型尚未适配。")
    result, seen = [], set()
    for item in list_value(record, "asnLineItems"):
        line = text(str(item.get("lineNo") or ""))
        if line in seen:
            raise ValidationError("百世入库行号重复。")
        seen.add(line)
        result.append({"external_inbound_id": number, "external_line_id": line,
            "inbound_type": types[record["asnType"]], "source_sku": text(item.get("sku")),
            "planned_quantity": count(item.get("quantity")),
            "received_quantity": count(item.get("putawayedQuantity")), "status": "putaway_completed",
            "received_at_utc": received_at, "updated_at_utc": received_at})
    if not result:
        raise ValidationError("百世已上架单据缺少明细。")
    return result
