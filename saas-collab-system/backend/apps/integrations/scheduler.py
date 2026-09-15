from copy import copy
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError

from .models import SyncJob, SyncScheduleDispatch, SyncSchedulerHeartbeat
from .sync_alerts import upsert_sync_failure_alert

# The dispatcher ticks every minute. Older slots are missed, not new executions.
MISFIRE_GRACE_SECONDS = 60
DISPATCH_START_TIMEOUT = timedelta(minutes=5)


def recover_unstarted_dispatches(now, limit):
    ids = list(SyncScheduleDispatch.objects.filter(
        status="running", sync_run__isnull=True,
        started_at__lte=now - DISPATCH_START_TIMEOUT,
    ).values_list("pk", "sync_job_id")[:limit])
    for pk, job_id in ids:
        with transaction.atomic():
            job = SyncJob.objects.select_for_update().get(pk=job_id)
            if job.status == "running" or (job.lock_expires_at and job.lock_expires_at > now):
                continue
            if job.runs.filter(status="running").exists():
                continue
            SyncScheduleDispatch.objects.filter(pk=pk, status="running", sync_run__isnull=True).update(
                status="failed", finished_at=now,
                reason="派发启动超时：未取得执行锁或创建运行，已终止此计划时点；后续计划可继续。",
            )


def schedule_policy(job):
    scope = job.sync_scope or {}
    return scope.get("schedule") if isinstance(scope.get("schedule"), dict) else scope


def paused_until(job):
    value = parse_datetime(str(schedule_policy(job).get("pause_until") or ""))
    return value if value and timezone.is_aware(value) else None


def calculate_next_run_at(sync_job, reference=None):
    if not sync_job.is_enabled or sync_job.schedule_type in {"manual", "cron"}:
        return None
    reference = reference or timezone.now()
    schedule = schedule_policy(sync_job)
    pause = paused_until(sync_job)
    if pause and pause > reference:
        reference = pause
    kind = sync_job.schedule_type
    if kind in {"interval", "hourly"}:
        return reference + timedelta(minutes=int(schedule.get("interval_minutes") or 60))
    if kind not in {"daily", "weekly"}:
        return None
    zone = ZoneInfo(schedule.get("timezone") or "Asia/Shanghai")
    local_reference = reference.astimezone(zone)
    hour, minute = map(int, (schedule.get("local_time") or "02:00").split(":"))
    weekdays = schedule.get("weekdays") or list(range(1, 8))
    for offset in range(15):
        day = local_reference.date() + timedelta(days=offset)
        if kind == "weekly" and day.isoweekday() not in weekdays:
            continue
        candidate = datetime.combine(day, time(hour, minute), tzinfo=zone)
        utc_candidate = candidate.astimezone(UTC)
        # Skip nonexistent wall times at a DST transition; choose fold=0 once.
        if utc_candidate.astimezone(zone).replace(tzinfo=None) != candidate.replace(tzinfo=None):
            continue
        if utc_candidate > reference:
            return utc_candidate
    raise ValidationError("无法计算下一次执行时间，请检查计划。")


def preview_schedule(job, reference=None):
    candidate = copy(job)
    candidate.is_enabled = True
    cursor = reference or timezone.now()
    result = []
    for _ in range(3):
        cursor = calculate_next_run_at(candidate, cursor)
        if cursor is None:
            break
        result.append(cursor)
    return result


