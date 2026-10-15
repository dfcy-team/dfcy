"""One-shot history execution windows; never change the normal job schedule."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import HistorySyncTaskControl

BEIJING = ZoneInfo("Asia/Shanghai")
DEFAULT_POLICY = {"mode": "anytime", "timezone": "Asia/Shanghai", "start_time": "00:30", "end_time": "06:00"}


def validate_execution_policy(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULT_POLICY):
        raise ValidationError("补采执行时段参数无效。")
    policy = {**DEFAULT_POLICY, **value}
    if not isinstance(policy["mode"], str) or policy["mode"] not in {"anytime", "night"} or policy["timezone"] != "Asia/Shanghai":
        raise ValidationError("补采执行时段须选择随时执行或北京时间夜间执行。")
    try:
        start, end = time.fromisoformat(policy["start_time"]), time.fromisoformat(policy["end_time"])
        if any(len(policy[key]) != 5 for key in ("start_time", "end_time")) or not start < end:
            raise ValueError
        # The option promises post-midnight, low-traffic operation, not a hidden all-day schedule.
        if end > time(8, 0):
            raise ValueError
    except (TypeError, ValueError):
        raise ValidationError("夜间窗口须在北京时间 00:00～08:00 内，使用 HH:MM 且结束晚于开始。")
    return policy


def execution_window(policy, now=None):
    policy = validate_execution_policy(policy or {})
    now = now or timezone.now()
    if policy["mode"] == "anytime":
        return {"allowed": True, "state": "ready", "next_eligible_at": None, "policy": policy}
    local = now.astimezone(BEIJING)
    start = datetime.combine(local.date(), time.fromisoformat(policy["start_time"]), BEIJING)
    end = datetime.combine(local.date(), time.fromisoformat(policy["end_time"]), BEIJING)
    if start <= local < end:
        return {"allowed": True, "state": "ready", "next_eligible_at": None, "policy": policy}
    following = start if local < start else start + timedelta(days=1)
    return {"allowed": False, "state": "waiting_window", "next_eligible_at": following.isoformat(), "policy": policy}


def history_task_gate(batch, job_id, now=None, control=None):
    control = control or HistorySyncTaskControl.objects.filter(batch_id=batch.pk, sync_job_id=job_id).first()
    try:
        result = execution_window(control.execution_policy if control else {}, now)
    except ValidationError:
        return {"allowed": False, "state": "invalid_schedule", "next_eligible_at": None, "policy": None}
    if batch.status == "paused" or (control and control.is_paused):
        result.update(allowed=False, state="paused", next_eligible_at=None)
    elif batch.status not in {"running", "failed", "completed"}:
        result.update(allowed=False, state="blocked", next_eligible_at=None)
    result["pause_reason"] = control.pause_reason if control else ""
    return result


def history_authorizer(segment):
    control = HistorySyncTaskControl.objects.filter(batch_id=segment.batch_id, sync_job_id=segment.sync_job_id).select_related("authorized_by").first()
    return control.authorized_by if control and control.authority_assigned else segment.batch.created_by


def runnable_history_exists(job, now):
    """Waiting history must not starve the same task's ordinary daytime sync."""
    from .models import HistorySyncBatch
    batch_ids = job.history_segments.exclude(status__in=["success", "failed"]).values("batch_id")
    batches = HistorySyncBatch.objects.filter(pk__in=batch_ids, status="running")
    return any(history_task_gate(batch, job.pk, now)["allowed"] for batch in batches)


def blocking_runs(queryset, now):
    """Only ignore queued history gated at claim time; running leases always block."""
    waiting = []
    for run in queryset.filter(status="queued", history_segment__isnull=False).select_related("history_segment__batch"):
        if not history_task_gate(run.history_segment.batch, run.sync_job_id, now)["allowed"]:
            waiting.append(run.pk)
    return queryset.exclude(pk__in=waiting)


def pause_for_permission(segment):
    control, _ = HistorySyncTaskControl.objects.get_or_create(batch_id=segment.batch_id, sync_job_id=segment.sync_job_id)
    control.is_paused, control.pause_reason = True, "permission_changed"
    control.save(update_fields=["is_paused", "pause_reason", "updated_at"])
