"""BEST overseas warehouse GLINK requests; no automatic write or retry."""
import hashlib
import json
from dataclasses import dataclass

from django.conf import settings
from rest_framework.exceptions import PermissionDenied, ValidationError

from .custody import get_custody_backend
from .net_guard import PlatformHttpClient

CONTRACT = "glink"
GATEWAYS = {
    "production": "https://edi-glink.800best.com/gateway/api/glink",
    "pilot": "https://kytest.800best.com/gateway/api/glink",
}
DISCOVERY = {"GLINK_QUERY_OWNER_NOTIFY", "GLINK_QUERY_WAREHOUSE_NOTIFY"}


@dataclass(frozen=True)
class Operation:
    name: str
    label: str
    write: bool = False
    method: str = "POST"

    @property
    def path(self):
        return self.name


from .best_glink_contract import CONTRACTS, scope_fields, validate_fields

OPERATIONS = tuple(Operation(item["name"], item["label"], item["write"])
                   for item in CONTRACTS.values() if item["direction"] == "request")


def operation_for(name):
    for operation in OPERATIONS:
        if operation.name == name:
            return operation
    raise ValidationError("未支持的 GLINK 接口，旧 ECAPI 接口不能继续执行。")


def parse_data(value):
    if not isinstance(value, str) or len(value.encode("utf-8")) > 1024 * 1024:
        raise ValidationError("百世 bizData 必须是 JSON 对象字符串，大小不超过1MB。")
    try:
        data = json.loads(value)
        if not isinstance(data, dict):
            raise ValueError()
        json.dumps(data, allow_nan=False)
    except (ValueError, TypeError):
        raise ValidationError("百世 bizData JSON 格式无效。") from None
    return data


def check_identity(data, authorization):
    expected = {"customerCode": authorization.integration_config.platform_config.get("customer_code"),
                "warehouseCode": authorization.external_warehouse_code}
    if any(not value or data.get(key) != value for key, value in expected.items()):
        raise PermissionDenied("客户或仓库编码与当前授权不一致。")
    expected["whCode"] = expected["warehouseCode"]
    expected["ownerCode"] = expected["customerCode"]
    def check(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in expected and item not in (None, "") and item != expected[key]:
                    raise PermissionDenied("业务明细超出当前仓库授权。")
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)
    check(data)


def prepare_operation(name, payload):
    operation = operation_for(name)
    if not isinstance(payload, dict) or set(payload) != {"bizData"}:
        raise ValidationError("百世业务参数须为包含 bizData JSON 的对象。")
    data = parse_data(payload["bizData"])
    def check(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key.replace("_", "").lower() in {"partnerid", "partnerkey", "sign", "password", "token", "authorization"}:
                    raise ValidationError("业务参数不能携带认证凭据。")
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)
    check(data)
    customer_field, warehouse_field = scope_fields(name)
    normalized = dict(data)
    if customer_field == "ownerCode" and "ownerCode" not in normalized:
        normalized["ownerCode"] = normalized.get("customerCode")
    if warehouse_field == "whCode" and "whCode" not in normalized:
        normalized["whCode"] = normalized.get("warehouseCode")
    validate_fields(name, normalized)
    return {"operation": name, "payload": payload, "requires_confirmation": operation.write,
            "execution_enabled": False, "local_business_updated": False}


def gateway_for(environment):
    if environment not in GATEWAYS:
        raise ValidationError("百世 GLINK 仅支持试运行或生产环境。")
    return GATEWAYS[environment]


