"""Approved, expiry-driven renewal of existing marketplace/WMS custody references."""
from datetime import timedelta
from hashlib import sha256
from copy import copy
import time

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.permissions.services import user_has_integration_permission
from apps.permissions.ui_p6_scopes import integration_values_allowed
from .models import (
    AutomaticRefreshAttempt, IntegrationAuditLog, MarketplaceStoreAuthorization,
    SyncJob, SyncRun, SyncSchedulerHeartbeat, WarehouseAuthorization,
)
from .oauth_errors import OAUTH_AUTH_REJECTED, OAuthFlowError
from .production_settings import get_runtime_platform_config


AUTO_REFRESH_VALIDATION_PENDING = "AUTO_REFRESH_VALIDATION_PENDING"
AUTO_REFRESH_VALIDATION_FAILED = "AUTO_REFRESH_VALIDATION_FAILED"
VALIDATION_RETRY_DELAYS = (2, 5, 15)


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
    if record.last_error_code == AUTO_REFRESH_VALIDATION_FAILED:
        return False
    if warehouse and (record.provider != "jifeng_wms" or not record.oauth_user_id):
        return False
    if not warehouse and record.platform not in {"lazada", "shopee", "tiktok"}:
        return False
    expiry = record.oauth_expires_at if warehouse else record.expires_at
    if (not expiry or expiry > timezone.now() + timedelta(minutes=15)
            or not _actor_allowed(record)):
        return False
    binding = "warehouse_authorization" if warehouse else "store_authorization"
    return not SyncRun.objects.filter(**{f"sync_job__{binding}_id": record.pk}, status="running").exists()


def require_automatic_refresh(record, expected_token_id):
    if record.token_id != expected_token_id or not automatic_refresh_allowed(record):
        raise ValidationError("AUTO_REFRESH_CONDITIONS_CHANGED")


def _mark_validation_pending(record):
    if isinstance(record, WarehouseAuthorization):
        WarehouseAuthorization.objects.filter(pk=record.pk, token_id=record.token_id).update(
            validation_status=WarehouseAuthorization.ValidationStatus.PENDING,
            last_verified_at=None,
            last_error_code=AUTO_REFRESH_VALIDATION_PENDING,
        )
        record.validation_status = WarehouseAuthorization.ValidationStatus.PENDING
        record.last_verified_at = None
    else:
        from .models import authorization_service_write

        record.last_error_code = AUTO_REFRESH_VALIDATION_PENDING
        record.status = MarketplaceStoreAuthorization.Status.ACTIVE
        with authorization_service_write():
            record.save(update_fields=["status", "last_error_code", "updated_at"])
    record.last_error_code = AUTO_REFRESH_VALIDATION_PENDING


def _mark_validation_success(record):
    now = timezone.now()
    if isinstance(record, WarehouseAuthorization):
        WarehouseAuthorization.objects.filter(pk=record.pk, token_id=record.token_id).update(
            validation_status=WarehouseAuthorization.ValidationStatus.VERIFIED,
            last_verified_at=now,
            last_error_code="",
        )
        record.validation_status = WarehouseAuthorization.ValidationStatus.VERIFIED
        record.last_verified_at = now
    else:
        from .models import authorization_service_write

        record.last_error_code = ""
        record.status = MarketplaceStoreAuthorization.Status.ACTIVE
        with authorization_service_write():
            record.save(update_fields=["status", "last_error_code", "updated_at"])
    record.last_error_code = ""


def _mark_validation_failed(record, message="刷新接口成功，但新令牌只读校验失败；请核对权限和店铺绑定后重新验证。"):
    if isinstance(record, WarehouseAuthorization):
        WarehouseAuthorization.objects.filter(pk=record.pk, token_id=record.token_id).update(
            validation_status=WarehouseAuthorization.ValidationStatus.FAILED,
            last_verified_at=None,
            last_error_code=AUTO_REFRESH_VALIDATION_FAILED,
        )
        record.last_error_code = AUTO_REFRESH_VALIDATION_FAILED
        record.validation_status = WarehouseAuthorization.ValidationStatus.FAILED
    else:
        from .models import authorization_service_write

        record.status = MarketplaceStoreAuthorization.Status.ERROR
        record.last_error_code = AUTO_REFRESH_VALIDATION_FAILED
        with authorization_service_write():
            record.save(update_fields=["status", "last_error_code", "updated_at"])
    _pause_validation_jobs(record, AUTO_REFRESH_VALIDATION_FAILED, message)


