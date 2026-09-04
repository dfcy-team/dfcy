"""Service-layer transitions for warehouse inventory API bindings.

Warehouse authorization records contain only opaque custody references copied
from an already managed integration configuration.  The page API never
accepts raw credentials and all state transitions are audited here so callers
cannot bypass the tenant and service-platform checks.
"""

import hashlib

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.common.exceptions import IdempotencyConflict, StateConflict

from .models import (
    IntegrationAuditLog,
    PlatformIntegrationConfig,
    SyncJob,
    WarehouseAuthorization,
    authorization_service_write,
    warehouse_binding_key,
)
from .audit_sanitizer import sanitize_audit_detail
from .subject_access_service import _warehouse_provider


VISIBLE_CONFIG_STATUSES = {
    PlatformIntegrationConfig.Status.CONFIGURED,
    PlatformIntegrationConfig.Status.VERIFIED,
    PlatformIntegrationConfig.Status.ACTIVE,
}
REVOKED_CREDENTIAL_STATUSES = {
    PlatformIntegrationConfig.CredentialStatus.UNCONFIGURED,
    PlatformIntegrationConfig.CredentialStatus.REVOKED,
}


def _digest(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _idempotency_key_hash(value):
    key = str(value or "").strip()
    if not key:
        return ""
    if not 8 <= len(key) <= 120:
        raise ValidationError({"idempotency_key": "幂等键长度必须在 8 到 120 个字符之间。"})
    if any(ord(char) < 0x21 or ord(char) > 0x7E for char in key):
        raise ValidationError({"idempotency_key": "幂等键只能包含可打印 ASCII 字符。"})
    return _digest(key)


def _audit(*, record, actor, action, detail, result=IntegrationAuditLog.Result.SUCCESS):
    return IntegrationAuditLog.objects.create(
        tenant=record.tenant,
        integration_config=record.integration_config,
        action=action,
        actor=actor,
        result=result,
        masked_detail=sanitize_audit_detail(detail),
    )


def _config_api_type(config):
    value = str((config.platform_config or {}).get("api_type") or "").strip().lower()
    return value or ("inventory" if config.platform == "jifeng_wms" else "marketplace")


def validate_warehouse_binding(*, actor, warehouse, integration_config):
    """Validate the non-secret prerequisites for binding a config to a warehouse."""
    if actor.tenant_id != warehouse.tenant_id:
        raise ValidationError("仓库不属于当前租户。")
    if integration_config.tenant_id != actor.tenant_id:
        raise ValidationError("接入配置不属于当前租户。")
    if warehouse.status != "active":
        raise ValidationError("仓库已停用，无法绑定库存 API。")
    try:
        provider = _warehouse_provider(warehouse)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    if integration_config.platform != provider:
        raise ValidationError("接入配置的平台与仓库绑定的仓储服务平台不一致。")
    if _config_api_type(integration_config) != "inventory":
        raise ValidationError("所选接入配置不是库存 API 配置。")
    if integration_config.status not in VISIBLE_CONFIG_STATUSES:
        raise ValidationError("接入配置必须处于已配置、已检查或启用状态。")
    if integration_config.environment in {
        PlatformIntegrationConfig.Environment.PILOT,
        PlatformIntegrationConfig.Environment.PRODUCTION,
    } and integration_config.sync_write_enabled:
        raise ValidationError("试运行和生产库存接入不允许开启写同步。")
    if not integration_config.credential_id or not integration_config.token_id:
        raise ValidationError("接入配置的受控凭据引用不完整，请先维护接入凭据。")
    if integration_config.credential_status in REVOKED_CREDENTIAL_STATUSES:
        raise ValidationError("接入配置的受控凭据不可用，请先维护接入凭据。")
    regions = {str(value or "").upper() for value in (integration_config.regions or [])}
    if regions and str(warehouse.country_code or "").upper() not in regions:
        raise ValidationError("仓库所在国家/站点不在接入配置的区域范围内。")
    return provider


def _replay_by_idempotency(*, actor, key_hash, payload_digest):
    if not key_hash:
        return None
    logs = IntegrationAuditLog.objects.filter(
        tenant=actor.tenant,
        action__in=("warehouse_authorize", "warehouse_rebind"),
    ).order_by("-id")
    for log in logs:
        detail = log.masked_detail if isinstance(log.masked_detail, dict) else {}
        if detail.get("idempotency_key_hash") != key_hash:
            continue
        if detail.get("payload_digest") != payload_digest:
            raise IdempotencyConflict("幂等键已用于另一项仓库 API 接入操作。")
        authorization_id = detail.get("authorization_id")
        if not authorization_id:
            return None
        return WarehouseAuthorization.objects.filter(
            tenant=actor.tenant,
            pk=authorization_id,
        ).select_related("warehouse", "integration_config").first()
    return None


@transaction.atomic
def bind_warehouse_authorization(
    *,
    actor,
    warehouse,
    integration_config,
    replace=False,
    expected_authorization_id=None,
    idempotency_key=None,
):
    """Create or safely replace the one active inventory binding per warehouse."""
    provider = validate_warehouse_binding(
        actor=actor,
        warehouse=warehouse,
        integration_config=integration_config,
    )
    key_hash = _idempotency_key_hash(idempotency_key)
    payload_digest = _digest(
        f"{warehouse.id}:{integration_config.id}:{bool(replace)}:{expected_authorization_id or ''}"
    )
    replay = _replay_by_idempotency(
        actor=actor,
        key_hash=key_hash,
        payload_digest=payload_digest,
    )
    if replay is not None:
        return replay, True, "replay"

    # A rebind carries the authorization row that the operator confirmed in
    # the page.  Lock and validate that exact row before looking up the
    # current active binding; otherwise a stale request for a revoked row
    # could silently fall through and create a fresh authorization, reviving
    # a binding that was explicitly revoked.
    expected = None
    if expected_authorization_id is not None:
        expected = (
            WarehouseAuthorization.objects.select_for_update()
            .filter(tenant=actor.tenant, pk=expected_authorization_id)
            .first()
        )
        if expected is None or expected.status != WarehouseAuthorization.Status.ACTIVE:
            raise StateConflict("当前仓库 API 授权已撤销或已失效，请刷新页面后重新操作。")
        if expected.warehouse_id != warehouse.id:
            raise StateConflict("换绑请求的仓库主体已变化，请刷新页面后重新操作。")

    binding_key = warehouse_binding_key(actor.tenant_id, warehouse.id)
    active = (
        WarehouseAuthorization.objects.select_for_update()
        .filter(
            tenant=actor.tenant,
            warehouse=warehouse,
            status=WarehouseAuthorization.Status.ACTIVE,
        )
        .order_by("-updated_at", "-id")
        .first()
    )
    if active and active.integration_config_id == integration_config.id:
        return active, True, "already_bound"
    if active and not replace:
        raise StateConflict("仓库已有库存 API 绑定，请明确确认后再更换绑定。")
    if active and replace and expected_authorization_id is None:
        raise StateConflict("更换仓库 API 绑定必须携带当前授权记录 ID，请刷新页面后重试。")
    if active and expected_authorization_id is not None and int(expected_authorization_id) != active.id:
        raise StateConflict("仓库授权状态已变化，请刷新页面后重新操作。")

    now = timezone.now()
    previous_id = active.id if active else None
    if active:
        active.status = WarehouseAuthorization.Status.REVOKED
        active.revoked_at = now
        active.active_warehouse_binding_key = None
        active.updated_by = actor
        active.last_error_code = ""
        active.save(
            update_fields=[
                "status",
                "revoked_at",
                "active_warehouse_binding_key",
                "updated_by",
                "last_error_code",
                "updated_at",
            ]
        )
        SyncJob.objects.filter(
            tenant=actor.tenant,
            warehouse_authorization=active,
        ).update(is_enabled=False, status=SyncJob.Status.DISABLED, next_run_at=None)

    record = WarehouseAuthorization(
        tenant=actor.tenant,
        integration_config=integration_config,
        warehouse=warehouse,
        provider=provider,
        # These are opaque references from the managed configuration.  The
        # API never accepts client-supplied credential values.
        credential_id=integration_config.credential_id,
        token_id=integration_config.token_id,
        credential_mask=dict(integration_config.credential_mask or {}),
        status=WarehouseAuthorization.Status.ACTIVE,
        authorized_at=now,
        last_error_code="",
        active_warehouse_binding_key=binding_key,
        created_by=actor,
        updated_by=actor,
    )
    try:
        with authorization_service_write():
            record.full_clean()
            record.save()
    except IntegrityError as exc:
        raise StateConflict("仓库授权已被其他操作更新，请刷新后重试。") from exc

    action = "warehouse_rebind" if previous_id else "warehouse_authorize"
    _audit(
        record=record,
        actor=actor,
        action=action,
        detail={
            "authorization_id": record.id,
            "warehouse_id": warehouse.id,
            "warehouse_code": warehouse.code,
            "provider": provider,
            "integration_config_id": integration_config.id,
            "previous_authorization_id": previous_id,
            "idempotency_key_hash": key_hash,
            "payload_digest": payload_digest,
            "external_api_called": False,
            "raw_credentials_received": False,
        },
    )
    return record, False, action


@transaction.atomic
def revoke_warehouse_authorization(*, actor, authorization):
    """Revoke a tenant-scoped binding and disable dependent inventory jobs."""
    if actor.tenant_id != authorization.tenant_id:
        raise ValidationError("授权记录不属于当前租户。")
    locked = WarehouseAuthorization.objects.select_for_update().select_related(
        "warehouse", "integration_config"
    ).get(pk=authorization.pk)
    if locked.status == WarehouseAuthorization.Status.REVOKED:
        return locked, True
    previous_status = locked.status
    locked.status = WarehouseAuthorization.Status.REVOKED
    locked.revoked_at = timezone.now()
    locked.active_warehouse_binding_key = None
    locked.updated_by = actor
    locked.last_error_code = ""
    disabled_jobs = SyncJob.objects.filter(
        tenant=actor.tenant,
        warehouse_authorization=locked,
    ).update(is_enabled=False, status=SyncJob.Status.DISABLED, next_run_at=None)
    locked.save(
        update_fields=[
            "status",
            "revoked_at",
            "active_warehouse_binding_key",
            "updated_by",
            "last_error_code",
            "updated_at",
        ]
    )
    _audit(
        record=locked,
        actor=actor,
        action="warehouse_revoke",
        detail={
            "authorization_id": locked.id,
            "warehouse_id": locked.warehouse_id,
            "warehouse_code": locked.warehouse.code,
            "provider": locked.provider,
            "integration_config_id": locked.integration_config_id,
            "previous_status": previous_status,
            "disabled_job_count": disabled_jobs,
            "external_api_called": False,
            "raw_credentials_received": False,
        },
    )
    return locked, False
