"""Conservative, reversible cleanup of provably inconsistent empty queue rows.

Age or a missing broker message alone is NOT invalidity. Historical requests,
continuations, scheduled dispatches, failures and completed results are retained.
"""
import hashlib
import json

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import SyncJob, SyncRun
from .sync_delivery import read_delivery_snapshot

ARCHIVED_INVALID_QUEUE = "SYNC_INVALID_QUEUE_ARCHIVED"
MAX_SCAN = 500


def visible_runs(queryset):
    """Keep archived rows addressable by the existing scoped detail endpoint."""
    return queryset.exclude(error_code=ARCHIVED_INVALID_QUEUE)


def _base(tenant_id, cutoff):
    return SyncRun.objects.filter(
        tenant_id=tenant_id, sync_job__tenant_id=tenant_id,
        status="queued", started_at__isnull=True, finished_at__lte=cutoff,
        enqueued_at__lte=cutoff, history_segment__isnull=True,
        schedule_dispatch__isnull=True, error_code="", retry_count=0,
        fetched_count=0, created_count=0, updated_count=0, skipped_count=0, failed_count=0,
    ).select_related("sync_job").order_by("pk")


def _eligible(run, snapshot, now):
    if run.sync_job.status == "running" or (run.sync_job.lock_expires_at and run.sync_job.lock_expires_at > now):
        return False
    if run.idempotency_key.startswith(("history:", "scheduled:", "retry:", "resume:")):
        return False
    log = run.masked_log or {}
    if not isinstance(log, dict) or set(log) - {"execution_mode", "trigger_type", "delivery"}:
        return False
    # An unobservable broker cannot authorize discarding a queued request.
    return snapshot.complete and snapshot.state(run.sync_job_id, run.idempotency_key, 0) == "absent"


def _fingerprint(run):
    # Never expose the underlying key/log to command output or review samples.
    row = {field: getattr(run, field) for field in (
        "id", "sync_job_id", "tenant_id", "status", "run_id", "idempotency_key",
        "enqueued_at", "started_at", "finished_at", "masked_log", "error_code", "masked_error_message",
        "fetched_count", "created_count", "updated_count", "skipped_count", "failed_count", "retry_count",
    )}
    return hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()


def preview_invalid_runs(tenant_id, cutoff, snapshot=None, now=None):
    now = now or timezone.now()
    if type(tenant_id) is not int or tenant_id < 1 or not timezone.is_aware(cutoff) or cutoff > now:
        raise ValidationError("必须指定有效租户及已过去的 UTC 截止时间。")
    snapshot = snapshot if snapshot is not None else read_delivery_snapshot()
    rows = list(_base(tenant_id, cutoff)[:MAX_SCAN + 1])
    eligible = [run for run in rows[:MAX_SCAN] if _eligible(run, snapshot, now)]
    plan = {"tenant_id": tenant_id, "cutoff": cutoff.isoformat(),
            "candidates": [{"id": run.pk, "before_sha256": _fingerprint(run)} for run in eligible]}
    digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    return {"status": "PREVIEW_ONLY", "candidate_count": len(eligible), "scan_complete": len(rows) <= MAX_SCAN,
            "broker_evidence_complete": snapshot.complete, "plan_sha256": digest,
            "plan": plan, "deleted_count": 0, "business_data_writes": 0}


def archive_invalid_runs(tenant_id, cutoff, expected_sha256):
    """Soft archive only an unchanged reviewed plan; no run/data is deleted."""
    initial = preview_invalid_runs(tenant_id, cutoff)
    if (not initial["scan_complete"] or not initial["broker_evidence_complete"]
            or initial["plan_sha256"] != expected_sha256):
        raise ValidationError("清理预览已变化或队列证据不完整，请重新预览。")
    ids = [row["id"] for row in initial["plan"]["candidates"]]
    if not ids:
        return {**initial, "status": "NO_INVALID_RUNS", "archived_count": 0}
    with transaction.atomic():
        job_ids = list(SyncRun.objects.filter(tenant_id=tenant_id, pk__in=ids).values_list("sync_job_id", flat=True))
        list(SyncJob.objects.select_for_update(of=("self",)).filter(
            tenant_id=tenant_id, pk__in=job_ids).order_by("pk"))
        list(SyncRun.objects.select_for_update(of=("self",)).filter(
            tenant_id=tenant_id, pk__in=ids).order_by("pk"))
        fresh = preview_invalid_runs(tenant_id, cutoff)
        if (not fresh["scan_complete"] or not fresh["broker_evidence_complete"]
                or fresh["plan_sha256"] != expected_sha256):
            raise ValidationError("运行记录或队列证据已变化，未清理任何记录。")
        now = timezone.now()
        for run in _base(tenant_id, cutoff).filter(pk__in=ids):
            run.masked_log = {**(run.masked_log or {}), "invalid_queue_archive": {
                "archived_at": now.isoformat(), "reason": "empty_queued_row_has_terminal_timestamp",
                "original_status": run.status, "original_error_code": run.error_code,
                "original_masked_error_message": run.masked_error_message,
                "before_sha256": _fingerprint(run), "plan_sha256": expected_sha256,
            }}
            run.status = "cancelled"
            run.error_code = ARCHIVED_INVALID_QUEUE
            run.masked_error_message = "已可恢复归档：空排队记录已有结束时间，且未开始执行、无投递/历史/定时/断点证据。"
            run.save(update_fields=["status", "error_code", "masked_error_message", "masked_log"])
    return {**fresh, "status": "INVALID_EMPTY_QUEUE_ROWS_ARCHIVED", "archived_count": len(ids)}
