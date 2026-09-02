from celery.exceptions import MaxRetriesExceededError
from celery import shared_task
from django.conf import settings
from datetime import timedelta
from django.utils import timezone

from .execution import _mark_runner_manual_required, _save_execution, run_pilot_execution
from .models import PilotExecution


@shared_task(
    bind=True,
    name="pilot.run_execution",
    soft_time_limit=900,
    time_limit=960,
    acks_late=True,
    max_retries=720,
)
def execute_pilot_execution(self, execution_id):
    execution = run_pilot_execution(execution_id)
    if execution.status == "running":
        try:
            raise self.retry(
                countdown=max(1.0, min(float(getattr(settings, "PILOT_RUNNER_POLL_RETRY_DELAY", 5)), 60.0)),
                max_retries=max(1, min(int(getattr(settings, "PILOT_RUNNER_MAX_TASK_RETRIES", 720)), 2000)),
            )
        except MaxRetriesExceededError:
            execution = _mark_runner_manual_required(
                execution_id,
                error_code="RUNNER_RETRY_LIMIT",
                summary="Runner polling retry limit reached; manual intervention is required.",
            )
    return {
        "execution_id": execution.id,
        "status": execution.status,
        "attempt": execution.attempt,
    }


def _dispatch_execution(execution_id):
    try:
        result = execute_pilot_execution.apply_async(args=[execution_id])
    except Exception:
        return False
    execution = PilotExecution.objects.filter(
        pk=execution_id,
        status__in=(PilotExecution.Status.QUEUED, PilotExecution.Status.RUNNING),
        celery_task_id="",
    ).first()
    if execution:
        execution.celery_task_id = str(result.id)[:255]
        _save_execution(execution, ["celery_task_id"])
    return True


@shared_task(name="pilot.dispatch_stale_executions")
def dispatch_stale_executions(limit=50):
    """Recover queued or running executions after publish/worker loss."""

    cutoff = timezone.now() - timedelta(
        seconds=max(30, int(getattr(settings, "PILOT_EXECUTION_DISPATCH_STALE_SECONDS", 120)))
    )
    executions = PilotExecution.objects.filter(
        status__in=(PilotExecution.Status.QUEUED, PilotExecution.Status.RUNNING),
        updated_at__lte=cutoff,
    ).order_by("updated_at", "id")[: max(1, min(int(limit), 200))]
    dispatched = 0
    for execution in executions:
        if _dispatch_execution(execution.id):
            dispatched += 1
    return {"dispatched": dispatched}
