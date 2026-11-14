"""BEST ECAPI 2.0 protocol. No OAuth, no implicit network or write retries."""
from dataclasses import dataclass
import hashlib
import re
from xml.etree import ElementTree as ET

from django.conf import settings
from rest_framework.exceptions import PermissionDenied, ValidationError

from .best_access import validate_gateway
from .capability import live_network_mode_enabled, live_platform_security_approved, approved_custody_configured
from .custody import get_custody_backend
from .net_guard import PlatformHttpClient


@dataclass(frozen=True)
class Operation:
    name: str
    label: str
    write: bool = False
    method: str = "POST"

    @property
    def path(self):
        return self.name


OPERATIONS = tuple(Operation(name, label, write) for name, label, write in (
    ("GET_RMA_STATUS_REQ", "退货单状态查询", False),
    ("WMS_ASN_STATUS_QUERY", "入库单状态查询", False),
    ("WMS_SO_STATUS_QUERY", "出库单状态查询", False),
    ("WMS_CUSTOMER_NOTIFY", "客户信息同步", True),
    ("WMS_SKU_NOTIFY", "SKU同步", True),
    ("TW_ASN_NOTIFY", "入库单同步", True),
    ("TW_SO_NOTIFY", "出库单同步", True),
    ("TW_CANCEL_NOTIRY", "仓配单取消", True),
    ("TW_BOM_NOTIFY", "组合商品同步", True),
    ("TW_PROCESS_NOTIFY", "组合加工单创建", True),
    ("TW_CANCEL_PROCESS", "组合加工单取消", True),
    ("WMS_ASN_LIST_QUERY", "入库及退货列表", False),
    ("WMS_SO_LIST_QUERY", "出库订单列表", False),
    ("WMS_SKU_INVENTORY_EXT_QUERY", "库存拓展查询", False),
    ("GetProductInventoryLlu", "库存查询（带库位）", False),
    ("WMS_INV_TRANS_NOTIFY", "库存转移单创建", True),
    ("WMS_SN_NOTIFY", "SN码下发", True),
    ("TW_UPDATE", "仓储单据更新", True),
    ("GetShippingOrderInfo", "运单信息查询", False),
    ("TMS_TRACE_QUERY", "物流信息查询", False),
    ("TMS_GPS_QUERY", "GPS查询", False),
))


def operation_for(name):
    for operation in OPERATIONS:
        if operation.name == name:
            return operation
    raise ValidationError("未支持的百世请求接口；推送接口不能作为查询调用。")


def parse_xml(value, root):
    if not isinstance(value, str) or len(value.encode("utf-8")) > 1024 * 1024 or re.search(r"<!\s*(DOCTYPE|ENTITY)", value, re.I):
        raise ValidationError("XML报文过大或包含不允许的声明。")
    try:
        node = ET.fromstring(value)
    except ET.ParseError:
        raise ValidationError("XML报文格式错误。") from None
    if node.tag != root:
        raise ValidationError("XML根节点不符合仓配2.0协议。")
    return node


def prepare_operation(name, payload):
    operation = operation_for(name)
    if not isinstance(payload, dict) or set(payload) != {"bizData"}:
        raise ValidationError("百世业务参数须为包含 bizData XML 的对象。")
    root = parse_xml(payload["bizData"], "request")
    sensitive = {"partnerkey", "partnerid", "sign", "password", "token", "accesstoken", "authorization"}
    for node in root.iter():
        if any(str(key).replace("_", "").lower() in sensitive for key in (node.tag, *node.attrib)):
            raise ValidationError("业务XML不能携带认证凭据。")
    return {"operation": name, "payload": payload, "requires_confirmation": operation.write,
            "execution_enabled": False, "local_business_updated": False}


def signature(biz_data, key):
    return hashlib.md5((biz_data + key).encode("utf-8")).hexdigest()


def check_identity(root, authorization):
    expected = {"warehouseCode": authorization.external_warehouse_code,
                "customerCode": authorization.integration_config.platform_config.get("customer_code")}
    for name, value in expected.items():
        nodes = list(root.iter(name))
        if not value or not nodes or any((node.text or "").strip() != value for node in nodes):
            raise PermissionDenied("报文客户或仓库编码与当前授权不一致。")


