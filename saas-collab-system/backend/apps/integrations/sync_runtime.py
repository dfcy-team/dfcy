"""Scoped serializers use database progress, not authorization switch guesses."""
from django.utils import timezone
from django.utils.dateparse import parse_datetime


def run_runtime_state(run):
    now = timezone.now()
    log = run.masked_log or {}
    budget = log.get("runtime_budget") or {}
    progress = parse_datetime(str(budget.get("last_page_committed_at") or ""))
    # Continuations keep the original run enqueue/start timestamps. Queue age
    # must start at the last committed yield, not the start of the whole batch.
    queued = progress if budget.get("pending") and progress else run.enqueued_at
    state, label = run.status, {
        "queued": "等待执行", "running": "执行中", "success": "已完成",
        "failed": "失败", "cancelled": "已取消",
    }.get(run.status, run.status)
    if run.status == "queued":
        if run.history_segment_id and run.history_segment.batch.status == "paused":
            state, label = "paused", "补采已暂停（断点保留）"
        elif run.error_code == "WAITING_CREDENTIAL_REFRESH":
            state, label = "credential_wait", "等待授权续期"
        elif (ready := parse_datetime(str(budget.get("ready_at") or ""))) and ready > now:
            state, label = "backoff", "等待续跑退避"
        elif budget.get("pending"):
            state, label = "queued", "等待分页续跑"
    delivery = log.get("delivery") or {}
    checked = parse_datetime(str(delivery.get("checked_at") or ""))
    fresh = checked and timezone.is_aware(checked) and 0 <= (now - checked).total_seconds() <= 180
    delivery_state = delivery.get("state", "unknown") if fresh and delivery.get("sequence") == budget.get("sequence", 0) else "unknown"
    return {
        "execution_lane": "history" if run.history_segment_id else "daily",
        "state": state, "label": label,
        "queued_since": queued.isoformat() if run.status == "queued" and queued else None,
        "last_progress_at": progress.isoformat() if progress else None,
        "wait_seconds": int(max(0, (now - queued).total_seconds())) if run.status == "queued" and queued else None,
        "delivery_state": delivery_state,
        "notice": "运行状态来自数据库；队列位置仅为最近巡检证据，未确认不代表丢失。自动续期、任务启用和派发心跳均不代表取数成功。",
    }
