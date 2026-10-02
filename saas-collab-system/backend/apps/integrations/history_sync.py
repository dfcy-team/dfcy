"""Durable one-shot Shopee history outbox, isolated from incremental watermarks."""
import hashlib
import json
from copy import copy
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.permissions.ui_p6_scopes import filter_sync_jobs
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from apps.common.module_gate import is_module_enabled
from .models import HistorySyncBatch, HistorySyncSegment, IntegrationAuditLog, SyncJob, SyncRun
from .security import sanitize_text
from .sync_services import _run_id, validate_manual_sync_job


def scoped_jobs(user, permission_codes):
    queryset = SyncJob.objects.filter(tenant_id=user.tenant_id).select_related(
        "integration_config", "store_authorization__store",
    )
    for code in permission_codes:
        queryset = filter_sync_jobs(user, queryset, code)
    return queryset


def history_execution_allowed(segment):
    user = segment.batch.created_by
    codes = ["integrations.history.manage", "integrations.run_live_readonly"]
    if not user or not user.is_active or user.user_type != "internal" or not all(
        check_user_permission(user, code) and get_permission_data_scopes(user, code) for code in codes
    ):
        return False
    return scoped_jobs(user, codes).filter(pk=segment.sync_job_id).exists()


def history_validation_job(job, segment):
    candidate = copy(job)
    candidate.sync_scope = {"query": {
        "mode": "range", "start_at": datetime.fromtimestamp(segment.scope["time_from"], UTC).isoformat(),
        "end_at": datetime.fromtimestamp(segment.scope["time_to"], UTC).isoformat(), "time_basis": "created",
    }}
    return candidate


def shop_name(job):
    store = job.store_authorization.store if job.store_authorization_id else None
    return str(store.name if store else f"订单任务 #{job.pk}")


def _audit(batch, user, jobs, action, detail=None):
    for job in jobs:
        IntegrationAuditLog.objects.create(
            tenant_id=batch.tenant_id, integration_config=job.integration_config,
            store_authorization=job.store_authorization, actor=user, result="success",
            action=f"history_sync_{action}", masked_detail={"batch_id": batch.pk, "job_id": job.pk,
                "start_date": str(batch.start_date), "end_date": str(batch.end_date), "platform_write": False, **(detail or {})},
        )


def create_history_batch(user, payload):
    if not is_module_enabled("api_integrations"):
        raise ValidationError("API 数据接入模块已停用，不能创建历史补采。")
    if not isinstance(payload, dict) or set(payload) - {"name", "job_ids", "start_date", "end_date", "idempotency_key"}:
        raise ValidationError("历史补采参数无效。")
    ids = payload.get("job_ids")
    if not isinstance(ids, list) or not 1 <= len(ids) <= 100 or any(type(pk) is not int or pk < 1 for pk in ids):
        raise ValidationError("请选择 1～100 个店铺订单任务。")
    ids = sorted(set(ids))
    key = str(payload.get("idempotency_key") or "").strip()
    name = str(payload.get("name") or "Shopee 历史补采").strip()
    if not key or len(key) > 100 or not name or len(name) > 120:
        raise ValidationError("批次名称或幂等键无效。")
    now = timezone.now()
    zone = ZoneInfo("Asia/Shanghai")
    try:
        start_day, end_day = date.fromisoformat(payload["start_date"]), date.fromisoformat(payload["end_date"])
    except (KeyError, ValueError, TypeError):
        raise ValidationError("起止日期须为 YYYY-MM-DD。")
    if start_day > end_day or end_day > now.astimezone(zone).date() or (end_day - start_day).days > 3660:
        raise ValidationError("开始日期不能晚于结束日期，结束日期不能晚于今天，总范围最多十年。")
    normalized = {"job_ids": ids, "start_date": str(start_day), "end_date": str(end_day), "name": name}
    fingerprint = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()
    with transaction.atomic():
        jobs = list(scoped_jobs(user, ["integrations.history.manage", "integrations.run_live_readonly"])
                    .filter(pk__in=ids).select_for_update().order_by("pk"))
        if len(jobs) != len(ids):
            raise PermissionDenied("所选任务超出权限范围或不存在。")
        existing = HistorySyncBatch.objects.filter(tenant_id=user.tenant_id, idempotency_key=key).first()
        if existing:
            if existing.request_hash != fingerprint:
                raise ValidationError("幂等键已经用于不同的历史补采请求。")
            return existing
        # Locking the common job serializes overlapping batch creation on MySQL.
        if HistorySyncSegment.objects.filter(sync_job_id__in=ids, batch__status__in=["running", "paused"]).exists():
            raise ValidationError("所选店铺已有未结束的历史补采批次，请先继续或处理该批次。")
        start = int(datetime.combine(start_day, time.min, zone).timestamp())
        end = min(int(datetime.combine(end_day, time(23, 59, 59), zone).timestamp()), int(now.timestamp()))
        if start >= end:
            raise ValidationError("采集时间范围尚无可采集的完整秒数。")
        batch = HistorySyncBatch.objects.create(tenant_id=user.tenant_id, created_by=user, name=name,
            idempotency_key=key, request_hash=fingerprint, start_date=start_day, end_date=end_day)
        segments = []
        for job in jobs:
            if job.integration_config.platform != "shopee" or job.resource_type not in {"sales_order", "refund_return", "settlement_bill"} or not job.store_authorization_id:
                raise ValidationError("仅支持已授权 Shopee 店铺的销售订单、退货退款和财务流水任务。")
            if not job.is_enabled or job.status == "disabled":
                raise ValidationError(f"{shop_name(job)}：请先启用订单同步任务。")
            cursor, sequence = start, 1
            while cursor <= end:
                stop = min(cursor + 15 * 86400 - 1, end)
                segment = HistorySyncSegment(batch=batch, sync_job=job, sequence=sequence,
                    scope={"time_from": cursor, "time_to": stop, "time_basis": "created", "page_size": 100})
                if sequence == 1:
                    validate_manual_sync_job(history_validation_job(job, segment), live_only=True)
                segments.append(segment)
                cursor, sequence = stop + 1, sequence + 1
        HistorySyncSegment.objects.bulk_create(segments)
        _audit(batch, user, jobs, "create")
        return batch


