"""Scoped, auditable recovery of existing history tasks and their segments."""
import hashlib
import json

from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.common.module_gate import is_module_enabled
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from .history_schedule import history_task_gate, validate_execution_policy
from .models import HistorySyncBatch, HistorySyncSegment, HistorySyncTaskControl, SyncJob, SyncRun
from .security import sanitize_text


def task_revision(batch, job):
    control = HistorySyncTaskControl.objects.filter(batch=batch, sync_job=job).first()
    segments = list(batch.segments.filter(sync_job=job).order_by("pk").values("pk", "status", "attempt", "scope")
                    .annotate(last_run=Max("runs__pk")))
    payload = {"batch": [batch.pk, batch.status, str(batch.start_date), str(batch.end_date)],
               "job": [job.pk, job.status, job.is_enabled, str(job.lock_expires_at)], "segments": segments,
               "control": [control.is_paused, control.execution_policy, str(control.updated_at)] if control else None}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def failure_kind(run):
    if not run:
        return "missing_run", "运行记录缺失，先核对原任务与分段关联。"
    code, message = run.error_code or "", run.masked_error_message or ""
    lower = message.lower()
    if code == "RUN_TIMEOUT":
        return "execution_timeout", "执行超时。按已保存的页内断点续采；重复超时请核对单次请求耗时和工作进程。"
    if any(word in lower for word in ("timed out", "timeout", "超时")) and "1205" not in message:
        return "request_timeout", "平台请求超时。保留已提交断点，仅重试失败部分；连续失败时检查平台响应与连接配置。"
    if any(word in lower for word in ("429", "rate limit", "限流")):
        return "rate_limit", "平台限流。等待平台允许的重试时间，降低并发后重试。"
    if any(word in message for word in ("1213", "1205", "死锁", "锁等待")):
        return "database_lock", "数据库锁冲突。核对其他在途运行，冲突解除后从已提交断点重试。"
    if any(word in lower for word in ("授权", "token", "credential", "oauth")):
        return "authorization", "先到对应店铺维护授权并检查连接；续期成功不会自动清除历史失败。"
    if any(word in message for word in ("配置", "能力", "合同", "白名单")):
        return "configuration", "先检查连接配置、能力矩阵和生产准入，再重试原分段。"
    if any(word in message for word in ("日期", "范围", "2025", "六个月")):
        return "date_range", "检查原采集日期及平台可查询范围；不允许清空游标后绕过日期限制。"
    return "data_or_runtime", "查看对应运行详情，修复数据合同或运行异常后再重试；已成功数据保留。"


def retry_block_reason(job, segment):
    from .history_sync import history_validation_job
    from .sync_services import validate_manual_sync_job
    if segment.status != "failed":
        return "仅可重试失败分段。"
    if not job.is_enabled or job.status == "disabled":
        return "请先启用当前同步任务，再重试补采。"
    if not is_module_enabled("api_integrations"):
        return "API 数据接入模块已停用。"
    try:
        validate_manual_sync_job(history_validation_job(job, segment), live_only=True)
    except ValidationError as exc:
        return sanitize_text(str(exc.detail))[:600]
    return ""


def task_diagnostics(batch, job, *, page=1, can_manage=False):
    """GET is configuration/DB only: no provider call, token refresh or repair."""
    failed = batch.segments.filter(sync_job=job, status="failed").prefetch_related("runs").order_by("sequence")
    count = failed.count()
    rows = []
    for segment in failed[(page - 1) * 20:page * 20]:
        run = max(segment.runs.all(), key=lambda value: value.pk, default=None)
        kind, guidance = failure_kind(run)
        blocked = retry_block_reason(job, segment) if can_manage else "需要补采管理和真实只读执行权限。"
        rows.append({"id": segment.pk, "sequence": segment.sequence, "status": segment.status,
                     "attempt": segment.attempt, "run_id": run.pk if run else None,
                     "error_code": run.error_code if run else "", "category": kind, "guidance": guidance,
                     "error_message": sanitize_text(run.masked_error_message)[:600] if run else "",
                     "time_from": segment.scope.get("time_from"), "time_to": segment.scope.get("time_to"),
                     "can_retry": not blocked, "blocked_reason": blocked,
                     "detail_progress": ((run.masked_log or {}).get("runtime_budget") or {}).get("detail_progress", {}) if run else {}})
    return {"batch_id": batch.pk, "sync_job_id": job.pk, "revision": task_revision(batch, job),
            "page": page, "page_size": 20, "total": count, "segments": rows,
            "execution": history_task_gate(batch, job.pk),
            "store_id": job.store_authorization.store_id if job.store_authorization_id else None,
            "integration_config_id": job.integration_config_id}


