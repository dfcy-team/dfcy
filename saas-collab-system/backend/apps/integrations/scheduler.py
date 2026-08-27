from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import SyncJob


def calculate_next_run_at(sync_job, reference=None):
    if not sync_job.is_enabled or sync_job.schedule_type == SyncJob.ScheduleType.MANUAL:
        return None
    reference = reference or timezone.now()
    scope = dict(sync_job.sync_scope or {})
    schedule = scope.get("schedule") if isinstance(scope.get("schedule"), dict) else scope
    pause_until = parse_datetime(str(schedule.get("pause_until") or ""))
    if pause_until and timezone.is_naive(pause_until):
        pause_until = timezone.make_aware(pause_until)
    if pause_until and pause_until > reference:
        return pause_until

    schedule_type = str(sync_job.schedule_type or "interval")
    if schedule_type in {"interval", "hourly", "cron"}:
        default_minutes = 60
        minutes = max(1, int(schedule.get("interval_minutes") or default_minutes))
        return reference + timedelta(minutes=minutes)

    try:
        local_zone = ZoneInfo(str(schedule.get("timezone") or "Asia/Shanghai"))
    except ZoneInfoNotFoundError:
        local_zone = ZoneInfo("Asia/Shanghai")
    local_reference = reference.astimezone(local_zone)
    try:
        hour, minute = [int(value) for value in str(schedule.get("local_time") or "02:00").split(":", 1)]
        local_time = time(hour=hour, minute=minute)
    except (TypeError, ValueError):
        local_time = time(hour=2)
    weekdays = {int(day) for day in schedule.get("weekdays") or range(1, 8)}
    for offset in range(0, 8):
        local_day = local_reference.date() + timedelta(days=offset)
        if schedule_type == "weekly" and local_day.isoweekday() not in weekdays:
            continue
        candidate = datetime.combine(local_day, local_time, tzinfo=local_zone)
        if candidate > local_reference:
            return candidate.astimezone(UTC)
    return reference + timedelta(days=1)


def dispatch_due_jobs(enqueue, now=None, limit=20):
    now = now or timezone.now()
    initialized = 0
    for job in SyncJob.objects.filter(
        is_enabled=True,
        next_run_at__isnull=True,
    ).exclude(schedule_type=SyncJob.ScheduleType.MANUAL)[:limit]:
        next_run_at = calculate_next_run_at(job, now)
        if next_run_at:
            initialized += SyncJob.objects.filter(pk=job.pk, next_run_at__isnull=True).update(
                next_run_at=next_run_at
            )

    due_ids = list(
        SyncJob.objects.filter(
            is_enabled=True,
            status__in=(SyncJob.Status.IDLE, SyncJob.Status.FAILED),
            next_run_at__lte=now,
        )
        .exclude(schedule_type=SyncJob.ScheduleType.MANUAL)
        .order_by("next_run_at", "id")
        .values_list("id", flat=True)[:limit]
    )
    dispatched = 0
    failed = 0
    for job_id in due_ids:
        with transaction.atomic():
            job = SyncJob.objects.select_for_update().get(pk=job_id)
            if not job.next_run_at or job.next_run_at > now:
                continue
            due_at = job.next_run_at
            idempotency_key = f"scheduled:{job.id}:{int(due_at.timestamp())}"
            job.next_run_at = calculate_next_run_at(job, max(now, due_at))
            job.save(update_fields=["next_run_at", "updated_at"])
        try:
            enqueue(job.id, idempotency_key)
            dispatched += 1
        except Exception:
            SyncJob.objects.filter(pk=job.id, status__in=(SyncJob.Status.IDLE, SyncJob.Status.FAILED)).update(
                next_run_at=due_at
            )
            failed += 1
    return {"initialized": initialized, "dispatched": dispatched, "failed": failed}
