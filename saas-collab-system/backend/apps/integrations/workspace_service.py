import json

from django.db import connection
from django.db.models import Case, CharField, Count, DateTimeField, F, Func, OuterRef, Q, Subquery, Value, When
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Coalesce, Concat, Replace, Substr
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from apps.audit.models import NotificationMessage
from apps.masterdata.models import CountrySiteMaster, PlatformMaster, WarehouseMaster
from apps.permissions.ui_p6_scopes import filter_integration_configs, filter_sync_jobs, filter_sync_runs

from .models import (
    MarketplaceStoreAuthorization,
    PlatformIntegrationConfig,
    SyncCheckpoint,
    SyncAlertIncident,
    SyncJob,
    SyncRun,
    SyncScheduleDispatch,
    WarehouseAuthorization,
)
from .platform_schema_service import get_platform_schema, integration_platform_key, platform_api_type_options
from .capability_gate import sync_source_health, sync_source_health_for_jobs
from .production_settings import get_runtime_platform_config, get_runtime_setting
from .scheduler import paused_until, scheduler_health
from .automatic_refresh import credential_refresh_state, credential_scheduler_health
from .sync_policy import recommended_policy


RESOURCE_DESTINATIONS = {
    "platform_product": ("平台商品档案", "listings_platformproductdetail / integrations_marketplaceproductmapping"),
    "sales_order": ("销售订单", "sales_order / sales_order_item"),
    "settlement_bill": ("财务流水", "platform_finance_transaction"),
    "advertising_report": ("Shopee 广告数据", "shopee_advertising_record"),
    "refund_return": ("退款退货", "refund_return / refund_return_item"),
    "inventory_snapshot": ("库存分析", "inventory_snapshot"),
}


def _table_columns(table_name):
    with connection.cursor() as cursor:
        if table_name not in connection.introspection.table_names(cursor):
            return set()
        return {column.name for column in connection.introspection.get_table_description(cursor, table_name)}


def _raw_map(table_name, requested_columns, ids):
    ids = list(ids)
    available = _table_columns(table_name)
    columns = [column for column in requested_columns if column in available]
    if not ids or "id" not in columns:
        return {}
    placeholders = ",".join(["%s"] * len(ids))
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT {','.join(columns)} FROM {table_name} WHERE id IN ({placeholders})",
            ids,
        )
        return {row[0]: dict(zip(columns, row)) for row in cursor.fetchall()}


def _json_value(value):
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}