def _scoped_job(batch, user, job_id, *, lock=False):
    from .history_sync import scoped_jobs
    codes = ["integrations.history.manage", "integrations.run_live_readonly"]
    if not user.is_active or user.user_type != "internal" or not all(check_user_permission(user, code) and get_permission_data_scopes(user, code) for code in codes):
        raise PermissionDenied("需要补采管理和真实只读执行权限。")
    if type(job_id) is not int or job_id <= 0:
        raise ValidationError("同步任务 ID 无效。")
    query = scoped_jobs(user, codes)
    if lock:
        query = query.select_for_update(of=("self",))
    job = query.filter(pk=job_id).first()
    if not job or batch.tenant_id != user.tenant_id or not batch.segments.filter(sync_job_id=job_id).exists():
        raise PermissionDenied("任务不存在于该批次或超出当前店铺权限范围。")
    return job


def task_action(batch, user, payload):
    from .history_sync import _audit, update_batch_status
    from .sync_delivery import read_delivery_snapshot
    action = payload.get("action")
    if not isinstance(action, str) or action not in {"pause", "resume", "retry_failed", "set_schedule", "reconcile"}:
        raise ValidationError("不支持的任务补采操作。")
    allowed = {"action", "sync_job_id", "expected_revision"}
    allowed |= {"execution_policy"} if action == "set_schedule" else {"segment_ids"} if action == "retry_failed" else set()
    if set(payload) - allowed or not {"sync_job_id", "expected_revision"}.issubset(payload):
        raise ValidationError("任务补采操作须包含当前任务和诊断版本。")
    if not isinstance(payload["expected_revision"], str) or len(payload["expected_revision"]) != 64:
        raise ValidationError("补采诊断版本无效，请刷新后重新操作。")
    if not is_module_enabled("api_integrations"):
        raise ValidationError("API 数据接入模块已停用。")
    # Permission is checked before accessing broker evidence or acquiring locks.
    _scoped_job(batch, user, payload.get("sync_job_id"))
    snapshot = read_delivery_snapshot() if action == "reconcile" else None
    if snapshot is not None and not snapshot.complete:
        raise ValidationError("执行队列证据不完整，暂不能修复运行状态；请稍后重新核对。")
    with transaction.atomic():
        job = _scoped_job(batch, user, payload["sync_job_id"], lock=True)
        batch = HistorySyncBatch.objects.select_for_update().get(pk=batch.pk, tenant_id=user.tenant_id)
        if task_revision(batch, job) != payload.get("expected_revision"):
            raise ValidationError("补采状态已变化，请刷新诊断后重新操作。")
        control, _ = HistorySyncTaskControl.objects.get_or_create(batch=batch, sync_job=job)
        detail = {"task_id": job.pk, "task_scoped": True}
        if action == "pause":
            control.is_paused, control.pause_reason = True, "manual"
        elif action == "resume":
            # Translating a legacy global pause must not wake other shops.
            if batch.status == "paused":
                other_ids = list(batch.segments.exclude(sync_job=job).values_list("sync_job_id", flat=True).distinct())
                for other_id in other_ids:
                    other, _ = HistorySyncTaskControl.objects.get_or_create(batch=batch, sync_job_id=other_id)
                    other.is_paused, other.pause_reason = True, other.pause_reason or "legacy_batch_pause"
                    other.save(update_fields=["is_paused", "pause_reason", "updated_at"])
                batch.status, batch.finished_at = "running", None
            elif batch.status != "running":
                raise ValidationError("已结束批次请使用重试失败分段，不能直接继续。")
            control.is_paused, control.pause_reason = False, ""
            control.authorized_by, control.authority_assigned = user, True
        elif action == "set_schedule":
            control.execution_policy = validate_execution_policy(payload.get("execution_policy"))
            detail["execution_policy"] = control.execution_policy
        elif action == "retry_failed":
            selected = payload.get("segment_ids")
            failed = batch.segments.select_for_update().filter(sync_job=job, status="failed").order_by("pk")
            if selected is not None:
                if not isinstance(selected, list) or not 1 <= len(selected) <= 100 or any(type(pk) is not int or pk < 1 for pk in selected):
                    raise ValidationError("请选择 1～100 个失败分段。")
                failed = failed.filter(pk__in=set(selected))
                if failed.count() != len(set(selected)):
                    raise ValidationError("所选分段已变化或不属于当前任务的失败分段。")
            retryable, skipped = [], 0
            for segment in failed:
                if retry_block_reason(job, segment):
                    skipped += 1
                else:
                    retryable.append(segment)
            if not retryable:
                raise ValidationError("当前没有可恢复分段；请按诊断处理授权、配置或在途运行后重试。")
            for segment in retryable:
                segment.status, segment.attempt, segment.submitted_at = "pending", segment.attempt + 1, None
                segment.save(update_fields=["status", "attempt", "submitted_at"])
            control.authorized_by, control.authority_assigned = user, True
            if batch.status != "paused":
                batch.status, batch.finished_at = "running", None
            detail.update(retried_segments=len(retryable), skipped_segments=skipped,
                          kept_paused=batch.status == "paused" or control.is_paused)
        else:
            detail.update(_reconcile(batch, job, snapshot))
        control.save()
        batch.save(update_fields=["status", "finished_at"])
        if action in {"set_schedule", "resume"}:
            # A continuation's old next-window timestamp must not override a
            # deliberate policy change. Keep the run, sequence and cursor intact.
            gate = history_task_gate(batch, job.pk, control=control)
            for waiting_run in job.runs.select_for_update().filter(history_segment__batch=batch, status="queued"):
                budget = dict((waiting_run.masked_log or {}).get("runtime_budget") or {})
                if budget.get("wait_reason") not in {"waiting_window", "paused"}:
                    continue
                budget["ready_at"] = gate.get("next_eligible_at") or timezone.now().isoformat()
                if gate["allowed"]:
                    budget.pop("wait_reason", None)
                else:
                    budget["wait_reason"] = gate["state"]
                waiting_run.masked_log = {**(waiting_run.masked_log or {}), "runtime_budget": budget}
                waiting_run.save(update_fields=["masked_log"])
        update_batch_status(batch.pk)
        _audit(batch, user, [job], "task_" + action, detail)
        batch.refresh_from_db()
        return batch, detail


