"""Scoped native reads; never refresh a token or post a business ledger entry."""
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation

from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.permissions.services import check_user_permission
from apps.permissions.ui_p6_scopes import filter_store_authorizations
from .audit_sanitizer import sanitize_audit_detail
from .lazada_api_contract import prepare_operation
from .models import IntegrationAuditLog, LazadaApiSnapshot, MarketplaceStoreAuthorization
from .readonly_clients import LazadaReadonlyClient


def scoped_authorizations(actor, *, execute=False):
    permissions = ["integrations.store.view"] + (["integrations.run_live_readonly"] if execute else [])
    records = MarketplaceStoreAuthorization.objects.select_related("integration_config", "store").filter(
        tenant_id=actor.tenant_id, platform="lazada")
    for permission in permissions:
        if not check_user_permission(actor, permission):
            raise PermissionDenied("没有 Lazada 只读查询权限。")
        records = filter_store_authorizations(actor, records, permission)
    return records


def snapshot_data(snapshot, *, include_response=False):
    result = {"id": snapshot.pk, "operation": snapshot.operation, "status": snapshot.status,
              "error_code": snapshot.error_code, "created_at": snapshot.created_at.isoformat(),
              "response_hash": snapshot.response_hash, "parameters": snapshot.parameters}
    if include_response:
        result["response"] = snapshot.response
    return result


def validate_account_page(response, query):
    """A missing or malformed ledger page is not a successful empty account."""
    data = response.get("data")
    page = data.get("page_info") if isinstance(data, dict) else None
    rows = data.get("transactions") if isinstance(data, dict) else None
    valid = (response.get("success") is True and isinstance(page, dict) and isinstance(rows, list)
        and all(type(page.get(key)) is int and page[key] >= 0 for key in ("page_num", "page_size", "total_count"))
        and page["page_num"] == query["page_num"] and page["page_size"] == query["page_size"]
        and len(rows) <= page["page_size"] and len(rows) <= page["total_count"])
    if valid:
        for row in rows:
            try:
                valid = (isinstance(row, dict) and isinstance(row.get("transaction_number"), str)
                    and bool(row["transaction_number"].strip()) and isinstance(row.get("amount"), str)
                    and bool(re.fullmatch(r"[+-]?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?", row["amount"]))
                    and Decimal(row["amount"].replace(",", "")).is_finite() and isinstance(row.get("currency"), str)
                    and bool(re.fullmatch(r"[A-Z]{3}", row["currency"])))
            except InvalidOperation:
                valid = False
            if not valid:
                break
    if not valid:
        error = ValidationError("Lazada account transaction page is incomplete or invalid.")
        error.controlled_code = "LAZADA_ACCOUNT_RESPONSE_INVALID"
        raise error


def execute_operation(*, actor, authorization_id, name, payload, client=None):
    authorization = scoped_authorizations(actor, execute=True).filter(pk=authorization_id).first()
    if authorization is None:
        raise PermissionDenied("授权不在当前租户和店铺权限范围。")
    operation, query = prepare_operation(name, payload)
    if authorization.status != "active" or (authorization.expires_at and authorization.expires_at <= timezone.now()):
        raise ValidationError("授权无效或已过期；本次不会刷新令牌。")
    client = client or LazadaReadonlyClient(authorization.integration_config, authorization=authorization)
    if name in {"products", "product"}:
        client.resource_type = "platform_product"
    client.preflight()
    try:
        response = client._request("/rest" + operation.path, query)
        result = response.get("result")
        if response.get("success") is False or isinstance(result, dict) and result.get("success") is False:
            rejection = ValidationError("Lazada returned a business rejection.")
            rejection.controlled_code = (response.get("error_code") or response.get("errorCode")
                or ((result.get("error_code") or result.get("errorCode")) if isinstance(result, dict) else None)
                or "LAZADA_BUSINESS_REJECTED")
            raise rejection
        if name == "account_transactions":
            validate_account_page(response, query)
        status, code = "succeeded", ""
    except Exception as exc:
        # Exceptions may contain signed URLs. Store a controlled category, never str(exc).
        code = getattr(exc, "controlled_code", "LAZADA_READ_FAILED")
        if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", code):
            code = "LAZADA_READ_FAILED"
        parameter = getattr(exc, "missing_parameter", "")
        response, status = ({"missing_parameter":parameter} if isinstance(parameter, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,59}", parameter) else {}), "failed"
    safe_response = sanitize_audit_detail(response)
    digest = hashlib.sha256(json.dumps(safe_response, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    snapshot = LazadaApiSnapshot.objects.create(tenant_id=actor.tenant_id, authorization=authorization,
        actor=actor, operation=name, parameters=sanitize_audit_detail(payload), response=safe_response,
        response_hash=digest, status=status, error_code=code)
    IntegrationAuditLog.objects.create(tenant_id=actor.tenant_id, actor=actor,
        integration_config=authorization.integration_config, store_authorization=authorization,
        action="lazada_api.read", result="success" if status == "succeeded" else "failed",
        masked_detail={"snapshot_id":snapshot.pk, "operation":name, "error_code":code})
    return snapshot_data(snapshot, include_response=True)