def update_batch_status(batch_id):
    batch = HistorySyncBatch.objects.select_for_update().get(pk=batch_id)
    if batch.status == "paused":
        return
    if not batch.segments.exclude(status__in=["success", "failed"]).exists():
        batch.status = "failed" if batch.segments.filter(status="failed").exists() else "completed"
        batch.finished_at = timezone.now()
        batch.save(update_fields=["status", "finished_at"])


def batch_action(batch, user, action):
    if action not in {"pause", "resume", "retry_failed"}:
        raise ValidationError("不支持的历史补采操作。")
    with transaction.atomic():
        audit_detail = {}
        job_ids = list(batch.segments.values_list("sync_job_id", flat=True).distinct())
        jobs = list(scoped_jobs(user, ["integrations.history.manage", "integrations.run_live_readonly"])
                    .filter(pk__in=job_ids).select_for_update().order_by("pk"))
        if len(jobs) != len(job_ids):
            raise PermissionDenied("只能操作全部店铺均在授权范围内的批次。")
        batch = HistorySyncBatch.objects.select_for_update().get(pk=batch.pk)
        if action == "pause":
            if batch.status == "running":
                batch.status = "paused"
        elif action == "resume":
            if batch.status != "paused":
                raise ValidationError("只有暂停的批次可以继续。")
            batch.status = "running"
        else:
            failed = list(batch.segments.select_for_update().filter(status="failed").order_by("sync_job_id", "sequence"))
            if not failed:
                raise ValidationError("没有失败分段需要重试。")
            job_map = {job.pk: job for job in jobs}
            retryable = []
            for segment in failed:
                job = job_map[segment.sync_job_id]
                if not job.is_enabled or job.status == "disabled":
                    continue
                try:
                    validate_manual_sync_job(history_validation_job(job, segment), live_only=True)
                except ValidationError:
                    # Leave unresolved authorization/configuration failures and
                    # jobs currently running untouched; other shops may recover.
                    continue
                retryable.append(segment)
            if not retryable:
                raise ValidationError("当前没有可恢复的失败分段；请先处理授权、配置或在途运行，再重试。")
            for segment in retryable:
                segment.status, segment.attempt, segment.submitted_at = "pending", segment.attempt + 1, None
                segment.save(update_fields=["status", "attempt", "submitted_at"])
            batch.status = "running"
            audit_detail = {"retried_segments": len(retryable), "skipped_segments": len(failed) - len(retryable)}
        batch.finished_at = None
        batch.save(update_fields=["status", "finished_at"])
        update_batch_status(batch.pk)
        _audit(batch, user, jobs, action, audit_detail)
    batch.refresh_from_db()
    return batch


