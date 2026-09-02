import json

from django.db import connection
from django.db.models import Count
from django.utils import timezone

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
    WarehouseAuthorization,
)
from .platform_schema_service import get_platform_schema, integration_platform_key, platform_api_type_options
from .capability_gate import sync_source_health


RESOURCE_DESTINATIONS = {
    "sales_order": ("销售订单", "sales_order / sales_order_item"),
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
            "subject_code": warehouse.code,
            "subject_name": warehouse.name,
            "region": warehouse.country_code,
            "authorization_status": warehouse_row.status,
            "external_subject_id": "",
        }
    return {
        "subject_type": "unbound",
        "subject_code": "",
        "subject_name": "未绑定",
        "region": "",
        "authorization_status": "",
        "external_subject_id": "",
    }


def _schedule_state(job, latest_run):
    now = timezone.now()
    if not job.is_enabled or job.status == SyncJob.Status.DISABLED:
        return "disabled"
    if job.status == SyncJob.Status.RUNNING or (job.lock_expires_at and job.lock_expires_at > now):
        return "running"
    if job.status == SyncJob.Status.FAILED and not job.next_run_at:
        return "retry_exhausted"
    if latest_run and latest_run.status == SyncRun.Status.FAILED and job.next_run_at and job.next_run_at > now:
        return "retry_waiting"
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


def _job_row(job, raw_config, subject, latest_run, checkpoint=None):
    scope = _json_value(job.sync_scope)
    query_scope = _json_value(scope.get("query"))
    schedule_scope = _json_value(scope.get("schedule"))
    latest_log = _json_value(latest_run.masked_log) if latest_run else {}
    destination = RESOURCE_DESTINATIONS.get(job.resource_type, (job.resource_type, job.resource_type))
    execution_mode = str(scope.get("execution_mode") or "simulation")
    schedule_state = _schedule_state(job, latest_run)
    config_ready = (
        job.integration_config.status != PlatformIntegrationConfig.Status.DISABLED
        and job.integration_config.credential_status in {"referenced", "verified"}
    )
    authorization_ready = subject["authorization_status"] in {"authorized", "active"}
    source_health = sync_source_health(job)
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
    row = {
        "id": job.id,
        "platform": job.integration_config.platform,
        "api_type": _api_type(job.integration_config, raw_config),
        "account_alias": job.integration_config.account_alias,
        "config_name": job.integration_config.account_alias,
        "config_status": job.integration_config.status,
        "credential_status": job.integration_config.credential_status,
        "resource_type": job.resource_type,
        "schedule_type": job.schedule_type,
        "execution_mode": execution_mode,
        "status": job.status,
        "is_enabled": job.is_enabled,
        "max_retry_count": job.max_retry_count,
        "backoff_base_seconds": job.backoff_base_seconds,
        "query_mode": str(query_scope.get("mode") or scope.get("query_mode") or "incremental"),
        "lookback_days": int(query_scope.get("lookback_days") or scope.get("lookback_days") or 30),
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
        "catch_up": str(schedule_scope.get("catch_up") or scope.get("catch_up") or "run_once"),
        "pause_until": schedule_scope.get("pause_until") or scope.get("pause_until"),
        "query_statuses": query_scope.get("statuses") or scope.get("query_statuses") or [],
        "token_policy": "manual_no_refresh" if job.integration_config.platform == "tiktok" else "auto_refresh",
        "data_destination": destination[0],
        "data_table": destination[1],
        "last_run_at": _format_datetime(job.last_run_at),
        "next_run_at": _format_datetime(job.next_run_at),
        "schedule_state": schedule_state,
        "health_state": health_state,
        "blocked_reason": blocked_reason,
        "capability_state": source_health["state"],
        "capability_code": source_health.get("capability_code", ""),
        "source_priority": source_health.get("source_priority"),
        "selected_authorization_id": source_health.get("selected_authorization_id"),
        "latest_run_status": latest_run.status if latest_run else "",
        "latest_run_id": latest_run.run_id if latest_run else "",
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
    runs = list(
        filter_sync_runs(
            user,
            SyncRun.objects.filter(tenant=user.tenant, sync_job_id__in=job_ids).select_related(
                "sync_job", "sync_job__integration_config"
            ),
            "integrations.view",
        )
    )
    latest_by_job = {}
    for run in runs:
        latest_by_job.setdefault(run.sync_job_id, run)
    job_rows = {}
    for job in jobs:
        subject = _subject(job, stores, warehouse_auth, warehouse_master)
        job_rows[job.id] = _job_row(
            job,
            config_raw.get(job.integration_config_id, {}),
            subject,
            latest_by_job.get(job.id),
            checkpoints.get(job.id),
        )
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
            "credential_reference_version": config.credential_reference_version,
            "reference_count": config.reference_count,
            "last_verified_at": _format_datetime(config.last_verified_at),
            "updated_at": _format_datetime(config.updated_at),
        }
        for config in configs
    ]