class BestGlinkClient:
    def __init__(self, config, authorization, http_client=None, custody=None, *, verification_only=False):
        self.config, self.authorization = config, authorization
        self.verification_only = verification_only
        self.http = http_client or PlatformHttpClient(max_retries=0)
        self.custody = custody or get_custody_backend()

    def preflight(self):
        from .capability import live_network_mode_enabled, live_platform_security_approved, approved_custody_configured
        from apps.common.module_gate import is_module_enabled
        config, auth = self.config, self.authorization
        if not getattr(settings, "BEST_ECAPI_ENABLED", False):
            raise PermissionDenied("百世真实调用尚未开启。")
        from .production_settings import get_runtime_platform_config
        if not get_runtime_platform_config("best_ecapi").get("contract_approved", False):
            raise PermissionDenied("百世接口合同尚未批准。")
        if not (is_module_enabled("api_integrations") and live_network_mode_enabled()
                and live_platform_security_approved() and approved_custody_configured()):
            raise PermissionDenied("百世网络或凭据托管尚未就绪。")
        if (config.contract_version != CONTRACT or config.platform != "best_ecapi" or auth.provider != "best_ecapi"
                or config.pk != auth.integration_config_id or config.tenant_id != auth.tenant_id
                or config.tenant_id != auth.warehouse.tenant_id or auth.status != "active"
                or auth.warehouse.status != "active" or not config.credential_id
                or config.credential_status != "configured" or config.sync_write_enabled
                or config.status not in ({"configured", "verified", "active"} if self.verification_only else {"verified", "active"})):
            raise PermissionDenied("百世授权、租户或协议尚未就绪。")
        if not self.verification_only and (not config.network_enabled or not config.sync_read_enabled
                or auth.validation_status != "verified" or not auth.external_warehouse_code):
            raise PermissionDenied("百世仓库尚未验证或未开启读取。")
        gateway_for(config.environment)

    def _request(self, operation, fields):
        self.preflight()
        specification = operation_for(operation)
        if self.verification_only and operation not in DISCOVERY:
            raise PermissionDenied("当前入口仅允许百世只读查询。")
        if specification.write and not getattr(settings, "WAREHOUSE_BUSINESS_WRITE_ENABLED", False):
            raise PermissionDenied("百世写入尚未开启。")
        customer = self.config.platform_config.get("customer_code")
        if not customer or fields.get("customerCode", customer) != customer:
            raise PermissionDenied("客户编码与当前授权不一致。")
        payload = {**fields, "customerCode": customer}
        if operation not in DISCOVERY:
            warehouse = self.authorization.external_warehouse_code
            if not warehouse or fields.get("warehouseCode", warehouse) != warehouse:
                raise PermissionDenied("仓库编码与当前授权不一致。")
            payload["warehouseCode"] = warehouse
        if any(key.lower() in {"partnerid", "partnerkey", "sign", "token", "password"} for key in payload):
            raise ValidationError("业务参数不能携带认证凭据。")
        if operation not in DISCOVERY:
            check_identity(payload, self.authorization)
        if fields.get("domainCode") and fields["domainCode"] != self.config.platform_config.get("domain_code"):
            raise PermissionDenied("不能覆盖当前客户所属域。")
        customer_field, warehouse_field = scope_fields(operation)
        if customer_field == "ownerCode" and fields.get("ownerCode", customer) != customer:
            raise PermissionDenied("百世工单货主与当前授权不一致。")
        if "whCode" in fields and fields["whCode"] != self.authorization.external_warehouse_code:
            raise PermissionDenied("百世库存快照仓库与当前授权不一致。")
        wire_payload = dict(payload)
        if customer_field != "customerCode":
            wire_payload.pop("customerCode", None)
            wire_payload[customer_field] = customer
        if warehouse_field != "warehouseCode":
            wire_payload.pop("warehouseCode", None)
            if warehouse_field:
                wire_payload[warehouse_field] = self.authorization.external_warehouse_code
        validate_fields(operation, wire_payload)
        # partnerId is supplied by the server after validating caller business fields.
        if any(field["name"] == "partnerId" and field["required"] for field in CONTRACTS[operation]["fields"]):
            wire_payload["partnerId"] = self.config.platform_config["partner_id"]
        biz_data = json.dumps(wire_payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        prepare_operation(operation, {"bizData": json.dumps(payload, ensure_ascii=False, allow_nan=False)})
        if operation not in DISCOVERY:
            check_identity(payload, self.authorization)
        try:
            key = self.custody.retrieve_secret(self.config.credential_id)
            response = self.http.request("POST", gateway_for(self.config.environment), form_body={
                "partnerId": self.config.platform_config["partner_id"], "serviceType": operation,
                "bizData": biz_data, "sign": hashlib.md5((biz_data + key).encode("utf-8")).hexdigest(),
            }, retry=False, connect_timeout=self.config.connect_timeout_seconds,
                read_timeout=self.config.read_timeout_seconds)
            if response.status_code != 200:
                raise ValueError()
            result = json.loads(response.text)
            if not isinstance(result, dict) or result.get("success") is not True:
                raise ValueError()
        except Exception:
            raise ValidationError("百世 GLINK 查询失败，请核对授权或网络；未自动重试。") from None
        # Explicit returned identities must agree with this authorization. Missing optional
        # detail identities may inherit the already scoped parent request.
        def verify(value):
            if isinstance(value, dict):
                for name, item in value.items():
                    if name == "customerCode" and item not in (None, "", customer):
                        raise PermissionDenied("百世响应客户与当前授权不一致。")
                    if operation not in DISCOVERY and name in {"warehouseCode", "whCode"} and item not in (None, "", self.authorization.external_warehouse_code):
                        raise PermissionDenied("百世响应仓库与当前授权不一致。")
                    if operation == "GLINK_QUERY_WORK_ORDER" and name == "ownerCode" and item not in (None, "", customer):
                        raise PermissionDenied("百世响应工单货主与当前授权不一致。")
                    verify(item)
            elif isinstance(value, list):
                for item in value:
                    verify(item)
        verify(result)
        return result

    def query(self, operation, fields):
        if operation_for(operation).write:
            raise PermissionDenied("查询入口不能执行写入。")
        return self._request(operation, fields)

    def _signed_request(self, method, path, payload):
        if method != "POST":
            raise ValidationError("百世 GLINK 仅支持 POST。")
        prepare_operation(path, payload)
        result = self._request(path, parse_data(payload["bizData"]))
        return {"code": "0", "data": result}

    def discover_warehouses(self):
        owner = self.query("GLINK_QUERY_OWNER_NOTIFY", {})
        customers = owner.get("customerDTOList")
        customer = self.config.platform_config["customer_code"]
        if (not isinstance(customers, list) or not customers
                or any(not isinstance(row, dict) or row.get("customerCode") != customer for row in customers)):
            raise PermissionDenied("百世返回的客户与当前授权不一致。")
        allowed_codes = set()
        for row in customers:
            encoded = row.get("warehouseCodes")
            if row.get("enable") is False or not isinstance(encoded, str) or not encoded.strip():
                raise PermissionDenied("百世客户未启用或未返回已绑定仓库范围。")
            allowed_codes.update(part.strip().split(":", 1)[0] for part in encoded.split(",") if part.strip())
        result = self.query("GLINK_QUERY_WAREHOUSE_NOTIFY", {})
        rows = result.get("resultList")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValidationError("百世仓库列表格式无效。")
        warehouses = []
        seen = set()
        for row in rows:
            if row.get("warehouseCode") not in allowed_codes:
                continue
            code = row.get("warehouseCode")
            if not isinstance(code, str) or not code.strip() or len(code) > 64 or code in seen:
                raise ValidationError("百世仓库编码缺失或重复。")
            seen.add(code)
            warehouses.append({"code": code, "name": row.get("warehouseDescription") or code,
                "country": str(row.get("country") or ""), "time_zone": str(row.get("timeZone") or "")})
        return warehouses

    def fetch_inventory(self, cursor, scope):
        codes = scope.get("sku_codes")
        if (not isinstance(codes, list) or not codes
                or any(not isinstance(code, str) or not code.strip() for code in codes)
                or len(codes) != len(set(codes))):
            raise ValidationError("请指定不重复的 SKU 查询范围。")
        try:
            offset = int(cursor or 0)
        except (TypeError, ValueError):
            raise ValidationError("百世库存游标无效。") from None
        if offset < 0 or offset >= len(codes) or offset % 200:
            raise ValidationError("百世库存游标无效。")
        batch = codes[offset:offset + 200]
        canonical = {code.casefold(): code for code in codes}
        if len(canonical) != len(codes):
            raise ValidationError("百世库存接口统一编码大小写；当前SKU范围存在大小写冲突，不能自动关联。")
        result = self.query("GLINK_QUERY_INVENTORY_NOTIFY_NEW", {"skus": batch, "stockStatus": "GOOD", "ignoreZero": False})
        rows = result.get("inventoryVOList")
        if not isinstance(rows, list):
            raise ValidationError("百世库存响应缺少明细，不能视为零库存。")
        from django.utils import timezone
        snapshot_at = scope.get("snapshot_at_utc") or getattr(self, "_inventory_snapshot_at", None)
        if not snapshot_at:
            snapshot_at = timezone.now().isoformat()
            self._inventory_snapshot_at = snapshot_at
        seen, records = set(), []
        for row in rows:
            # GLINK NEW returns uppercase codes even when the item catalogue preserves case.
            code = canonical.get(str(row.get("sku") or "").casefold()) if isinstance(row, dict) else None
            if (not isinstance(row, dict) or code not in batch or code in seen
                    or row.get("customerCode") != self.config.platform_config["customer_code"]
                    or row.get("warehouseCode") != self.authorization.external_warehouse_code
                    or row.get("skuStatus") != "GOOD"):
                raise ValidationError("百世库存明细超出授权范围、状态不符或重复。")
            seen.add(code)
            records.append({"itemSkuCode": code, "totalQuantity": row.get("totalQty"),
                "normalQuantity": row.get("salableQty"), "_snapshot_at_utc": snapshot_at})
        if seen != set(batch):
            raise ValidationError("百世库存响应未完整覆盖本批SKU，缺失项不能自动补零。")
        return {"records": records, "next_cursor": str(offset + 200) if offset + 200 < len(codes) else "",
                "raw_responses": [{"endpoint": "GLINK_QUERY_INVENTORY_NOTIFY_NEW", "payload": result}]}

    def fetch_inbound(self, cursor, scope):
        from .best_glink_business import inbound_records
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        zone = self.config.platform_config.get("business_time_zone")
        if zone != "Asia/Shanghai":
            raise ValidationError("百世入库同步前须确认业务时间口径。")
        try:
            page = int(cursor or 1)
            start = datetime.fromtimestamp(float(scope["time_from"]), timezone.utc)
            end = datetime.fromtimestamp(float(scope["time_to"]), timezone.utc)
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ValidationError("百世入库同步查询范围无效。") from None
        if page < 1 or page > 10000 or start >= end:
            raise ValidationError("百世入库分页或时间范围无效。")
        result = self.query("GLINK_BATCH_QUERY_ASN_NOTIFY", {
            "lastUpdatedTimeFrom": start.astimezone(ZoneInfo(zone)).strftime("%Y-%m-%d %H:%M:%S"),
            "lastUpdatedTimeTo": end.astimezone(ZoneInfo(zone)).strftime("%Y-%m-%d %H:%M:%S"),
            "page": page, "pageSize": 100,
        })
        rows = result.get("asnInfoList")
        total = result.get("total")
        if not isinstance(rows, list) or isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise ValidationError("百世入库分页结构无效。")
        if len(rows) != min(100, max(0, total - (page - 1) * 100)):
            raise ValidationError("百世入库分页数量不完整。")
        records, seen = [], set()
        for row in rows:
            if not isinstance(row, dict) or not row.get("asnNumber") or row["asnNumber"] in seen:
                raise ValidationError("百世入库单号缺失或重复。")
            seen.add(row["asnNumber"])
            records.extend(inbound_records(row, self.authorization))
        return {"records": records, "next_cursor": str(page + 1) if page * 100 < total else "",
                "raw_responses": [{"endpoint": "GLINK_BATCH_QUERY_ASN_NOTIFY", "payload": result}]}