def dispatch_history_segments(enqueue, now=None, limit=20):
    """Retry broker delivery with the same run/sequence, never repeat a completed segment."""
    now = now or timezone.now()
    if not is_module_enabled("api_integrations"):
        return 0
    submitted = 0
    job_ids = list(HistorySyncSegment.objects.filter(batch__status="running")
        .exclude(status__in=["success", "failed"]).values_list("sync_job_id", flat=True).distinct()[:limit])
    for job_id in job_ids:
        with transaction.atomic():
            job = SyncJob.objects.select_for_update().get(pk=job_id)
            segments = HistorySyncSegment.objects.filter(sync_job=job, batch__status="running").order_by("batch_id", "sequence")
            # Reconcile terminal runs after worker loss or a committed run followed by process death.
            for segment in segments.filter(status__in=["queued", "running"]).select_for_update():
                run = segment.runs.order_by("-id").first()
                if run and run.status in {"success", "failed", "cancelled"}:
                    segment.status = "success" if run.status == "success" else "failed"
                    segment.save(update_fields=["status"])
                    update_batch_status(segment.batch_id)
            segment = segments.exclude(status__in=["success", "failed"]).select_for_update().first()
            if not segment or not job.is_enabled or job.status in {"running", "disabled"} or (job.lock_expires_at and job.lock_expires_at > now):
                continue
            if not history_execution_allowed(segment):
                HistorySyncBatch.objects.filter(pk=segment.batch_id, status="running").update(status="paused")
                continue
            from .scheduler import paused_until
            pause = paused_until(job)
            if pause and pause > now:
                continue
            if job.runs.filter(status__in=["queued", "running"]).exclude(history_segment=segment).exclude(history_segment__batch__status="paused").exists():
                continue
            run = segment.runs.filter(idempotency_key=f"history:{segment.pk}:{segment.attempt}").first()
            if run and run.status != "queued":
                continue
            budget = (run.masked_log or {}).get("runtime_budget", {}) if run else {}
            ready = parse_datetime(str(budget.get("ready_at") or ""))
            if ready and ready > now:
                continue
            if segment.submitted_at and segment.submitted_at > now - timedelta(seconds=180):
                continue
            if run is None:
                run = SyncRun.objects.create(tenant_id=job.tenant_id, sync_job=job, history_segment=segment,
                    run_id=_run_id(), idempotency_key=f"history:{segment.pk}:{segment.attempt}", status="queued",
                    enqueued_at=now, masked_log={"execution_mode": "live_readonly", "trigger_type": "history",
                        "history_batch_id": segment.batch_id, "history_segment_id": segment.pk})
            segment.status, segment.submitted_at = "queued", now
            segment.save(update_fields=["status", "submitted_at"])
            key, sequence = run.idempotency_key, int(budget.get("sequence", 0))
        try:
            enqueue(job_id, key, sequence)
            submitted += 1
        except Exception:
            # Uncertain broker outcome: do not reset the durable key or generate a second run.
            pass
    return submitted


def batch_data(batch, visible_job_ids):
    from .automatic_refresh import credential_refresh_state
    segments = list(batch.segments.filter(sync_job_id__in=visible_job_ids)
        .select_related("sync_job__store_authorization__store").prefetch_related("runs"))
    shops = {}
    for segment in segments:
        item = shops.setdefault(segment.sync_job_id, {"job_id": segment.sync_job_id, "shop_name": shop_name(segment.sync_job),
            "resource_type": segment.sync_job.resource_type,
            "status": batch.status, "total_segments": 0, "success_segments": 0, "failed_segments": 0,
            "fetched_count": 0, "last_error": "", "waiting_for_refresh": 0})
        if "authorization" not in item:
            item["authorization"] = credential_refresh_state(segment.sync_job.store_authorization)
        item["total_segments"] += 1
        item["success_segments"] += segment.status == "success"
        item["failed_segments"] += segment.status == "failed"
        runs = list(segment.runs.all())
        item["fetched_count"] += sum(run.fetched_count for run in runs)
        if runs:
            latest = max(runs, key=lambda run: run.pk)
            item["waiting_for_refresh"] += (latest.status == "queued" and latest.error_code == "WAITING_CREDENTIAL_REFRESH"
                                            and item["authorization"]["state"] in {"due", "refreshing", "retry_wait"})
            if latest.status in {"failed", "cancelled"} and latest.masked_error_message:
                text = sanitize_text(latest.masked_error_message)
                item["last_error"] = (
                    "该分段执行时授权已过期；请查看下方当前授权状态。" if "主体授权已过期" in text else
                    "数据库死锁，重试已耗尽；待锁冲突处理后重试失败分段。" if "1213" in text or "死锁" in text else
                    "数据库锁等待超时；待锁冲突处理后重试失败分段。" if "1205" in text or "锁等待超时" in text else text
                )
    for item in shops.values():
        authorization = item["authorization"]
        item["recovery_hint"] = (
            "当前授权需人工处理，请先恢复授权并做只读检查。" if authorization["requires_manual_recovery"] or authorization["expired"] and authorization["state"] == "disabled" else
            "正在等待自动续期，采集断点已保留。" if item["waiting_for_refresh"] else
            "当前授权尚未到期；历史失败不会自动消失，可重试可恢复失败分段。" if item["failed_segments"] else
            "自动续期开关不代表采集成功，请结合最近实际续期和分段结果。"
        )
        if item["failed_segments"]:
            item["status"] = "failed"
        elif item["success_segments"] == item["total_segments"]:
            item["status"] = "completed"
    result = {"id": batch.pk, "name": batch.name, "status": batch.status, "start_date": str(batch.start_date),
        "end_date": str(batch.end_date), "created_at": batch.created_at.isoformat(), "shops": list(shops.values())}
    for field in ["total_segments", "success_segments", "failed_segments", "fetched_count"]:
        result[field] = sum(item[field] for item in shops.values())
    return result