def _run_rows(runs, job_rows):
    rows = []
    for run in runs:
        job = job_rows.get(run.sync_job_id, {})
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
                "subject_name": job.get("subject_name", "历史未绑定"),
                "subject_code": job.get("subject_code", ""),
                "region": job.get("region", ""),
                "platform": run.sync_job.integration_config.platform,
                "api_type": job.get("api_type", "inventory" if run.sync_job.integration_config.platform == "jifeng_wms" else "marketplace"),
                "resource_type": run.sync_job.resource_type,
                "data_destination": destination[0],
                "data_table": destination[1],
                "execution_mode": log.get("execution_mode", "simulation"),
                "external_api_called": _boolean_value(log.get("external_api_called")),
                "token_refreshed": _boolean_value(log.get("token_refreshed")),
                "status": run.status,
                "started_at": _format_datetime(run.started_at),
                "finished_at": _format_datetime(run.finished_at),
                "duration_seconds": duration,
                "fetched_count": run.fetched_count,
                "created_count": run.created_count,
                "updated_count": run.updated_count,
                "skipped_count": run.skipped_count,
                "failed_count": run.failed_count,
                "retry_count": run.retry_count,
                "retry_of": str(log.get("retry_of") or "")[:80],
                "next_retry_at": _format_datetime(log.get("next_retry_at")),
                "max_retry_count": run.sync_job.max_retry_count,
                "checkpoint_version": checkpoint.get("version"),
                "checkpoint_advanced": _boolean_value(checkpoint.get("advanced")),
                "archive_file_count": len(archive_files),
                "error_code": str(run.error_code or "")[:80],
                "masked_error_message": str(run.masked_error_message or "")[:240],
                "masked_log": log,
            }
        )
    return rows


def _matches(row, params, mode):
    equality = {
        "platform": "platform",
        "status": "status",
        "environment": "environment",
        "api_type": "api_type",
        "resource_type": "resource_type",
        "schedule_type": "schedule_type",
    }
    for query_key, row_key in equality.items():
        expected = str(params.get(query_key, "")).strip().lower()
        if expected and str(row.get(row_key, "")).lower() != expected:
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
        started = str(row.get("started_at") or "")[:10]
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
    }


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
    all_rows = (
        _config_rows(configs, config_raw)
        if mode == "configs"
        else list(job_rows.values())
        if mode == "sync-jobs"
        else _run_rows(runs, job_rows)
    )
    all_rows.sort(key=lambda row: (str(row.get("started_at") or row.get("updated_at") or ""), row.get("id", 0)), reverse=True)
    filtered = [row for row in all_rows if _matches(row, params, mode)]
    page_size = min(max(int(params.get("page_size", 50)), 1), 100)
    page_count = max(1, (len(filtered) + page_size - 1) // page_size)
    page = min(max(int(params.get("page", 1)), 1), page_count)
    page_rows = filtered[(page - 1) * page_size : page * page_size]
    allowed_config_ids = [config.id for config in configs]
    scoped_incidents = SyncAlertIncident.objects.filter(
        tenant=user.tenant, sync_job_id__in=[job.id for job in jobs]
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
        "run_count": len(runs),
        "successful_run_count": sum(1 for run in runs if run.status == SyncRun.Status.SUCCESS),
        "failed_run_count": sum(1 for run in runs if run.status == SyncRun.Status.FAILED),
        "running_run_count": sum(1 for run in runs if run.status == SyncRun.Status.RUNNING),
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
        if row["subject_type"] != "unbound" and row["credential_status"] in {"referenced", "verified"}
    }
    reference_options = _reference_options(user)
    return {
        "mode": mode,
        "source_status": "ready",
        "summary": summary,
        "scheduler": {"configured": True, "heartbeat_state": "scheduled", "execution_policy": "readonly_automatic"},
        "scheduler_history": [],
        "options": _options(all_rows),
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
        "pagination": {"page": page, "page_size": page_size, "total": len(filtered), "page_count": page_count},
        "results": page_rows,
    }
