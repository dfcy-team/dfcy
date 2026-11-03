"""Manual warehouse operations. Execution is off unless explicitly approved.

No scheduler, OAuth refresh, local inventory update or accounting posting is
performed here. A provider timeout never authorizes replaying a write.
"""
import hashlib
import json

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.common.exceptions import StateConflict
from apps.permissions.services import check_user_permission
from apps.permissions.ui_p6_scopes import integration_values_allowed
from .models import IntegrationAuditLog, WarehouseApiAttempt
from .net_guard import PlatformHttpClient
from .readonly_clients import JifengWmsReadonlyClient
from .warehouse_api_contract import SENSITIVE_KEYS, operation_for, prepare_operation
from .warehouse_credential_service import require_verified_warehouse


def _redact(value):
    if isinstance(value, dict):
        return {k: "<REDACTED>" if k.replace("_", "").lower() in SENSITIVE_KEYS | {"invoicesecretkey"}
                else _redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def execution_gate(operation):
    if getattr(settings, "WAREHOUSE_BUSINESS_API_ENABLED", False) is not True:
        raise PermissionDenied("仓库业务接口已登记，真实调用尚未授权；本次不访问仓库。")
    if operation.write and getattr(settings, "WAREHOUSE_BUSINESS_WRITE_ENABLED", False) is not True:
        raise PermissionDenied("仓库写入接口未授权；本次不访问仓库。")


def execute_operation(*, actor, authorization, name, payload, confirmed=False, idempotency_key="", client=None):
    operation = operation_for(name)
    execution_gate(operation)
    prepared = prepare_operation(name, payload)
    config = authorization.integration_config
    if (actor.tenant_id != authorization.tenant_id or actor.tenant_id != config.tenant_id
            or actor.tenant_id != authorization.warehouse.tenant_id
            or authorization.provider != "jifeng_wms" or config.platform != "jifeng_wms"
            or authorization.status != "active" or authorization.warehouse.status != "active"):
        raise PermissionDenied("仓库授权、配置或租户不匹配。")
    permission = "integrations.manage" if operation.write else "integrations.run_live_readonly"
    if not check_user_permission(actor, permission) or not check_user_permission(actor, "integrations.warehouse.view"):
        raise PermissionDenied("没有此仓库操作的权限。")
    if not integration_values_allowed(actor, permission, platform=config.platform, environment=config.environment,
            regions=[authorization.external_warehouse_region], config_id=config.pk,
            warehouse_id=authorization.warehouse_id):
        raise PermissionDenied("仓库超出当前操作的数据范围。")
    require_verified_warehouse(authorization)
    # Do not permit a user-supplied warehouse override or forwarding auth fields.
    if isinstance(payload, dict):
        for key in ("warehouse", "warehouseCode"):
            if key in payload and payload[key] != authorization.external_warehouse_code:
                raise PermissionDenied("业务参数仓库与当前授权仓库不一致。")
    if operation.write:
        if confirmed is not True or not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 120:
            raise ValidationError("写入操作必须人工确认并提供8至120字符的幂等键。")
        if transaction.get_connection().in_atomic_block:
            raise ValidationError("写入必须在独立提交边界执行，不能在未提交事务中调用仓库。")
    api = client or JifengWmsReadonlyClient(config, authorization,
        http_client=PlatformHttpClient(max_retries=0))
    # Reuse all existing module/network/contract/custody approvals before reserving a write.
    api.preflight()
    attempt = None
    if operation.write:
        digest = hashlib.sha256(json.dumps([authorization.pk, name, prepared["payload"]],
            sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        try:
            with transaction.atomic():
                attempt = WarehouseApiAttempt.objects.create(tenant_id=actor.tenant_id,
                    authorization=authorization, actor=actor, operation=name,
                    key_hash=hashlib.sha256(idempotency_key.encode()).hexdigest(), payload_hash=digest)
        except IntegrityError:
            raise StateConflict("该幂等键已使用；请先查询仓库结果，禁止自动重发。") from None
    try:
        response = api._signed_request(operation.method, operation.path, prepared["payload"])
        if not isinstance(response, dict) or "code" not in response:
            raise ValueError("invalid response envelope")
        data = response.get("data")
        if isinstance(data, dict):
            for key in ("warehouse", "warehouseCode"):
                if data.get(key) and data[key] != authorization.external_warehouse_code:
                    raise ValueError("response warehouse mismatch")
        succeeded = str(response["code"]) == "0"
        if attempt:
            WarehouseApiAttempt.objects.filter(pk=attempt.pk).update(
                status="succeeded" if succeeded else "rejected", finished_at=timezone.now())
        IntegrationAuditLog.objects.create(tenant_id=actor.tenant_id, integration_config=config, actor=actor,
            action="warehouse_api." + name, result="success" if succeeded else "failed",
            masked_detail={"operation": name, "warehouse_authorization_id": authorization.pk,
                "attempt_id": attempt.pk if attempt else None})
        if not succeeded:
            raise ValidationError("仓库未接受本次请求，请查询单据状态；不自动重试。")
        return {"operation": name, "attempt_id": attempt.pk if attempt else None,
                "data": _redact(response.get("data")), "local_business_updated": False}
    except Exception:
        if attempt:
            WarehouseApiAttempt.objects.filter(pk=attempt.pk, status="running").update(
                status="unknown", finished_at=timezone.now())
        raise ValidationError("仓库调用未取得可确认结果；请先查询单据，禁止自动重试写入。") from None