def _pause_validation_jobs(record, error_code, message):
    binding = "warehouse_authorization_id" if isinstance(record, WarehouseAuthorization) else "store_authorization_id"
    jobs = SyncJob.objects.filter(**{binding: record.pk})
    affected_jobs = list(jobs.select_related("tenant", "integration_config__created_by"))
    jobs.update(is_enabled=False, status=SyncJob.Status.DISABLED, next_run_at=None)
    from .sync_alerts import upsert_sync_failure_alert

    for job in affected_jobs:
        try:
            upsert_sync_failure_alert(
                job,
                error_code=error_code,
                message=message + "关联同步任务已暂停。",
            )
        except Exception:
            # Alert delivery must not undo authorization quarantine or expose
            # the provider response through a secondary failure path.
            continue


def validate_refreshed_authorization(record):
    """Perform one real, minimal read using the newly persisted token."""
    from .net_guard import PlatformHttpClient

    record = copy(record)
    record.last_error_code = ""
    http_client = PlatformHttpClient(max_retries=0)
    if isinstance(record, WarehouseAuthorization):
        from .readonly_clients import JifengWmsReadonlyClient

        return JifengWmsReadonlyClient(record.integration_config, record, http_client=http_client).fetch_inventory(
            None, {"page_size": 1},
        )

    if record.platform == "lazada":
        from .readonly_clients import LazadaReadonlyClient

        return LazadaReadonlyClient(record.integration_config, record, http_client=http_client).validate_token()

    from .marketplace_oauth_service import resolve_oauth_provider

    provider = resolve_oauth_provider(record.platform, record.integration_config)
    if isinstance(getattr(provider, "http", None), PlatformHttpClient):
        provider.http = http_client
    stores = provider.fetch_authorized_stores(record)
    if not any(str(item.get("platform_store_id")) == str(record.platform_store_id)
               for item in stores if isinstance(item, dict)):
        raise ValidationError("Refreshed token readonly validation did not return the bound store.")
    return stores


def _definitive_authorization_failure(exc):
    if isinstance(exc, OAuthFlowError):
        return exc.controlled_code == OAUTH_AUTH_REJECTED
    return getattr(exc, "status_code", None) in {401, 403} or "认证失败" in str(getattr(exc, "detail", ""))


def _retryable_validation_failure(exc):
    return isinstance(exc, (TimeoutError, ConnectionError)) or (
        isinstance(exc, OAuthFlowError)
        and getattr(exc, "category", None) in {"timeout_uncertain", "network_uncertain"}
    )


def _validate_with_retries(record):
    delays = iter(VALIDATION_RETRY_DELAYS)
    while True:
        try:
            return validate_refreshed_authorization(record)
        except Exception as exc:
            if _definitive_authorization_failure(exc) or not _retryable_validation_failure(exc):
                raise
            try:
                delay = next(delays)
            except StopIteration:
                raise exc from None
            time.sleep(delay)


def _record_validation_error(record, exc):
    diagnostic = {}
    for key, allowed in (
        ("stage", {"verify_store", "read_developer_secret", "save_token", "exchange_token"}),
        ("controlled_code", {"OAUTH_AUTH_REJECTED", "OAUTH_PROVIDER_ERROR", "OAUTH_PROVIDER_UNAVAILABLE", "OAUTH_CALLBACK_REJECTED"}),
        ("identity_evidence", {"shop_id_missing", "shop_id_mismatch", "invalid_shop_response", "invalid_token_scope", "token_scope_mismatch"}),
    ):
        value = getattr(exc, key, None)
        if isinstance(value, str) and value in allowed:
            diagnostic[key] = value
    status = getattr(exc, "http_status", None)
    if type(status) is int and 100 <= status <= 599:
        diagnostic["http_status"] = status
    if _retryable_validation_failure(exc) and not _definitive_authorization_failure(exc):
        _mark_validation_pending(record)
        message = "新令牌已保存，但网络校验未完成；请重新验证，不要重复刷新令牌。"
        _pause_validation_jobs(record, AUTO_REFRESH_VALIDATION_PENDING, message)
        return {**diagnostic, "error_code": AUTO_REFRESH_VALIDATION_PENDING, "reason": message,
                "reauthorization_required": False, "validation_category": "network_uncertain"}
    rejected = _definitive_authorization_failure(exc)
    message = ("刷新接口成功，但新令牌只读校验失败：平台拒绝认证，请重新授权。" if rejected else
               "刷新接口成功，但新令牌只读校验失败；请核对权限、配置和店铺绑定后重新验证。")
    _mark_validation_failed(record, message)
    return {**diagnostic, "error_code": AUTO_REFRESH_VALIDATION_FAILED, "reason": message,
            "reauthorization_required": rejected,
            "validation_category": "authorization_rejected" if rejected else "readonly_validation_failed"}


