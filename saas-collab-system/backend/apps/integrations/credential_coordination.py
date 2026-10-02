"""Yield data work at page boundaries; never rotate a token in a data worker."""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .automatic_refresh import automatic_refresh_allowed, credential_refresh_state
from .models import SyncJob, SyncRun, SyncScheduleDispatch

WAIT_CODE = "WAITING_CREDENTIAL_REFRESH"
WAIT_MESSAGE = "等待自动续期；已保留查询范围和采集断点，续期后由调度继续。"
WAIT_TIMEOUT_SECONDS = 1800


def job_refresh_wait(job):
    record = job.store_authorization or job.warehouse_authorization
    if not record or job.integration_config.environment not in {"pilot", "production"}:
        return None
    record.refresh_from_db()
    state = credential_refresh_state(record)
    if state["state"] not in {"due", "refreshing", "retry_wait"}:
        return None
    return state if automatic_refresh_allowed(record, ignore_running=True) else None


def wait_metadata(previous=None):
    now = timezone.now()
    previous = previous or {}
    started = parse_datetime(str(previous.get("started_at") or "")) if previous.get("active") else None
    started = started or now
    if (now - started).total_seconds() >= WAIT_TIMEOUT_SECONDS:
        return None
    return {"active": True, "started_at": started.isoformat(),
            "deadline_at": (started + timedelta(seconds=WAIT_TIMEOUT_SECONDS)).isoformat()}


def defer_queued_for_refresh(job, *, existing, key, dispatch=None, history_segment=None):
    if not key or not job.is_enabled or job.status == "disabled" or not job_refresh_wait(job):
        return None
    log = (existing.masked_log or {}) if existing else {}
    wait = wait_metadata(log.get("renewal_wait"))
    if wait is None:
        return None  # normal preflight reports failure; never wait indefinitely
    from .sync_services import _run_id
    with transaction.atomic():
        locked = SyncJob.objects.select_for_update().get(pk=job.pk, tenant_id=job.tenant_id)
        if not locked.is_enabled or locked.status in {"running", "disabled"}:
            return None
        run, _ = SyncRun.objects.get_or_create(
            sync_job=locked, idempotency_key=key,
            defaults={"tenant_id": locked.tenant_id, "run_id": _run_id(), "status": "queued",
                      "enqueued_at": timezone.now(), "history_segment": history_segment},
        )
        run = SyncRun.objects.select_for_update().get(pk=run.pk)
        if run.status != "queued":
            return None
        budget = dict((run.masked_log or {}).get("runtime_budget") or {})
        budget.update({"sequence": int(budget.get("sequence", 0)), "pending": True,
                       "ready_at": (timezone.now() + timedelta(seconds=60)).isoformat(), "submitted_at": None})
        run.error_code, run.masked_error_message = WAIT_CODE, WAIT_MESSAGE
        run.masked_log = {**(run.masked_log or {}), "runtime_budget": budget, "renewal_wait": wait}
        run.save(update_fields=["error_code", "masked_error_message", "masked_log"])
        if history_segment:
            type(history_segment).objects.filter(pk=history_segment.pk).update(status="queued", submitted_at=None)
        if dispatch:
            SyncScheduleDispatch.objects.filter(pk=dispatch.pk).update(status="queued", sync_run=run, reason=WAIT_MESSAGE)
        return run
