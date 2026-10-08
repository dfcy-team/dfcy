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
from .models import HistorySyncBatch, HistorySyncSegment, IntegrationAuditLog, SyncCursor, SyncJob, SyncRun
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


def _history_range(payload, now):
    zone = ZoneInfo("Asia/Shanghai")
    try:
        start_day, end_day = date.fromisoformat(payload["start_date"]), date.fromisoformat(payload["end_date"])
        if str(start_day) != payload["start_date"] or str(end_day) != payload["end_date"]:
            raise ValueError
    except (KeyError, ValueError, TypeError):
        raise ValidationError("起止日期须为 YYYY-MM-DD。")
    if start_day > end_day or end_day > now.astimezone(zone).date() or (end_day - start_day).days > 3660:
        raise ValidationError("开始日期不能晚于结束日期，结束日期不能晚于今天，总范围最多十年。")
    start = int(datetime.combine(start_day, time.min, zone).timestamp())
    end = min(int(datetime.combine(end_day, time(23, 59, 59), zone).timestamp()), int(now.timestamp()))
    if start >= end:
        raise ValidationError("采集时间范围尚无可采集的完整秒数。")
    return start_day, end_day, start, end


def _range_snapshot(batch, segments, now):
    """Only untouched pending windows may be replaced; provider cursors are immutable."""
    jobs = {segment.sync_job_id: segment.sync_job for segment in segments}
    cursor_keys = set(SyncCursor.objects.filter(sync_job_id__in=jobs, cursor_key__startswith="history:")
                      .values_list("sync_job_id", "cursor_key"))
    protected, signature, invalid = [], [], False
    for segment in segments:
        runs = list(segment.runs.all())
        has_cursor = (segment.sync_job_id, f"history:{segment.pk}") in cursor_keys
        scope = segment.scope if isinstance(segment.scope, dict) else {}
        start, end = scope.get("time_from"), scope.get("time_to")
        invalid |= type(start) is not int or type(end) is not int or (type(start) is int and type(end) is int and start > end)
        if segment.status != "pending" or segment.attempt != 1 or segment.submitted_at or runs or has_cursor:
            protected.append(segment)
        signature.append([segment.pk, segment.sync_job_id, start, end, segment.status, segment.attempt,
                          str(segment.submitted_at or ""), has_cursor, sorted([run.pk, run.status] for run in runs)])
    try:
        zone = ZoneInfo("Asia/Shanghai")
        protected_start = str(datetime.fromtimestamp(min(s.scope["time_from"] for s in protected), zone).date()) if protected and not invalid else None
        protected_end = str(datetime.fromtimestamp(max(s.scope["time_to"] for s in protected), zone).date()) if protected and not invalid else None
    except (ValueError, OSError, OverflowError):
        invalid, protected_start, protected_end = True, None, None
    active = any(job.status == "running" or job.lock_expires_at and job.lock_expires_at > now for job in jobs.values())
    active |= any(run.status == "running" for segment in segments for run in segment.runs.all())
    reason = (
        "批次缺少可调整的分段，请先核对运行记录。" if not segments else
        "运行中的批次请先暂停，再调整补采范围。" if batch.status == "running" else
        "只有暂停或已结束的批次可以调整补采范围。" if batch.status not in {"paused", "completed", "failed"} else
        "仍有在途运行或执行锁，请等待当前执行结束后刷新。" if active else
        "分段时间范围异常，请先核对运行记录。" if invalid else ""
    )
    revision = hashlib.sha256(json.dumps({"dates": [str(batch.start_date), str(batch.end_date)], "status": batch.status,
        "segments": sorted(signature), "jobs": sorted([job.pk, job.status, str(job.lock_expires_at or "")] for job in jobs.values())},
        sort_keys=True).encode()).hexdigest()
    return {"allowed": not reason, "blocked_reason": reason, "protected_start_date": protected_start,
            "protected_end_date": protected_end, "revision": revision}, protected


