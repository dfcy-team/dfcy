from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .models import SyncJob, SyncScheduleDispatch
from .scheduler import dispatch_due_jobs, paused_until
from .sync_services import fail_queued_sync_run, run_sync_job, validate_manual_sync_job
from .sync_alerts import upsert_sync_failure_alert


@shared_task
def refresh_due_integration_credentials():
    from .automatic_refresh import refresh_due_authorizations
    return refresh_due_authorizations()


@shared_task(bind=True, soft_time_limit=840, time_limit=900)
def run_readonly_sync_job(self, sync_job_id, idempotency_key=None):
    sync_job = SyncJob.objects.select_related("tenant", "integration_config").get(pk=sync_job_id)
    dispatch = None
    if str(idempotency_key or "").startswith("scheduled:"):
        with transaction.atomic():
            sync_job = SyncJob.objects.select_for_update().select_related("tenant", "integration_config").get(pk=sync_job_id)
            dispatch = SyncScheduleDispatch.objects.filter(pk=str(idempotency_key).split(":")[-1], sync_job=sync_job).first()
            if not dispatch or dispatch.status != "queued":
                return {"status": "not_executed", "created": False}
            pause = paused_until(sync_job)
            if not sync_job.is_enabled or (pause and pause > timezone.now()):
                dispatch.status, dispatch.reason = "skipped", "任务已停用或暂停，未执行"
                dispatch.finished_at = timezone.now()
                dispatch.save(update_fields=["status", "reason", "finished_at"])
                return {"status": "skipped", "created": False}
            dispatch.status, dispatch.started_at = "running", timezone.now()
            dispatch.save(update_fields=["status", "started_at"])
    try:
        validate_manual_sync_job(sync_job, live_only=True)
        run, created = run_sync_job(sync_job, idempotency_key=idempotency_key, dispatch=dispatch)
        if dispatch:
            dispatch.status, dispatch.finished_at = run.status, run.finished_at
            dispatch.save(update_fields=["status", "finished_at"])
    except Exception as exc:
        fail_queued_sync_run(
            sync_job,
            idempotency_key,
            error_code="SYNC_PREFLIGHT_FAILED",
            message=str(exc),
        )
        if dispatch:
            dispatch.status, dispatch.reason, dispatch.finished_at = "blocked", "执行校验或执行阶段失败，请核对授权、能力和只读准入，并查看同步异常。", timezone.now()
            dispatch.save(update_fields=["status", "reason", "finished_at"])
        upsert_sync_failure_alert(
            sync_job,
            error_code="SYNC_PREFLIGHT_FAILED",
            message=str(exc),
        )
        raise
    return {"run_id": run.id, "status": run.status, "created": created}
@shared_task
def dispatch_due_readonly_sync_jobs(limit=20):
    return dispatch_due_jobs(
        lambda sync_job_id, idempotency_key: run_readonly_sync_job.delay(
            sync_job_id,
            idempotency_key=idempotency_key,
        ),
        limit=max(1, min(int(limit), 100)),
    )