@transaction.atomic
def revalidate_saved_authorization(record, *, actor):
    """Revalidate a saved token, renewing it first only when it has expired."""
    expected_token_id = record.token_id
    record = type(record).objects.select_for_update().get(pk=record.pk, tenant_id=actor.tenant_id)
    if record.token_id != expected_token_id:
        raise ValidationError("授权令牌已变化，请刷新页面后重试。")
    if (record.status not in {"active", "error"} or not record.token_id
            or record.last_error_code not in {AUTO_REFRESH_VALIDATION_PENDING, AUTO_REFRESH_VALIDATION_FAILED}):
        raise ValidationError("当前授权没有待验证的新令牌。")
    binding = "warehouse_authorization" if isinstance(record, WarehouseAuthorization) else "store_authorization"
    if SyncRun.objects.filter(**{f"sync_job__{binding}_id": record.pk}, status="running").exists():
        raise ValidationError("关联同步正在运行，请结束后再验证令牌。")
    detail = {"token_refreshed": False}
    expiry = record.oauth_expires_at if isinstance(record, WarehouseAuthorization) else record.expires_at
    if expiry is not None and expiry <= timezone.now():
        if isinstance(record, WarehouseAuthorization):
            from .warehouse_credential_service import refresh_warehouse_authorization

            record = refresh_warehouse_authorization(actor=actor, authorization=record)
        else:
            from .marketplace_oauth_service import refresh_marketplace_authorization

            record = refresh_marketplace_authorization(record, actor=actor)
        # Commit the new reference even when the subsequent read fails.
        _mark_validation_pending(record)
        detail["token_refreshed"] = True
    candidate = copy(record)
    candidate.status = "active"
    try:
        _validate_with_retries(candidate)
        _mark_validation_success(record)
        result = "success"
    except Exception as exc:
        detail.update(_record_validation_error(record, exc))
        result = "failed"
    IntegrationAuditLog.objects.create(
        tenant_id=record.tenant_id, integration_config=record.integration_config,
        store_authorization=record if isinstance(record, MarketplaceStoreAuthorization) else None,
        actor=actor, action="revalidate_saved_token", result=result, masked_detail=detail,
    )
    return record


def refresh_due_authorizations(limit=100):
    from .marketplace_oauth_service import refresh_marketplace_authorization
    from .warehouse_credential_service import refresh_warehouse_authorization

    SyncSchedulerHeartbeat.objects.update_or_create(
        key="credential-refresh", defaults={"last_seen_at": timezone.now()},
    )
    due = timezone.now() + timedelta(minutes=15)
    sources = (
        ("lazada", MarketplaceStoreAuthorization.objects.filter(expires_at__lte=due, platform="lazada", status="active")),
        ("shopee", MarketplaceStoreAuthorization.objects.filter(expires_at__lte=due, platform="shopee", status="active")),
        ("tiktok", MarketplaceStoreAuthorization.objects.filter(expires_at__lte=due, platform="tiktok", status="active")),
        ("jifeng_wms", WarehouseAuthorization.objects.filter(oauth_expires_at__lte=due, provider="jifeng_wms", status="active")),
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
            detail = {"automatic": True, "platform": platform, "authorization_id": record.pk,
                      "readonly_validation_performed": False, "token_saved": False}
            try:
                if platform in {"lazada", "shopee", "tiktok"}:
                    record = refresh_marketplace_authorization(
                        record, actor=record.updated_by, expected_token_id=record.token_id,
                    )
                else:
                    record = refresh_warehouse_authorization(
                        actor=record.updated_by, authorization=record,
                        automatic=True, expected_token_id=record.token_id,
                    )
                detail["token_saved"] = True
                result = "success"
            except Exception as exc:
                # Provider payloads/URLs can include credentials. Never stringify
                # the exception here, and never replay an ambiguous rotation.
                detail.update(error_code="AUTO_REFRESH_FAILED", reason="自动续期未完成；请检查授权、权限、准入及网络，手动刷新或重新授权后恢复。")
            attempt.status = result
            attempt.finished_at = timezone.now()
            attempt.save(update_fields=["status", "finished_at"])
            IntegrationAuditLog.objects.create(
                tenant_id=record.tenant_id, integration_config=record.integration_config,
                store_authorization=record if platform in {"lazada", "shopee", "tiktok"} else None,
                actor=record.updated_by, action="automatic_refresh", result=result, masked_detail=detail,
            )
            counts[result] += 1
    return counts