def _reconcile(batch, job, snapshot):
    """Never remove messages or manufacture success: require durable evidence."""
    from .sync_delivery import observe_delivery
    changed, now = 0, timezone.now()
    for segment in batch.segments.select_for_update().filter(sync_job=job, status__in=["queued", "running"]).order_by("pk"):
        run = segment.runs.select_for_update().filter(idempotency_key=f"history:{segment.pk}:{segment.attempt}").first()
        if not run:
            continue
        if run.status in {"success", "failed", "cancelled"}:
            segment.status = "success" if run.status == "success" else "failed"
            segment.save(update_fields=["status"])
            changed += 1
        elif (run.status == "running" and job.lock_token == run.run_id and job.lock_expires_at and job.lock_expires_at <= now):
            budget = (run.masked_log or {}).get("runtime_budget") or {}
            if observe_delivery(run, snapshot, int(budget.get("sequence", 0)), now) != "absent":
                continue
            run.status, run.finished_at, run.error_code = "failed", now, "RUN_INTERRUPTED"
            run.masked_error_message = "执行租约已过期且队列核对无在途执行；断点保留，请检查后重试该分段。"
            run.save(update_fields=["status", "finished_at", "error_code", "masked_error_message"])
            segment.status = "failed"
            segment.save(update_fields=["status"])
            job.status, job.lock_token, job.lock_expires_at = SyncJob.Status.FAILED, "", None
            job.save(update_fields=["status", "lock_token", "lock_expires_at", "updated_at"])
            from .sync_alerts import upsert_sync_failure_alert
            upsert_sync_failure_alert(job, error_code=run.error_code, message=run.masked_error_message)
            changed += 1
    return {"reconciled_segments": changed, "auto_retried": False, "cursor_reset": False}