def adjust_history_range(batch, user, payload):
    """Re-plan unused windows under the same job locks as dispatch; never enqueue."""
    codes = ["integrations.history.manage", "integrations.run_live_readonly"]
    if not user.is_active or user.user_type != "internal" or not all(
        check_user_permission(user, code) and get_permission_data_scopes(user, code) for code in codes
    ):
        raise PermissionDenied("调整补采范围须具备历史补采管理和真实只读同步权限。")
    if not is_module_enabled("api_integrations"):
        raise ValidationError("API 数据接入模块已停用，不能调整历史补采。")
    if not isinstance(payload, dict) or set(payload) != {"start_date", "end_date", "expected_revision"}:
        raise ValidationError("调整补采范围须提交起止日期和当前版本标识。")
    if not isinstance(payload["expected_revision"], str) or len(payload["expected_revision"]) != 64:
        raise ValidationError("批次版本标识无效，请刷新后重试。")
    now = timezone.now()
    start_day, end_day, start, end = _history_range(payload, now)
    with transaction.atomic():
        job_ids = list(batch.segments.values_list("sync_job_id", flat=True).distinct())
        jobs = list(scoped_jobs(user, ["integrations.history.manage", "integrations.run_live_readonly"])
                    .filter(pk__in=job_ids).select_for_update().order_by("pk"))
        if batch.tenant_id != user.tenant_id or not job_ids or len(jobs) != len(job_ids):
            raise PermissionDenied("只能操作全部店铺均在授权范围内的批次。")
        batch = HistorySyncBatch.objects.select_for_update().get(pk=batch.pk, tenant_id=user.tenant_id)
        segments = list(batch.segments.select_for_update().select_related("sync_job").prefetch_related("runs").order_by("pk"))
        snapshot, protected = _range_snapshot(batch, segments, now)
        if not snapshot["allowed"]:
            raise ValidationError(snapshot["blocked_reason"])
        if snapshot["revision"] != payload["expected_revision"]:
            raise ValidationError("补采范围或分段状态已变化，请刷新批次后重新调整。")
        # Preserve the original creation hash: retrying the original creation
        # request must still return this batch, not create or rewind a second one.
        if (start_day, end_day) == (batch.start_date, batch.end_date):
            return batch
        if HistorySyncSegment.objects.filter(sync_job_id__in=job_ids, batch__status__in=["running", "paused"]).exclude(batch=batch).exists():
            raise ValidationError("所选店铺已有其他未结束的历史补采批次，请先处理该批次。")
        if any(segment.scope["time_from"] < start or segment.scope["time_to"] > end for segment in protected):
            raise ValidationError(f"新范围须包含已提交或带断点的分段：{snapshot['protected_start_date']} 至 {snapshot['protected_end_date']}；不能裁掉既有采集进度。")
        preserved_ids = {segment.pk for segment in protected}
        unused_ids = [segment.pk for segment in segments if segment.pk not in preserved_ids]
        planned = []
        for job in jobs:
            sequence = max(s.sequence for s in segments if s.sync_job_id == job.pk) + 1
            covered = sorted((s.scope["time_from"], s.scope["time_to"]) for s in protected if s.sync_job_id == job.pk)
            cursor = start
            gaps = []
            for left, right in covered:
                if cursor < left:
                    gaps.append((cursor, left - 1))
                cursor = max(cursor, right + 1)
            if cursor <= end:
                gaps.append((cursor, end))
            for left, right in gaps:
                cursor = left
                while cursor <= right:
                    stop = min(cursor + 15 * 86400 - 1, right)
                    planned.append(HistorySyncSegment(batch=batch, sync_job=job, sequence=sequence,
                        scope={"time_from": cursor, "time_to": stop, "time_basis": "created", "page_size": 100}))
                    cursor, sequence = stop + 1, sequence + 1
        # PROTECT on SyncRun.history_segment is a final safety net; runs and
        # history/default cursors/checkpoints and ingested rows are never deleted.
        batch.segments.filter(pk__in=unused_ids).delete()
        HistorySyncSegment.objects.bulk_create(planned)
        old_dates = {"start_date": str(batch.start_date), "end_date": str(batch.end_date)}
        batch.start_date, batch.end_date, batch.status, batch.finished_at = start_day, end_day, "paused", None
        batch.save(update_fields=["start_date", "end_date", "status", "finished_at"])
        _audit(batch, user, jobs, "adjust_range", {"old_range": old_dates,
            "new_range": {"start_date": str(start_day), "end_date": str(end_day)},
            "preserved_segments": len(protected), "replaced_pending_segments": len(unused_ids),
            "new_pending_segments": len(planned), "previous_revision": snapshot["revision"], "auto_resumed": False})
        return batch


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
    start_day, end_day, start, end = _history_range(payload, now)
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