class BestEcapiClient:
    def __init__(self, config, authorization, http_client=None, custody=None, *, verification_only=False):
        self.config, self.authorization = config, authorization
        self.verification_only = verification_only
        self.http = http_client or PlatformHttpClient(max_retries=0)
        self.custody = custody or get_custody_backend()

    def preflight(self):
        from apps.common.module_gate import is_module_enabled
        config, auth = self.config, self.authorization
        if getattr(settings, "BEST_ECAPI_ENABLED", False) is not True:
            raise PermissionDenied("百世接入功能已配置，真实调用未开启。")
        if (not is_module_enabled("api_integrations") or not live_network_mode_enabled()
                or not live_platform_security_approved() or not approved_custody_configured()):
            raise PermissionDenied("百世真实调用所需网络或凭据托管尚未就绪。")
        if (config.platform != "best_ecapi" or auth.provider != "best_ecapi" or config.pk != auth.integration_config_id
                or config.tenant_id != auth.tenant_id or config.tenant_id != auth.warehouse.tenant_id
                or auth.status != "active" or auth.warehouse.status != "active"
                or config.status not in ({"configured", "active", "verified"} if self.verification_only else {"active", "verified"}) or config.environment not in {"pilot", "production"}
                or not config.network_enabled or not config.sync_read_enabled or config.sync_write_enabled
                or not config.credential_id or config.credential_status != "configured"):
            raise PermissionDenied("百世配置、仓库授权或访问范围未就绪。")
        validate_gateway(config.platform_config.get("api_host", ""))

    def _signed_request(self, method, path, payload):
        self.preflight()
        operation = operation_for(path)
        if self.verification_only and path != "WMS_SKU_INVENTORY_EXT_QUERY":
            raise PermissionDenied("首次校验仅允许只读库存查询。")
        if method != "POST":
            raise ValidationError("百世仓配2.0只接受POST请求。")
        if operation.write and getattr(settings, "WAREHOUSE_BUSINESS_WRITE_ENABLED", False) is not True:
            raise PermissionDenied("百世写入未开启。")
        prepare_operation(path, payload)
        root = parse_xml(payload["bizData"], "request")
        check_identity(root, self.authorization)
        config = self.config
        try:
            secret = self.custody.retrieve_secret(config.credential_id)
            form = {"partnerID": config.platform_config["partner_id"], "serviceType": path,
                "bizData": payload["bizData"], "sign": signature(payload["bizData"], secret)}
            response = self.http.request("POST", config.platform_config["api_host"], form_body=form, retry=False,
                connect_timeout=config.connect_timeout_seconds, read_timeout=config.read_timeout_seconds)
            if response.status_code != 200:
                raise ValueError("http")
            result = parse_xml(response.text, "response")
            if result.findtext("result") not in {"true", "false"}:
                raise ValueError("envelope")
            # Only parsed business values are returned; transport/signature are never exposed.
            return {"code": "0" if result.findtext("result") == "true" else "1", "data": xml_value(result)}
        except Exception:
            raise ValidationError("百世未返回可确认的结果；请核对接口和配置，不自动重试。") from None

    def fetch_inventory(self, cursor, scope):
        # The official API requires 1–50 SKU codes; it is not a whole-warehouse enumeration API.
        codes = scope.get("sku_codes")
        if not isinstance(codes, list) or not codes or any(not isinstance(x, str) or not x.strip() or len(x) > 64 for x in codes):
            raise ValidationError("百世库存同步须在查询范围指定 sku_codes，不能将空列表当作全仓查询。")
        if len(codes) != len(set(codes)):
            raise ValidationError("百世库存查询SKU不可重复。")
        offset = int(cursor or 0)
        if offset < 0 or offset >= len(codes) or offset % 50:
            raise ValidationError("百世库存游标无效。")
        batch = codes[offset:offset + 50]
        root = ET.Element("request")
        ET.SubElement(root, "customerCode").text = self.config.platform_config["customer_code"]
        ET.SubElement(root, "warehouseCode").text = self.authorization.external_warehouse_code
        products = ET.SubElement(root, "products")
        for code in batch:
            ET.SubElement(ET.SubElement(products, "product"), "itemSkuCode").text = code
        response = self._signed_request("POST", "WMS_SKU_INVENTORY_EXT_QUERY", {"bizData": ET.tostring(root, encoding="unicode")})
        if response["code"] != "0":
            raise ValidationError("百世未接受库存查询。")
        product_container = response["data"].get("products")
        if not isinstance(product_container, dict):
            raise ValidationError("百世库存响应缺少products，不将其视为零库存。")
        rows = product_container.get("product", [])
        rows = rows if isinstance(rows, list) else [rows]
        if any(not isinstance(row, dict) or row.get("itemSkuCode") not in batch for row in rows):
            raise ValidationError("百世返回了不属于本次查询的SKU。")
        if len({row["itemSkuCode"] for row in rows}) != len(rows):
            raise ValidationError("百世库存响应SKU重复，须核对供应商口径。")
        from django.utils import timezone
        snapshot_at = timezone.now().isoformat()
        return {"records": [{**row, "_snapshot_at_utc": snapshot_at} for row in rows],
            "next_cursor": str(offset + 50) if offset + 50 < len(codes) else "",
            "raw_responses": [{"endpoint": "WMS_SKU_INVENTORY_EXT_QUERY", "payload": response}]}


def xml_value(node):
    if not list(node):
        return node.text or ""
    result = {}
    for child in node:
        value = xml_value(child)
        if child.tag in result:
            previous = result[child.tag]
            result[child.tag] = (previous if isinstance(previous, list) else [previous]) + [value]
        else:
            result[child.tag] = value
    return result