def _boolean_value(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _api_type(config, raw_config):
    value = str(raw_config.get("api_type") or config.platform_config.get("api_type") or "").strip()
    if value:
        return value
    return "inventory" if config.platform == "jifeng_wms" else "marketplace"


def _masked_fingerprint(value):
    value = str(value or "")
    return f"{value[:12]}…" if len(value) > 12 else value or "—"


def _format_datetime(value):
    if not value:
        return None
    if isinstance(value, str):
        return value
    return timezone.localtime(value).isoformat(timespec="seconds") if timezone.is_aware(value) else value.isoformat(timespec="seconds")


def _subject_maps(jobs, allowed_config_ids):
    store_ids = {job.store_authorization_id for job in jobs if job.store_authorization_id}
    stores = {
        item.id: item
        for item in MarketplaceStoreAuthorization.objects.filter(
            id__in=store_ids,
            integration_config_id__in=allowed_config_ids,
        ).select_related("store")
    }
    warehouse_ids = {job.warehouse_authorization_id for job in jobs if job.warehouse_authorization_id}
    warehouse_auth = {
        item.id: item
        for item in WarehouseAuthorization.objects.filter(
            id__in=warehouse_ids,
            integration_config_id__in=allowed_config_ids,
        ).select_related("warehouse")
    }
    warehouse_master = {item.warehouse_id: item.warehouse for item in warehouse_auth.values()}
    return stores, warehouse_auth, warehouse_master


def _subject(job, stores, warehouse_auth, warehouse_master):
    if job.store_authorization_id in stores:
        auth = stores[job.store_authorization_id]
        return {
            "subject_type": "store",
            "store_id": auth.store_id,
            "subject_code": auth.store.code,
            "subject_name": auth.store.name,
            "region": auth.region,
            "authorization_status": auth.status,
            "external_subject_id": auth.platform_store_id,
        }
    warehouse_row = warehouse_auth.get(job.warehouse_authorization_id)
    warehouse = warehouse_master.get(warehouse_row.warehouse_id) if warehouse_row else None
    if warehouse:
        return {
            "subject_type": "warehouse",
            "warehouse_id": warehouse.id,
            "store_id": None,
            "subject_code": warehouse.code,
            "subject_name": warehouse.name,
            "region": warehouse.country_code,
            "authorization_status": warehouse_row.status,
            "external_subject_id": "",
        }
    return {
        "subject_type": "unbound",
        "store_id": None,
        "subject_code": "",
        "subject_name": "未绑定",
        "region": "",
        "authorization_status": "",
        "external_subject_id": "",
    }


def _schedule_state(job, latest_run, queued_dispatches=None):
    now = timezone.now()
    if not job.is_enabled or job.status == SyncJob.Status.DISABLED:
        return "disabled"
    pause = paused_until(job)
    if pause and pause > now:
        return "paused"
    if (job.schedule_dispatches.filter(status="queued").exists() if queued_dispatches is None
            else job.pk in queued_dispatches):
        return "queued"
    if latest_run and latest_run.status == SyncRun.Status.QUEUED and not (
        latest_run.history_segment_id and latest_run.history_segment.batch.status == "paused"
    ):
        return "queued"
    retry_at = parse_datetime(str(_json_value(latest_run.masked_log).get("next_retry_at") or "")) if latest_run else None
    if latest_run and latest_run.status == SyncRun.Status.RUNNING and retry_at and retry_at > now:
        return "retry_waiting"
    if job.status == SyncJob.Status.RUNNING or (job.lock_expires_at and job.lock_expires_at > now):
        return "running"
    if job.status == SyncJob.Status.FAILED and not job.next_run_at:
        return "retry_exhausted"
    if job.schedule_type == SyncJob.ScheduleType.MANUAL:
        return "manual"
    if not job.next_run_at:
        return "unscheduled"
    if job.next_run_at <= now:
        return "due"
    return "scheduled"


def _checkpoint_map(job_ids):
    return {
        checkpoint.sync_job_id: {
            "version": checkpoint.version,
            "watermark": checkpoint.watermark_utc,
        }
        for checkpoint in SyncCheckpoint.objects.filter(sync_job_id__in=job_ids)
    }


def _job_row(job, raw_config, subject, latest_run, checkpoint=None, context=None):
    scope = _json_value(job.sync_scope)
    query_scope = _json_value(scope.get("query"))
    schedule_scope = _json_value(scope.get("schedule"))
    latest_log = _json_value(latest_run.masked_log) if latest_run else {}
    destination = RESOURCE_DESTINATIONS.get(job.resource_type, (job.resource_type, job.resource_type))
    execution_mode = str(scope.get("execution_mode") or "simulation")
    schedule_state = _schedule_state(job, latest_run, context["queued_dispatches"] if context is not None else None)
    config_ready = (
        job.integration_config.status != PlatformIntegrationConfig.Status.DISABLED
        and job.integration_config.credential_status in {"configured", "referenced", "verified"}
    )
    authorization_ready = subject["authorization_status"] in {"authorized", "active"}
    source_health = context["source_health"][job.pk] if context is not None else sync_source_health(job)
    capability_ready = source_health["state"] in {"ready", "not_required"}
    if not job.is_enabled:
        health_state = "disabled"
    elif subject["subject_type"] == "unbound" or not authorization_ready:
        health_state = "authorization"
    elif not config_ready:
        health_state = "configuration"
    elif not capability_ready:
        health_state = "capability"
    elif schedule_state == "running":
        health_state = "running"
    elif job.status == SyncJob.Status.FAILED or (latest_run and latest_run.status == SyncRun.Status.FAILED):
        health_state = "failed"
    elif schedule_state == "due":
        health_state = "due"
    else:
        health_state = "healthy"
    blocked_reason = ""
    if job.schedule_type == "cron":
        blocked_reason = "Cron 尚未开放，请修改为间隔、每日或每周计划"
    if subject["subject_type"] == "unbound":
        blocked_reason = "任务尚未绑定店铺或仓库授权"
    elif not authorization_ready:
        blocked_reason = "主体授权当前不可用"
    elif not config_ready:
        blocked_reason = "开发者凭据尚未就绪"
    elif source_health["state"] == "capability_missing":
        blocked_reason = "所需只读能力尚未启用"
    elif source_health["state"] == "source_not_selected":
        blocked_reason = "当前任务授权不是最高优先级来源"
    elif source_health["state"] == "unsupported":
        blocked_reason = "资源类型没有可执行的能力映射"
    if not blocked_reason and job.store_authorization_id:
        expires_at = job.store_authorization.expires_at
        if expires_at and expires_at <= timezone.now():
            blocked_reason = "授权已过期，请更新店铺授权"
    if not blocked_reason and job.integration_config.environment in {"pilot", "production"}:
        network_ready = (context["network_ready"] if context is not None
                         else get_runtime_setting("network", "readonly_sync_enabled", default=False))
        if not network_ready:
            blocked_reason = "系统只读准入未通过，请检查生产环境配置"
        elif job.integration_config.platform in {"shopee", "tiktok"}:
            contract = "product_contract_approved" if job.resource_type == "platform_product" else "contract_approved"
            platform_config = (context["platform_configs"][job.integration_config.platform] if context is not None
                               else get_runtime_platform_config(job.integration_config.platform))
            if not platform_config.get(contract):
                blocked_reason = "平台只读准入未通过，请检查生产环境配置"
    bound_authorization = job.store_authorization or job.warehouse_authorization
    if bound_authorization and context is not None:
        key = (type(bound_authorization), bound_authorization.pk)
        if key not in context["refresh_states"]:
            context["refresh_states"][key] = credential_refresh_state(bound_authorization)
        refresh_state = context["refresh_states"][key]
    else:
        refresh_state = credential_refresh_state(bound_authorization) if bound_authorization else None
    renewal_queued = False
    if refresh_state and refresh_state["expired"]:
        if job.is_enabled:
            health_state = "authorization"
        blocked_reason = "授权已过期，等待自动续期" if refresh_state["state"] in {"due", "refreshing", "retry_wait"} else "授权已过期，请检查续期状态并恢复授权"
    if (latest_run and latest_run.status == "queued" and latest_run.error_code == "WAITING_CREDENTIAL_REFRESH"
            and job.is_enabled and refresh_state):
        if refresh_state["state"] in {"due", "refreshing", "retry_wait"}:
            health_state, blocked_reason = "authorization", "等待自动续期；查询范围和采集断点已保留"
            renewal_queued = True
        elif refresh_state["requires_manual_recovery"]:
            health_state, blocked_reason = "authorization", "自动续期需人工处理；采集断点已保留"
        elif not blocked_reason:
            blocked_reason = "授权已更新，等待调度从原断点继续"
            renewal_queued = True
    row = {
        "id": job.id,
        "integration_config_id": job.integration_config_id,
        "platform": job.integration_config.platform,
        "api_type": _api_type(job.integration_config, raw_config),
        "account_alias": job.integration_config.account_alias,
        "config_name": job.integration_config.account_alias,
        "environment": job.integration_config.environment,
        "config_status": job.integration_config.status,
        "credential_status": job.integration_config.credential_status,
        "resource_type": job.resource_type,
        "schedule_type": job.schedule_type,
        "execution_mode": execution_mode,
        "strategy_profile": scope.get("strategy_profile", "legacy"),
        "incremental_anchor": query_scope.get("incremental_anchor", "lookback"),
        "recommended_policy": recommended_policy(job),
        "product_full_sync": bool(scope.get("product_full_sync", True)),
        "product_order_backfill": query_scope.get("product_order_backfill") or scope.get("product_order_backfill") or (
            "catalog_and_order_missing" if job.resource_type == "platform_product" and job.integration_config.platform == "shopee"
            else "catalog_only"
        ),
        "order_product_reconciliation": (latest_run.masked_log or {}).get("order_product_reconciliation") if latest_run else None,
        "status": job.status,
        "is_enabled": job.is_enabled,
        "max_retry_count": job.max_retry_count,
        "backoff_base_seconds": job.backoff_base_seconds,
        "query_mode": str(query_scope.get("mode") or scope.get("query_mode") or "incremental"),
        "advertising_datasets": query_scope.get("advertising_datasets", ["campaign", "campaign_daily", "shop_daily", "balance"]) if job.resource_type == "advertising_report" else [],
        "collection_time_basis": (
            query_scope.get("time_basis")
            or scope.get("time_basis")
            or ("created" if str(query_scope.get("mode") or scope.get("query_mode") or "incremental") == "range" else "updated")
        ) if job.resource_type == "sales_order" else None,
        "lookback_days": int(query_scope.get("lookback_days") or scope.get("lookback_days") or (job.integration_config.platform_config or {}).get("sync_scope", {}).get("lookback_days") or (7 if job.resource_type == "advertising_report" else 1)),
        "overlap_minutes": int(query_scope.get("overlap_minutes") if query_scope.get("overlap_minutes") is not None else scope.get("overlap_minutes") or 5),
        "query_page_size": int(query_scope.get("page_size") or scope.get("query_page_size") or 50),
        "max_pages": int(query_scope.get("max_pages") or scope.get("max_pages") or 100),
        "max_records": int(query_scope.get("max_records") or scope.get("max_records") or 50000),
        "range_start_at": query_scope.get("start_at") or scope.get("range_start_at"),
        "range_end_at": query_scope.get("end_at") or scope.get("range_end_at"),
        "interval_minutes": int(schedule_scope.get("interval_minutes") or scope.get("interval_minutes") or 60),
        "local_time": str(schedule_scope.get("local_time") or scope.get("local_time") or "02:00"),
        "weekdays": schedule_scope.get("weekdays") or scope.get("weekdays") or [1, 2, 3, 4, 5, 6, 7],
        "timezone": str(schedule_scope.get("timezone") or scope.get("timezone") or "Asia/Shanghai"),
        "catch_up": str(schedule_scope.get("catch_up") or scope.get("catch_up") or "skip"),
        "pause_until": schedule_scope.get("pause_until") or scope.get("pause_until"),
        "execution_budget_seconds": int(schedule_scope.get("execution_budget_seconds") or 0),
        "query_statuses": query_scope.get("statuses") or scope.get("query_statuses") or [],
        "token_policy": "auto_refresh",
        "credential_refresh": refresh_state,
        "data_destination": destination[0],
        "data_table": destination[1],
        "last_run_at": _format_datetime(job.last_run_at),
        "next_run_at": _format_datetime(job.next_run_at),
        "schedule_state": "queued" if renewal_queued else "blocked" if blocked_reason and job.is_enabled else schedule_state,
        "health_state": health_state,
        "blocked_reason": blocked_reason,
        "capability_state": source_health["state"],
        "capability_code": source_health.get("capability_code", ""),
        "source_priority": source_health.get("source_priority"),
        "selected_authorization_id": source_health.get("selected_authorization_id"),
        "latest_run_status": latest_run.status if latest_run else "",
        "latest_run_id": latest_run.run_id if latest_run else "",
        "latest_run_pk": latest_run.id if latest_run else None,
        "latest_started_at": _format_datetime(latest_run.started_at) if latest_run else None,
        "latest_finished_at": _format_datetime(latest_run.finished_at) if latest_run else None,
        "latest_fetched_count": latest_run.fetched_count if latest_run else 0,
        "latest_created_count": latest_run.created_count if latest_run else 0,
        "latest_updated_count": latest_run.updated_count if latest_run else 0,
        "latest_skipped_count": latest_run.skipped_count if latest_run else 0,
        "latest_failed_count": latest_run.failed_count if latest_run else 0,
        "latest_retry_count": latest_run.retry_count if latest_run else 0,
        "latest_error_code": latest_run.error_code if latest_run else "",
        "latest_error_message": str(
            (latest_run.masked_error_message if latest_run else "")
            or latest_log.get("masked_error_message")
            or ""
        )[:240],
        "checkpoint_version": (checkpoint or {}).get("version"),
        "checkpoint_watermark": _format_datetime((checkpoint or {}).get("watermark")),
        "updated_at": _format_datetime(job.updated_at),
        **subject,
    }
    return row


def _workspace_rows(user):
    all_configs = list(
        filter_integration_configs(
            user,
            PlatformIntegrationConfig.all_objects.filter(tenant=user.tenant).annotate(reference_count=Count("sync_jobs")),
            "integrations.config.view",
        )
    )
    configs = [config for config in all_configs if config.deleted_at is None]
    config_ids = [config.id for config in all_configs]
    config_raw = _raw_map("integrations_platformintegrationconfig", ["id", "api_type"], config_ids)
    jobs = list(
        filter_sync_jobs(
            user,
            SyncJob.objects.filter(tenant=user.tenant, integration_config_id__in=config_ids).select_related(
                "integration_config",
                "store_authorization",
                "store_authorization__store",
                "warehouse_authorization",
                "warehouse_authorization__warehouse",
            ),
            "integrations.view",
        )
    )
    job_ids = [job.id for job in jobs]
    checkpoints = _checkpoint_map(job_ids)
    stores, warehouse_auth, warehouse_master = _subject_maps(jobs, config_ids)
    runs = filter_sync_runs(
            user,
            SyncRun.objects.filter(tenant=user.tenant, sync_job_id__in=job_ids).select_related(
                "sync_job", "sync_job__integration_config", "history_segment__batch", "schedule_dispatch"
            ),
            "integrations.view",
        )
    # Fetch one latest log per visible job, not every historical log. The
    # successful-run timestamp follows the same model ordering as before.
    run_refs = list(SyncJob.objects.filter(pk__in=job_ids).annotate(
        latest_run_pk=Subquery(runs.filter(sync_job_id=OuterRef("pk")).values("pk")[:1]),
        last_success_at=Subquery(runs.filter(
            sync_job_id=OuterRef("pk"), status=SyncRun.Status.SUCCESS,
            masked_log__execution_mode="live_readonly",
        ).values("finished_at")[:1]),
    ).values("pk", "latest_run_pk", "last_success_at"))
    latest_by_job = {run.sync_job_id: run for run in runs.filter(
        pk__in=[ref["latest_run_pk"] for ref in run_refs if ref["latest_run_pk"] is not None]
    )}
    successful_by_job = {ref["pk"]: ref["last_success_at"] for ref in run_refs}
    context = {
        "queued_dispatches": set(SyncScheduleDispatch.objects.filter(
            tenant=user.tenant, sync_job_id__in=job_ids, status="queued"
        ).values_list("sync_job_id", flat=True)),
        "source_health": sync_source_health_for_jobs(jobs),
        "network_ready": get_runtime_setting("network", "readonly_sync_enabled", default=False),
        "platform_configs": {platform: get_runtime_platform_config(platform)
                             for platform in {job.integration_config.platform for job in jobs}},
        "refresh_states": {},
    }
    job_rows = {}
    for job in jobs:
        subject = _subject(job, stores, warehouse_auth, warehouse_master)
        job_rows[job.id] = _job_row(
            job,
            config_raw.get(job.integration_config_id, {}),
            subject,
            latest_by_job.get(job.id),
            checkpoints.get(job.id),
            context,
        )
        job_rows[job.id]["last_success_at"] = _format_datetime(successful_by_job.get(job.id))
        job_rows[job.id]["subject_key"] = f'{subject["subject_type"]}:{subject.get("store_id") or subject.get("warehouse_id") or job.id}'
    return configs, config_raw, jobs, job_rows, runs, warehouse_auth


def _config_rows(configs, config_raw):
    return [
        {
            "id": config.id,
            "account_alias": config.account_alias,
            "platform": config.platform,
            "api_type": _api_type(config, config_raw.get(config.id, {})),
            "environment": config.environment,
            "regions": config.regions,
            "status": config.status,
            "credential_status": config.credential_status,
            "credential_fingerprint": _masked_fingerprint(config.credential_fingerprint),
            "config_version": config.config_version,
            "callback_url": config.callback_url,
            "credential_reference_version": config.credential_reference_version,
            "reference_count": config.reference_count,
            "last_verified_at": _format_datetime(config.last_verified_at),
            "updated_at": _format_datetime(config.updated_at),
        }
        for config in configs
    ]


def _run_rows(runs, job_rows):
    from .sync_runtime import run_runtime_state
    rows = []
    for run in runs:
        job = job_rows.get(run.sync_job_id, {})
        dispatch = getattr(run, "schedule_dispatch", None)
        log = _json_value(run.masked_log)
        checkpoint = _json_value(log.get("checkpoint"))
        archive_files = log.get("archive_files") if isinstance(log.get("archive_files"), list) else []
        destination = RESOURCE_DESTINATIONS.get(run.sync_job.resource_type, ("业务事实", run.sync_job.resource_type))
        duration = None
        if run.started_at and run.finished_at:
            duration = max(0, int((run.finished_at - run.started_at).total_seconds()))
        rows.append(
            {
                "id": run.id,
                "run_id": run.run_id,
                "sync_job_id": run.sync_job_id,
                "job_enabled": run.sync_job.is_enabled,
                "environment": run.sync_job.integration_config.environment,
                "subject_key": job.get("subject_key", ""),
                "integration_config_id": job.get("integration_config_id"),
                "trigger_type": "retry" if log.get("retry_of") else log.get("trigger_type", ""),
                "scheduled_at": _format_datetime(dispatch.scheduled_at) if dispatch else log.get("scheduled_at"),
                "schedule_snapshot": dispatch.schedule_snapshot if dispatch else log.get("schedule_snapshot"),
                "enqueued_at": _format_datetime(run.enqueued_at) or (_format_datetime(dispatch.enqueued_at) if dispatch else log.get("enqueued_at")),
                "subject_name": job.get("subject_name", "历史未绑定"),
                "subject_code": job.get("subject_code", ""),
                "store_id": job.get("store_id"),
                "region": job.get("region", ""),
                "platform": run.sync_job.integration_config.platform,
                "api_type": job.get("api_type", "inventory" if run.sync_job.integration_config.platform == "jifeng_wms" else "marketplace"),
                "resource_type": run.sync_job.resource_type,
                "data_destination": destination[0],
                "data_table": destination[1],
                "execution_mode": log.get("execution_mode", ""),
                "external_api_called": _boolean_value(log.get("external_api_called")),
                "token_refreshed": _boolean_value(log.get("token_refreshed")),
                "status": run.status,
                "started_at": _format_datetime(run.started_at),
                "finished_at": _format_datetime(run.finished_at),
                "duration_seconds": duration,
                "fetched_count": run.fetched_count if "fetched" in log or run.fetched_count else None,
                "created_count": run.created_count if "fetched" in log or run.created_count else None,
                "updated_count": run.updated_count if "fetched" in log or run.updated_count else None,
                "skipped_count": run.skipped_count if "fetched" in log or run.skipped_count else None,
                "failed_count": run.failed_count if "fetched" in log or run.failed_count else None,
                "retry_count": run.retry_count,
                "execution_budget_seconds": _json_value(log.get("runtime_budget")).get("budget_seconds", 0),
                "continuation_count": _json_value(log.get("runtime_budget")).get("sequence", 0),
                "continuation_pending": bool(_json_value(log.get("runtime_budget")).get("pending")),
                "retry_of": str(log.get("retry_of") or "")[:80],
                "next_retry_at": _format_datetime(log.get("next_retry_at")),
                "max_retry_count": run.sync_job.max_retry_count,
                "checkpoint_version": checkpoint.get("version"),
                "checkpoint_advanced": _boolean_value(checkpoint.get("advanced")),
                "archive_file_count": len(archive_files),
                "error_code": str(run.error_code or "")[:80],
                "masked_error_message": str(run.masked_error_message or "")[:240],
                "masked_log": log,
                "runtime_state": run_runtime_state(run),
            }
        )
    return rows


def _unexecuted_plan_rows(user, job_rows, dispatches=None):
    result = []
    if dispatches is None:
        dispatches = SyncScheduleDispatch.objects.filter(tenant=user.tenant, sync_job_id__in=job_rows, sync_run__isnull=True)
    for dispatch in dispatches:
        job = job_rows[dispatch.sync_job_id]
        result.append({"id": f"plan-{dispatch.id}", "run_id": f"计划 #{dispatch.id}",
                       "sync_job_id": dispatch.sync_job_id, "subject_name": job["subject_name"],
                       "subject_key": job["subject_key"], "platform": job["platform"],
                       "resource_type": job["resource_type"], "status": dispatch.status,
                       "trigger_type": "scheduled", "execution_mode": "",
                       "scheduled_at": _format_datetime(dispatch.scheduled_at),
                       "enqueued_at": _format_datetime(dispatch.enqueued_at),
                       "started_at": None, "finished_at": _format_datetime(dispatch.finished_at),
                       "schedule_snapshot": dispatch.schedule_snapshot,
                       "masked_error_message": dispatch.reason,
                       "is_plan_only": True})
    return result


def _matches(row, params, mode):
    equality = {
        "platform": "platform",
        "status": "status",
        "environment": "environment",
        "api_type": "api_type",
        "resource_type": "resource_type",
        "schedule_type": "schedule_type",
        "sync_job_id": "sync_job_id" if mode == "sync-runs" else "id",
        "subject_key": "subject_key",
        "health_state": "health_state",
        "trigger_type": "trigger_type",
        "run_pk": "id",
    }
    for query_key, row_key in equality.items():
        expected = str(params.get(query_key, "")).strip().lower()
        if expected and str(row.get(row_key, "")).lower() not in expected.split(","):
            return False
    store_id = str(params.get("store_id", "")).strip()
    if store_id and str(row.get("store_id") or "") != store_id:
        return False
    job_state = str(params.get("job_state", "")).strip().lower()
    if mode == "sync-jobs" and job_state:
        states = {
            "enabled": bool(row.get("is_enabled")),
            "disabled": not row.get("is_enabled"),
            "running": row.get("schedule_state") == "running",
            "due": row.get("schedule_state") == "due",
            "failed": row.get("health_state") == "failed",
            "authorization": row.get("health_state") == "authorization",
        }
        if not states.get(job_state, False):
            return False
    subject = str(params.get("subject", "")).strip().casefold()
    if subject and subject not in " ".join(
        str(row.get(key, "")) for key in ("subject_code", "subject_name", "external_subject_id")
    ).casefold():
        return False
    run_id = str(params.get("run_id", "")).strip().casefold()
    if run_id and run_id not in str(row.get("run_id", "")).casefold():
        return False
    for query_key, compare in (("started_from", "from"), ("started_to", "to")):
        value = str(params.get(query_key, "")).strip()
        started = str(row.get("started_at") or row.get("scheduled_at") or "")[:10]
        if value and ((compare == "from" and started < value) or (compare == "to" and started > value)):
            return False
    return True


def _options(rows):
    def values(key):
        return sorted({str(row.get(key)) for row in rows if row.get(key) not in (None, "")})
    return {
        "platforms": values("platform"),
        "statuses": values("status"),
        "environments": values("environment"),
        "api_types": values("api_type"),
        "resource_types": values("resource_type"),
        "schedule_types": values("schedule_type"),
        "subjects": list({row.get("subject_key"): {"value": row.get("subject_key"), "label": row.get("subject_name")} for row in rows if row.get("subject_key")}.values()),
    }


def _query_values(params, key):
    return str(params.get(key, "")).strip().lower().split(",") if str(params.get(key, "")).strip() else []


def _matching_ids(values, prefix=""):
    # Preserve exact ID matching, and reject malformed IDs without an ORM
    # conversion exception (including plan IDs in a real-run filter).
    return [int(value[len(prefix):]) for value in values
            if value.startswith(prefix) and value[len(prefix):].isascii() and value[len(prefix):].isdigit()
            and str(int(value[len(prefix):])) == value[len(prefix):]]


def _legacy_scheduled_time():
    # Older runs can have a UTC scheduled time only in their masked metadata.
    return Cast(Replace(Substr(KeyTextTransform("scheduled_at", "masked_log"), 1, 19),
                        Value("T"), Value(" ")), DateTimeField())


def _query_date(params, key):
    value = str(params.get(key, "")).strip()
    if not value:
        return None
    try:
        date = parse_date(value) if len(value) == 10 and value[4] == value[7] == "-" else None
    except ValueError:
        date = None
    if date is None:
        raise ValueError(f"{key} must be a valid YYYY-MM-DD date.")
    return date


class _JSONKeyType(Func):
    """Keep JSON strings distinct from null/false in the two supported DBs."""
    function = "JSON_TYPE"
    output_field = CharField()

    def __init__(self, field, key):
        super().__init__(F(field), Value(f"$.{key}"))

    def as_mysql(self, compiler, connection, **extra_context):
        return self.as_sql(compiler, connection, template="JSON_TYPE(JSON_EXTRACT(%(expressions)s))", **extra_context)


def _filtered_runs(runs, job_rows, params):
    keys = {"platform", "environment", "api_type", "resource_type", "subject_key", "store_id", "subject"}
    metadata_params = {key: params[key] for key in keys if key in params}
    run_keys = keys | {"subject_code", "subject_name"}
    allowed_jobs = [pk for pk, row in job_rows.items() if _matches(
        {key: row.get(key) for key in run_keys}, metadata_params, "sync-runs",
    )]
    runs = runs.filter(sync_job_id__in=allowed_jobs)
    for key, field in (("status", "status"), ("sync_job_id", "sync_job_id"), ("run_pk", "pk")):
        values = _query_values(params, key)
        if values:
            runs = runs.filter(**{f"{field}__in": _matching_ids(values) if key != "status" else values})
    # These fields are not part of run rows. Do not silently broaden filters.
    if _query_values(params, "schedule_type") or _query_values(params, "health_state"):
        return runs.none()
    if run_id := str(params.get("run_id", "")).strip():
        runs = runs.filter(run_id__icontains=run_id)
    if triggers := _query_values(params, "trigger_type"):
        retry = Coalesce(Cast(KeyTextTransform("retry_of", "masked_log"), CharField()), Value(""))
        runs = runs.annotate(_retry_of=retry, _retry_type=_JSONKeyType("masked_log", "retry_of"))
        present = (Q(_retry_type__in=["text", "STRING"]) & ~Q(_retry_of="")) | ~Q(
            _retry_of__in=["", "null", "false", "0", "0.0", "-0.0", "[]", "{}"]
        )
        runs = runs.annotate(_trigger=Case(
            When(present, then=Value("retry")),
            default=Coalesce(KeyTextTransform("trigger_type", "masked_log"), Value("")), output_field=CharField(),
        )).filter(_trigger__in=triggers)
    runs = runs.annotate(_started_or_scheduled=Coalesce("started_at", "schedule_dispatch__scheduled_at", _legacy_scheduled_time()))
    if value := _query_date(params, "started_from"):
        runs = runs.filter(_started_or_scheduled__date__gte=value)
    if value := _query_date(params, "started_to"):
        # The old filter included undated queued runs for an upper bound only.
        runs = runs.filter(Q(_started_or_scheduled__date__lte=value) | Q(_started_or_scheduled__isnull=True))
    return runs


def _filtered_plans(plans, job_rows, params):
    metadata_params = {key: params[key] for key in ("platform", "resource_type", "subject_key", "subject") if key in params}
    allowed_jobs = [pk for pk, row in job_rows.items() if _matches(
        {key: row[key] for key in ("platform", "resource_type", "subject_key", "subject_name")},
        metadata_params, "sync-runs",
    )]
    plans = plans.filter(sync_job_id__in=allowed_jobs)
    if any(_query_values(params, key) for key in ("environment", "api_type", "schedule_type", "health_state")) or str(params.get("store_id", "")).strip():
        return plans.none()
    for key, field in (("status", "status"), ("sync_job_id", "sync_job_id"), ("run_pk", "pk")):
        values = _query_values(params, key)
        if values:
            plans = plans.filter(**{f"{field}__in": values if key == "status" else _matching_ids(values, "plan-" if key == "run_pk" else "")})
    if (triggers := _query_values(params, "trigger_type")) and "scheduled" not in triggers:
        return plans.none()
    if run_id := str(params.get("run_id", "")).strip():
        plans = plans.annotate(_run_label=Concat(Value("计划 #"), Cast("pk", CharField()))).filter(_run_label__icontains=run_id)
    if value := _query_date(params, "started_from"):
        plans = plans.filter(scheduled_at__date__gte=value)
    if value := _query_date(params, "started_to"):
        plans = plans.filter(scheduled_at__date__lte=value)
    return plans


def _run_page(user, runs, job_rows, params):
    plans = SyncScheduleDispatch.objects.filter(tenant=user.tenant, sync_job_id__in=job_rows, sync_run__isnull=True)
    filtered_runs = _filtered_runs(runs, job_rows, params)
    filtered_plans = _filtered_plans(plans, job_rows, params)
    # Union only small identity/time columns. Pagination happens in SQL, before
    # fetching masked logs, history relations or dispatch snapshots for the page.
    run_keys = filtered_runs.order_by().annotate(
        _row_kind=Value("run", output_field=CharField()), _row_key=Cast("pk", CharField()),
        _row_time=Coalesce("started_at", "enqueued_at", "schedule_dispatch__enqueued_at", "schedule_dispatch__scheduled_at", _legacy_scheduled_time()),
    ).values("_row_kind", "_row_key", "_row_time")
    plan_keys = filtered_plans.order_by().annotate(
        _row_kind=Value("plan", output_field=CharField()), _row_key=Concat(Value("plan-"), Cast("pk", CharField())),
        _row_time=Coalesce("enqueued_at", "scheduled_at"),
    ).values("_row_kind", "_row_key", "_row_time")
    identities = run_keys.union(plan_keys, all=True).order_by("-_row_time", "-_row_key")
    pagination = _pagination(params, identities.count())
    start = (pagination["page"] - 1) * pagination["page_size"]
    page_keys = list(identities[start:start + pagination["page_size"]])
    page_runs = runs.filter(pk__in=[int(key["_row_key"]) for key in page_keys if key["_row_kind"] == "run"])
    page_plans = plans.filter(pk__in=[int(key["_row_key"][5:]) for key in page_keys if key["_row_kind"] == "plan"])
    rows = _run_rows(page_runs, job_rows) + _unexecuted_plan_rows(user, job_rows, page_plans)
    row_map = {str(row["id"]): row for row in rows}
    page_rows = [row_map[key["_row_key"]] for key in page_keys]
    option_rows = []
    option_keys = ("platform", "environment", "api_type", "resource_type", "subject_key", "subject_name")
    for job_id, status in runs.order_by().values_list("sync_job_id", "status").distinct():
        option_rows.append({**{key: job_rows[job_id][key] for key in option_keys}, "status": status})
    for job_id, status in plans.order_by().values_list("sync_job_id", "status").distinct():
        option_rows.append({**{key: job_rows[job_id][key] for key in ("platform", "resource_type", "subject_key", "subject_name")}, "status": status})
    return page_rows, pagination, _options(option_rows)


def _pagination(params, total):
    page_size = min(max(int(params.get("page_size", 50)), 1), 100)
    page_count = max(1, (total + page_size - 1) // page_size)
    page = min(max(int(params.get("page", 1)), 1), page_count)
    return {"page": page, "page_size": page_size, "total": total, "page_count": page_count}


def _reference_options(user):
    countries = []
    seen_country_codes = set()
    for country in CountrySiteMaster.objects.filter(tenant=user.tenant, status="active").order_by(
        "country_code", "code"
    ):
        country_code = str(country.country_code or "").strip().upper()
        if not country_code or country_code in seen_country_codes:
            continue
        seen_country_codes.add(country_code)
        countries.append(
            {
                "value": country_code,
                "country_code": country_code,
                "code": country.code,
                "name": country.name,
                "label": f"{country_code}（{country.name}）",
                "currency": country.currency,
                "timezone": country.timezone,
            }
        )

    platforms = []
    seen_platforms = set()
    for platform in PlatformMaster.objects.filter(tenant=user.tenant, status="active").order_by("code"):
        integration_value = integration_platform_key(
            platform_type=platform.platform_type,
            code=platform.code,
            name=platform.name,
        )
        value = integration_value or platform.code
        if value in seen_platforms:
            continue
        seen_platforms.add(value)
        api_types = platform_api_type_options(integration_value)
        allowed_regions = None
        if integration_value == "lazada":
            allowed_regions = [item["value"] for item in get_platform_schema(integration_value)["regions"]]
        platforms.append(
            {
                "id": platform.id,
                "value": value,
                "code": platform.code,
                "name": platform.name,
                "label": f"{platform.name}（{platform.code}）",
                "enabled": bool(api_types),
                "api_types": api_types,
                "allowed_regions": allowed_regions,
            }
        )

    environment_labels = {"sandbox": "沙箱", "pilot": "试运行", "production": "生产"}
    environments = [
        {"value": value, "label": environment_labels.get(value, label)}
        for value, label in PlatformIntegrationConfig.Environment.choices
        if value != PlatformIntegrationConfig.Environment.MOCK
    ]
    return {"platforms": platforms, "countries": countries, "environments": environments}


def _warehouse_authorization_count(user, allowed_config_ids):
    return WarehouseAuthorization.objects.filter(
        tenant_id=user.tenant_id,
        integration_config_id__in=allowed_config_ids,
    ).count()


def integration_workspace(user, mode, params):
    if mode not in {"configs", "sync-jobs", "sync-runs"}:
        raise ValueError("Unknown integration workspace mode.")
    configs, config_raw, jobs, job_rows, runs, _ = _workspace_rows(user)
    if mode == "sync-runs":
        page_rows, pagination, options = _run_page(user, runs, job_rows, params)
    else:
        all_rows = _config_rows(configs, config_raw) if mode == "configs" else list(job_rows.values())
        if mode == "sync-jobs":
            all_rows.sort(key=lambda row: (
                str(row.get("platform") or "").casefold(),
                str(row.get("subject_name") or "").casefold(),
                str(row.get("subject_key") or ""),
                str(row.get("resource_type") or ""),
                int(row.get("id") or 0),
            ))
        else:
            all_rows.sort(key=lambda row: (str(row.get("updated_at") or ""), str(row.get("id", 0))), reverse=True)
        filtered = [row for row in all_rows if _matches(row, params, mode)]
        pagination = _pagination(params, len(filtered))
        start = (pagination["page"] - 1) * pagination["page_size"]
        page_rows = filtered[start:start + pagination["page_size"]]
        options = _options(all_rows)
    allowed_config_ids = [config.id for config in configs]
    scoped_incidents = SyncAlertIncident.objects.filter(
        tenant=user.tenant, sync_job_id__in=[job.id for job in jobs]
    )
    run_summary = runs.aggregate(
        run_count=Count("pk"),
        successful_run_count=Count("pk", filter=Q(status=SyncRun.Status.SUCCESS, masked_log__execution_mode="live_readonly")),
        failed_run_count=Count("pk", filter=Q(status=SyncRun.Status.FAILED)),
        running_run_count=Count("pk", filter=Q(status=SyncRun.Status.RUNNING)),
        queued_run_count=Count("pk", filter=Q(status=SyncRun.Status.QUEUED)),
    )
    summary = {
        "config_count": len(configs),
        "ready_credential_count": sum(
            1
            for config in configs
            if config.status != PlatformIntegrationConfig.Status.DISABLED
            and config.credential_status in {"configured", "referenced", "verified"}
            and bool(config.credential_id)
        ),
        "store_authorization_count": MarketplaceStoreAuthorization.objects.filter(
            tenant=user.tenant,
            integration_config_id__in=allowed_config_ids,
        ).count(),
        "warehouse_authorization_count": _warehouse_authorization_count(user, allowed_config_ids),
        "job_count": len(jobs),
        "enabled_job_count": sum(1 for job in jobs if job.is_enabled),
        **run_summary,
        "due_job_count": sum(1 for row in job_rows.values() if row["schedule_state"] == "due" and row["execution_mode"] == "simulation"),
        "live_confirmation_job_count": sum(1 for row in job_rows.values() if row["schedule_state"] == "due" and row["execution_mode"] == "live_readonly"),
        "retry_waiting_job_count": sum(1 for row in job_rows.values() if row["schedule_state"] == "retry_waiting"),
        "retry_exhausted_job_count": sum(1 for row in job_rows.values() if row["schedule_state"] == "retry_exhausted"),
        "stale_running_job_count": sum(1 for job in jobs if job.status == SyncJob.Status.RUNNING and (not job.lock_expires_at or job.lock_expires_at <= timezone.now())),
        "capability_blocked_job_count": sum(1 for row in job_rows.values() if row["health_state"] == "capability"),
        "open_sync_alert_count": NotificationMessage.objects.filter(
            tenant=user.tenant,
            message_type__in=[f"sync_job_failure:{job.id}" for job in jobs],
            status__in=(NotificationMessage.Status.UNREAD, NotificationMessage.Status.READ),
        ).count(),
        "open_sync_incident_count": scoped_incidents.filter(status=SyncAlertIncident.Status.OPEN).count(),
        "acknowledged_sync_incident_count": scoped_incidents.filter(
            status=SyncAlertIncident.Status.ACKNOWLEDGED
        ).count(),
    }
    eligible_subjects = {
        (row["subject_type"], row["subject_code"])
        for row in job_rows.values()
        if row["subject_type"] != "unbound"
        and row["config_status"] != PlatformIntegrationConfig.Status.DISABLED
        and row["credential_status"] in {"configured", "referenced", "verified"}
    }
    reference_options = _reference_options(user)
    return {
        "mode": mode,
        "source_status": "ready",
        "summary": summary,
        "scheduler": scheduler_health(),
        "credential_scheduler": credential_scheduler_health(),
        "scheduler_history": [],
        "options": options,
        "reference_options": reference_options,
        "regions": reference_options["countries"],
        "previews": {
            "due": {
                "due_count": summary["due_job_count"],
                "automatic_count": summary["due_job_count"],
                "confirmation_count": summary["live_confirmation_job_count"],
                "batch_limit": 20,
            },
            "reconcile": {
                "eligible_subject_count": len(eligible_subjects),
                "total_required": len([row for row in job_rows.values() if row["subject_type"] != "unbound"]),
                "existing_count": len([row for row in job_rows.values() if row["subject_type"] != "unbound"]),
                "missing_count": 0,
            },
            "creation_available": False,
        },
        "pagination": pagination,
        "results": page_rows,
    }
