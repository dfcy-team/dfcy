"""Approved, expiry-driven renewal of existing marketplace/WMS custody references."""
from datetime import timedelta
from hashlib import sha256

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.permissions.services import user_has_integration_permission
from apps.permissions.ui_p6_scopes import integration_values_allowed
from .models import (
    AutomaticRefreshAttempt, IntegrationAuditLog, MarketplaceStoreAuthorization,
    SyncRun, SyncSchedulerHeartbeat, WarehouseAuthorization,
)
from .production_settings import get_runtime_platform_config


def _platform(record):
    return record.platform if isinstance(record, MarketplaceStoreAuthorization) else "jifeng_wms"


def _actor_allowed(record):
    actor = record.updated_by
    config = record.integration_config
    if (not actor.is_active or actor.user_type != "internal" or actor.tenant_id != record.tenant_id
            or config.tenant_id != record.tenant_id):
        return False
    warehouse = isinstance(record, WarehouseAuthorization)
    codes = ("integrations.warehouse.authorize",) if warehouse else (
        "integrations.store.authorize", "integrations.credential.rotate",
    )
    return all(
        user_has_integration_permission(actor, code) and integration_values_allowed(
            actor, code, platform=config.platform, environment=config.environment,
            regions=[record.external_warehouse_region] if warehouse else [record.region],
            config_id=config.pk,
            warehouse_id=record.warehouse_id if warehouse else None,
            store_id=None if warehouse else record.store_id,
        ) for code in codes
    )


def automatic_refresh_allowed(record):
    warehouse = isinstance(record, WarehouseAuthorization)
    platform = _platform(record)
    if (record.status != "active" or not record.token_id
            or record.integration_config.environment not in {"pilot", "production"}
            or record.integration_config.status not in {"verified", "active"}
            or not get_runtime_platform_config(platform).get("auto_refresh_enabled", False)):
        return False
    if warehouse and (record.provider != "jifeng_wms" or not record.oauth_user_id):
        return False
    if not warehouse and record.platform not in {"lazada", "shopee", "tiktok"}:
        return False
    expiry = record.oauth_expires_at if warehouse else record.expires_at
    if not expiry or expiry > timezone.now() + timedelta(minutes=15) or not _actor_allowed(record):
        return False
    binding = "warehouse_authorization" if warehouse else "store_authorization"
    return not SyncRun.objects.filter(**{f"sync_job__{binding}_id": record.pk}, status="running").exists()


def require_automatic_refresh(record, expected_token_id):
    if record.token_id != expected_token_id or not automatic_refresh_allowed(record):
        raise ValidationError("AUTO_REFRESH_CONDITIONS_CHANGED")


def refresh_due_authorizations(limit=100):
    from .marketplace_oauth_service import refresh_marketplace_authorization
    from .warehouse_credential_service import refresh_warehouse_authorization

    SyncSchedulerHeartbeat.objects.update_or_create(
        key="credential-refresh", defaults={"last_seen_at": timezone.now()},
    )
    due = timezone.now() + timedelta(minutes=15)
    sources = (
        ("lazada", MarketplaceStoreAuthorization.objects.filter(platform="lazada", status="active", expires_at__lte=due)),
        ("shopee", MarketplaceStoreAuthorization.objects.filter(platform="shopee", status="active", expires_at__lte=due)),
        ("tiktok", MarketplaceStoreAuthorization.objects.filter(platform="tiktok", status="active", expires_at__lte=due)),
        ("jifeng_wms", WarehouseAuthorization.objects.filter(provider="jifeng_wms", status="active", oauth_expires_at__lte=due)),
    )
    counts = {"attempted": 0, "success": 0, "failed": 0}
    for platform, queryset in sources:
        if not get_runtime_platform_config(platform).get("auto_refresh_enabled", False):
            continue
        for record in queryset.select_related("integration_config", "updated_by").iterator():
            if counts["attempted"] >= max(1, min(int(limit), 100)):
                return counts
            if not automatic_refresh_allowed(record):
                continue
            # Only a one-way digest is persisted; no token or custody reference
            # is exposed in logs, task results or the settings response.
            key = sha256(f"{platform}:{record.tenant_id}:{record.pk}:{record.token_id}".encode()).hexdigest()
            attempt, created = AutomaticRefreshAttempt.objects.get_or_create(
                request_key=key, defaults={"tenant_id": record.tenant_id},
            )
            if not created:
                continue
            counts["attempted"] += 1
            result = "failed"
            detail = {"automatic": True, "platform": platform, "authorization_id": record.pk}
            try:
                if platform in {"lazada", "shopee", "tiktok"}:
                    refresh_marketplace_authorization(record, actor=record.updated_by, expected_token_id=record.token_id)
                else:
                    refresh_warehouse_authorization(actor=record.updated_by, authorization=record,
                        automatic=True, expected_token_id=record.token_id)
                result = "success"
            except Exception:
                # Provider payloads/URLs can include credentials. Never stringify
                # the exception here, and never replay an ambiguous rotation.
                detail.update(error_code="AUTO_REFRESH_FAILED", reason="自动续期未完成；请检查授权、权限、准入及网络，手动刷新或重新授权后恢复。")
            attempt.status, attempt.finished_at = result, timezone.now()
            attempt.save(update_fields=["status", "finished_at"])
            IntegrationAuditLog.objects.create(
                tenant_id=record.tenant_id, integration_config=record.integration_config,
                store_authorization=record if platform in {"lazada", "shopee", "tiktok"} else None,
                actor=record.updated_by, action="automatic_refresh", result=result, masked_detail=detail,
            )
            counts[result] += 1
    return counts
