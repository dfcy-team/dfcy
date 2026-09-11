"""Resolve warehouse identity with an existing OAuth token, never bootstrap."""

from django.core.exceptions import ValidationError as ModelValidationError
from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError

from apps.common.exceptions import StateConflict
from .models import PlatformIntegrationConfig, SyncJob, WarehouseAuthorization
from .net_guard import PlatformHttpClient
from .readonly_clients import JifengWmsReadonlyClient
from .warehouse_authorization_service import _audit, validate_warehouse_binding


def discover_warehouse(*, actor, authorization, external_warehouse_code=None, http=None, custody=None):
    record = WarehouseAuthorization.objects.select_related("integration_config", "warehouse").get(
        pk=authorization.pk, tenant_id=actor.tenant_id)
    config = record.integration_config
    if record.provider != "jifeng_wms" or record.status != WarehouseAuthorization.Status.ACTIVE:
        raise ValidationError("仓库授权已失效，请刷新页面。")
    validate_warehouse_binding(actor=actor, warehouse=record.warehouse, integration_config=config,
        external_warehouse_code=record.external_warehouse_code)
    client = JifengWmsReadonlyClient(config, record, custody=custody,
        http_client=http if http is not None else PlatformHttpClient(max_retries=0))
    warehouses = client.fetch_warehouses()
    region = (record.external_warehouse_region or record.warehouse.country_code).upper()
    for item in warehouses:
        item["selectable"] = item["is_authorized"] and item["country"] == region
    eligible = {item["code"]: item for item in warehouses if item["selectable"]}
    chosen = external_warehouse_code or record.external_warehouse_code
    if external_warehouse_code is not None and external_warehouse_code not in eligible:
        raise ValidationError("所选仓库不在当前账号授权且国家匹配的仓库列表中，原关联未更改。")
    if not chosen and len(warehouses) == 1 and len(eligible) == 1:
        chosen = next(iter(eligible))
    state = "linked" if chosen in eligible else ("selection_required" if eligible else "unavailable")
    with transaction.atomic():
        live_config = PlatformIntegrationConfig.objects.select_for_update().get(pk=config.pk, tenant_id=actor.tenant_id)
        current = WarehouseAuthorization.objects.select_for_update().select_related("warehouse").get(
            pk=record.pk, tenant_id=actor.tenant_id)
        if (live_config.config_version != config.config_version or live_config.updated_at != config.updated_at
                or current.updated_at != record.updated_at or current.token_id != record.token_id
                or current.external_warehouse_code != record.external_warehouse_code
                or current.status != WarehouseAuthorization.Status.ACTIVE
                or current.warehouse.updated_at != record.warehouse.updated_at):
            raise StateConflict("读取期间配置、凭据或仓库已变化，请刷新后重新获取仓库列表。")
        validate_warehouse_binding(actor=actor, warehouse=current.warehouse, integration_config=live_config,
            external_warehouse_code=chosen or "")
        if state == "linked" and chosen != current.external_warehouse_code:
            if SyncJob.objects.filter(warehouse_authorization=current, status=SyncJob.Status.RUNNING).exists():
                raise StateConflict("仓库仍有运行中的同步任务，请待任务结束后再关联仓库编号。")
            previous_code = current.external_warehouse_code
            current.external_warehouse_code = chosen
            current.external_warehouse_region = region
            current.validation_status = WarehouseAuthorization.ValidationStatus.PENDING
            current.last_verified_at = None
            current.last_error_code = ""
            current.updated_by = actor
            try:
                with transaction.atomic():
                    current.full_clean()
                    current.save(update_fields=["external_warehouse_code", "external_warehouse_region",
                        "validation_status", "last_verified_at", "last_error_code", "updated_by", "updated_at"])
            except (IntegrityError, ModelValidationError):
                raise StateConflict("仓库编号存在绑定冲突，未更改原关联；请检查是否已绑定其他本地仓库。") from None
            disabled = SyncJob.objects.filter(tenant_id=actor.tenant_id, warehouse_authorization=current).update(
                is_enabled=False, status=SyncJob.Status.DISABLED, next_run_at=None)
            _audit(record=current, actor=actor, action="warehouse_identity_resolve", detail={
                "warehouse_id": current.warehouse_id, "authorization_id": current.pk,
                "previous_external_warehouse_code": previous_code, "external_warehouse_code": chosen,
                "external_warehouse_region": region, "disabled_job_count": disabled,
                "external_api_called": True,
            })
    messages = {
        "linked": "仓库编号已关联；尚未完成库存只读校验。",
        "selection_required": "已获取仓库列表，请选择本地档案对应的仓库并确认关联。",
        "unavailable": "列表中没有明确授权且国家匹配的仓库，未更改关联。请核对 OMS 仓库权限和国家。",
    }
    return current, {"status": state, "warehouses": warehouses, "message": messages[state]}