def batch_action(batch, user, action, payload=None):
    if action == "adjust_range":
        return adjust_history_range(batch, user, payload)
    if payload:
        raise ValidationError("此操作不接受额外参数。")
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


def dispatch_history_segments(enqueue, now=None, limit=20, delivery_snapshot=None, admission=None):
    """Retry broker delivery with the same run/sequence, never repeat a completed segment."""
    now = now or timezone.now()
    if not is_module_enabled("api_integrations"):
        return 0
    submitted = 0
    from .sync_delivery import observe_delivery, read_delivery_snapshot
    delivery_snapshot = delivery_snapshot if delivery_snapshot is not None else read_delivery_snapshot()
    from .sync_dispatch_policy import fair_job_ids, mark_served
    pending = HistorySyncSegment.objects.filter(batch__status="running").exclude(status__in=["success", "failed"])
    job_ids = fair_job_ids(SyncJob.objects.filter(pk__in=pending.values("sync_job_id")), "history", limit)
    for job_id in job_ids:
        if submitted >= limit:
            break
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
            active_runs = list(job.runs.filter(status__in=["queued", "running"])
                .exclude(history_segment__batch__status="paused").order_by("pk")[:2])
            if active_runs:
                # A yielded later segment owns this job's continuation. Picking
                # an earlier retry first would then block both on the same run.
                # Ambiguous or non-history executions must still fail closed.
                if len(active_runs) != 1 or active_runs[0].status != "queued":
                    continue
                active_run = active_runs[0]
                segment = segments.exclude(status__in=["success", "failed"]).filter(
                    pk=active_run.history_segment_id).select_for_update().first()
                if not segment or active_run.idempotency_key != f"history:{segment.pk}:{segment.attempt}":
                    continue
            else:
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
            new_run = run is None
            if new_run and admission is not None and not admission.claim(job, "history"):
                continue
            if run is None:
                run = SyncRun.objects.create(tenant_id=job.tenant_id, sync_job=job, history_segment=segment,
                    run_id=_run_id(), idempotency_key=f"history:{segment.pk}:{segment.attempt}", status="queued",
                    enqueued_at=now, masked_log={"execution_mode": "live_readonly", "trigger_type": "history",
                        "history_batch_id": segment.batch_id, "history_segment_id": segment.pk})
            sequence = int(budget.get("sequence", 0))
            state = observe_delivery(run, delivery_snapshot, sequence, now)
            if state == "present" or (segment.submitted_at and state == "unknown"):
                continue
            if not new_run and admission is not None and not admission.claim(job, "history"):
                continue
            segment.status, segment.submitted_at = "queued", now
            segment.save(update_fields=["status", "submitted_at"])
            key = run.idempotency_key
        try:
            mark_served(job, "history", now)
            enqueue(job_id, key, sequence)
            submitted += 1
        except Exception:
            # Uncertain broker outcome: do not reset the durable key or generate a second run.
            pass
    return submitted


def batch_data(batch, visible_job_ids, manageable_job_ids=None):
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
    adjustment, _ = _range_snapshot(batch, segments, timezone.now())
    if batch.segments.exclude(sync_job_id__in=manageable_job_ids or []).exists() or batch.segments.exclude(sync_job_id__in=visible_job_ids).exists():
        adjustment.update(allowed=False, blocked_reason="需要全部店铺的数据范围及历史补采管理、真实只读同步权限。")
    elif not is_module_enabled("api_integrations"):
        adjustment.update(allowed=False, blocked_reason="API 数据接入模块已停用。")
    elif HistorySyncSegment.objects.filter(sync_job_id__in=[s.sync_job_id for s in segments],
            batch__status__in=["running", "paused"]).exclude(batch=batch).exists():
        adjustment.update(allowed=False, blocked_reason="所选店铺已有其他未结束的历史补采批次，请先处理该批次。")
    result["range_adjustment"] = adjustment
    for field in ["total_segments", "success_segments", "failed_segments", "fetched_count"]:
        result[field] = sum(item[field] for item in shops.values())
    return result
