from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .models import SyncJob, SyncRun, SyncScheduleDispatch
from .scheduler import dispatch_due_jobs, paused_until, resume_due_sync_runs
from .sync_services import fail_queued_sync_run, run_sync_job, validate_manual_sync_job
from .sync_alerts import upsert_sync_failure_alert


@shared_task
def refresh_due_integration_credentials():
    from .automatic_refresh import refresh_due_authorizations
    return refresh_due_authorizations()


@shared_task(bind=True, soft_time_limit=840, time_limit=900)
def run_readonly_sync_job(self, sync_job_id, idempotency_key=None, resume_sequence=0):
    sync_job = SyncJob.objects.select_related("tenant", "integration_config").get(pk=sync_job_id)
    dispatch = None
    existing = SyncRun.objects.filter(sync_job=sync_job, idempotency_key=idempotency_key).first() if idempotency_key else None
    if existing:
        budget = (existing.masked_log or {}).get("runtime_budget") or {}
        if existing.status != SyncRun.Status.QUEUED or int(budget.get("sequence", 0)) != resume_sequence:
            return {"status": "not_executed", "created": False}
    if str(idempotency_key or "").startswith("scheduled:"):
        with transaction.atomic():
            sync_job = SyncJob.objects.select_for_update().select_related("tenant", "integration_config").get(pk=sync_job_id)
            dispatch = SyncScheduleDispatch.objects.filter(pk=str(idempotency_key).split(":")[-1], sync_job=sync_job).first()
            if not dispatch or dispatch.status != "queued":
                return {"status": "not_executed", "created": False}
            if dispatch.sync_run_id:
                linked = dispatch.sync_run
                budget = (linked.masked_log or {}).get("runtime_budget") or {}
                if linked.status != SyncRun.Status.QUEUED or int(budget.get("sequence", 0)) != resume_sequence:
                    return {"status": "not_executed", "created": False}
            pause = paused_until(sync_job)
            if not sync_job.is_enabled or (pause and pause > timezone.now()):
                if dispatch.sync_run_id and resume_sequence:
                    # A reserved continuation may arrive after an operator
                    # pauses the job. Keep its durable outbox eligible on resume.
                    return {"status": "queued", "created": False}
                dispatch.status, dispatch.reason = "skipped", "任务已停用或暂停，未执行"
                dispatch.finished_at = timezone.now()
                dispatch.save(update_fields=["status", "reason", "finished_at"])
                return {"status": "skipped", "created": False}
            dispatch.status, dispatch.started_at = "running", dispatch.started_at or timezone.now()
            dispatch.save(update_fields=["status", "started_at"])
    try:
        validate_manual_sync_job(sync_job, live_only=True)
        kwargs = {"idempotency_key": idempotency_key, "dispatch": dispatch}
        if resume_sequence:
            kwargs["resume_sequence"] = resume_sequence
        run, created = run_sync_job(sync_job, **kwargs)
        if dispatch:
            SyncScheduleDispatch.objects.filter(pk=dispatch.pk, status="running").update(
                status=run.status, finished_at=run.finished_at,
                reason="本段时间预算已用完，分页进度已保存，等待续跑。" if run.status == "queued" else "",
            )
    except Exception as exc:
        fail_queued_sync_run(
            sync_job,
            idempotency_key,
            error_code="SYNC_PREFLIGHT_FAILED",
            message=str(exc),
        )
        if dispatch:
            SyncScheduleDispatch.objects.filter(pk=dispatch.pk, status="running").update(
                status="blocked", reason="执行校验或执行阶段失败，请核对授权、能力和只读准入，并查看同步异常。",
                finished_at=timezone.now(),
            )
        upsert_sync_failure_alert(
            sync_job,
            error_code="SYNC_PREFLIGHT_FAILED",
            message=str(exc),
        )
        raise
    return {"run_id": run.id, "status": run.status, "created": created}
@shared_task
def dispatch_due_readonly_sync_jobs(limit=20):
    def enqueue(job_id, key, resume_sequence=0):
        priority = 0 if SyncJob.objects.filter(pk=job_id, resource_type="inventory_snapshot").exists() else 5
        return run_readonly_sync_job.apply_async(
            args=(job_id,), kwargs={"idempotency_key": key, "resume_sequence": resume_sequence}, priority=priority,
        )
    result = dispatch_due_jobs(
        enqueue,
        limit=max(1, min(int(limit), 100)),
    )
    result["continued"] = resume_due_sync_runs(enqueue, limit=max(1, min(int(limit), 100)))
    return result