def next_after_missed(job, due, now):
    if job.schedule_type in {"interval", "hourly"}:
        delta = timedelta(minutes=int(schedule_policy(job).get("interval_minutes") or 60))
        return due + (max(0, (now - due) // delta) + 1) * delta
    return calculate_next_run_at(job, now)


def dispatch_due_jobs(enqueue, now=None, limit=20):
    now = now or timezone.now()
    SyncSchedulerHeartbeat.objects.update_or_create(key="readonly", defaults={"last_seen_at": now})
    recover_unstarted_dispatches(now, limit)
    initialized = dispatched = failed = skipped = 0
    ids = list(SyncJob.objects.filter(is_enabled=True).exclude(schedule_type__in=["manual", "cron"])
               .filter(next_run_at__isnull=True).values_list("id", flat=True)[:limit])
    for pk in ids:
        with transaction.atomic():
            job = SyncJob.objects.select_for_update().get(pk=pk)
            if job.is_enabled and job.next_run_at is None and job.schedule_type not in {"manual", "cron"}:
                job.next_run_at = calculate_next_run_at(job, now)
                job.save(update_fields=["next_run_at"])
                initialized += 1
    due_ids = list(SyncJob.objects.filter(is_enabled=True, next_run_at__lte=now)
                   .exclude(schedule_type__in=["manual", "cron"]).order_by("next_run_at", "id")
                   .values_list("id", flat=True)[:limit])
    for pk in due_ids:
        with transaction.atomic():
            job = SyncJob.objects.select_for_update().get(pk=pk)
            if not job.is_enabled or job.status == "disabled" or not job.next_run_at or job.next_run_at > now:
                continue
            pause = paused_until(job)
            if pause and pause > now:
                continue
            if job.status == "running":
                from .sync_services import _has_expired_lease, _recover_expired_lease
                if _has_expired_lease(job, now):
                    _recover_expired_lease(job, now)
                    job.schedule_dispatches.filter(status="running").update(status="failed", reason="执行锁已过期，旧执行已终止。", finished_at=now)
            if job.status == "running" or (job.lock_expires_at and job.lock_expires_at > now):
                continue
            for completed in job.schedule_dispatches.filter(status="running", sync_run__status__in=["success", "failed", "cancelled"]).select_related("sync_run"):
                completed.status, completed.finished_at = completed.sync_run.status, completed.sync_run.finished_at
                completed.save(update_fields=["status", "finished_at"])
            if job.schedule_dispatches.filter(status__in=["queued", "running"]).exists():
                continue
            due = job.next_run_at
            missed = (now - due).total_seconds() > MISFIRE_GRACE_SECONDS
            skip = missed and schedule_policy(job).get("catch_up", "skip") != "run_once"
            dispatch, created = SyncScheduleDispatch.objects.get_or_create(
                sync_job=job, scheduled_at=due,
                defaults={"tenant": job.tenant, "status": "skipped" if skip else "queued",
                          "finished_at": now if skip else None,
                          "reason": "错过计划，按策略跳过" if skip else "",
                          "schedule_snapshot": {"schedule_type": job.schedule_type, **schedule_policy(job)}},
            )
            job.next_run_at = next_after_missed(job, due, now)
            job.save(update_fields=["next_run_at", "updated_at"])
            if not created:
                continue
            if skip:
                skipped += 1
                continue
        try:
            # Claim was committed before broker submission. An uncertain broker
            # result must not cause this plan occurrence to be sent a second time.
            enqueue(job.id, f"scheduled:{job.id}:{dispatch.pk}")
            SyncScheduleDispatch.objects.filter(pk=dispatch.pk).update(enqueued_at=now)
            dispatched += 1
        except Exception:
            SyncScheduleDispatch.objects.filter(pk=dispatch.pk, status="queued").update(
                status="dispatch_failed", reason="队列提交结果无法确认，请检查队列；未重复派发。", finished_at=now)
            upsert_sync_failure_alert(job, error_code="SCHEDULER_ENQUEUE_FAILED", message="队列提交结果无法确认，请检查队列；此计划未重复派发。")
            failed += 1
    return {"initialized": initialized, "dispatched": dispatched, "failed": failed, "skipped": skipped}


def scheduler_health():
    heartbeat = SyncSchedulerHeartbeat.objects.filter(key="readonly").first()
    seen = heartbeat.last_seen_at if heartbeat else None
    return {"last_seen_at": seen.isoformat() if seen else None,
            "heartbeat_state": "unknown" if not seen else "recent" if (timezone.now() - seen).total_seconds() <= 180 else "stale",
            "notice": "仅说明派发服务心跳，不代表队列消费者或平台同步成功。"}
