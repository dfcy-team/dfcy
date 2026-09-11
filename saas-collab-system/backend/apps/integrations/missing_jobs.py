"""Read-only missing-task preview. Never creates jobs or resolves credentials."""
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.permissions.ui_p6_scopes import integration_values_allowed

from .capability_gate import require_sync_read_capability
from .models import MarketplaceStoreAuthorization, SyncJob, WarehouseAuthorization
from .platform_capabilities import CAPABILITY_REGISTRY
from .warehouse_credential_service import require_verified_warehouse


def preview_missing_jobs(user):
    rows = []
    subjects = (
        ("store", MarketplaceStoreAuthorization.objects.filter(tenant=user.tenant)
         .exclude(status=MarketplaceStoreAuthorization.Status.REVOKED)
         .select_related("integration_config", "store")),
        ("warehouse", WarehouseAuthorization.objects.filter(tenant=user.tenant)
         .exclude(status=WarehouseAuthorization.Status.REVOKED)
         .select_related("integration_config", "warehouse")),
    )
    existing = set(SyncJob.objects.filter(tenant=user.tenant).values_list(
        "store_authorization_id", "warehouse_authorization_id", "resource_type",
    ))
    for kind, authorizations in subjects:
        for authorization in authorizations.order_by("id"):
            config = authorization.integration_config
            if config.tenant_id != user.tenant_id:
                continue
            capability = CAPABILITY_REGISTRY.get(config.platform)
            if capability is None:
                continue
            store_id = authorization.store_id if kind == "store" else None
            warehouse_id = authorization.warehouse_id if kind == "warehouse" else None
            subject = authorization.store if kind == "store" else authorization.warehouse
            if subject.tenant_id != user.tenant_id:
                continue
            region = authorization.region if kind == "store" else subject.country_code
            regions = list(dict.fromkeys([*(config.regions or []), region or "__UNKNOWN__"]))
            for resource, modes in capability.resources.items():
                if "live_readonly" not in modes:
                    continue
                if (kind == "warehouse") != (resource == "inventory_snapshot"):
                    continue
                if not integration_values_allowed(
                    user, "integrations.manage", platform=config.platform,
                    environment=config.environment, regions=regions, config_id=config.id,
                    resource_type=resource, store_id=store_id, warehouse_id=warehouse_id,
                ):
                    continue
                key = (authorization.id if kind == "store" else None,
                       authorization.id if kind == "warehouse" else None, resource)
                if key in existing:
                    continue
                blockers = []
                if subject.status != "active":
                    blockers.append("店铺或仓库档案未启用")
                if config.status not in ("active", "verified") or not config.sync_read_enabled:
                    blockers.append("公共配置未启用只读同步")
                if config.credential_status != "configured" or not config.credential_id:
                    blockers.append("公共凭据尚未配置")
                if authorization.status != "active":
                    blockers.append("主体授权未启用")
                if not authorization.credential_id or not authorization.token_id:
                    blockers.append("主体凭据引用缺失")
                if config.sync_write_enabled:
                    blockers.append("公共配置启用了写同步")
                if config.environment not in ("pilot", "production"):
                    blockers.append("公共配置不是试运行或生产类型")
                job = SyncJob(tenant=user.tenant, integration_config=config, resource_type=resource)
                if kind == "store":
                    job.store_authorization = authorization
                    if authorization.expires_at and authorization.expires_at <= timezone.now():
                        blockers.append("主体授权已过期")
                    try:
                        require_sync_read_capability(job, "live_readonly")
                    except ValidationError:
                        blockers.append("只读能力未启用或当前授权不是选定来源")
                else:
                    try:
                        require_verified_warehouse(authorization)
                    except ValidationError:
                        blockers.append("仓库凭据不完整或尚未通过只读校验")
                rows.append({
                    "subject_type": kind, "subject_id": subject.id, "subject_name": subject.name,
                    "authorization_id": authorization.id, "integration_config_id": config.id,
                    "resource_type": resource, "status": "blocked" if blockers else "missing",
                    "blockers": blockers,
                })
    return {"items": rows, "preview_only": True, "created_count": 0,
            "notice": "仅预览缺失任务；不创建、启用或执行任务。无阻断不代表已连通，执行仍须通过现有门禁。"}
