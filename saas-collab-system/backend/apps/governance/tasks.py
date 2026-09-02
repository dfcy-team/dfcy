from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .execution import run_assistant_evaluation_job
from .models import AssistantEvaluationJob


def _dispatch_evaluation(job_id):
    """Best-effort enqueue; the next beat tick can safely retry this."""

    try:
        result = run_assistant_evaluation.apply_async(args=[job_id])
    except Exception:
        return False
    # The durable claim in run_assistant_evaluation_job is the source of truth;
    # this id is only a publish marker and is intentionally written after the
    # broker accepts the message. A crash before this write is recovered by
    # the next stale-dispatch tick and duplicate deliveries remain harmless.
    job = AssistantEvaluationJob.objects.filter(
        pk=job_id,
        status=AssistantEvaluationJob.Status.QUEUED,
        celery_task_id="",
    ).first()
    if job:
        job._execution_service_write = True
        try:
            job.celery_task_id = str(result.id)[:255]
            job.save(update_fields=["celery_task_id", "updated_at"])
        finally:
            job._execution_service_write = False
    return True


@shared_task(
    bind=True,
    name="governance.run_assistant_evaluation",
    soft_time_limit=150,
    time_limit=180,
    acks_late=True,
)
def run_assistant_evaluation(self, job_id):
    job = run_assistant_evaluation_job(job_id)
    return {"job_id": job.id, "status": job.status, "attempts": job.attempts}


@shared_task(name="governance.dispatch_stale_evaluations")
def dispatch_stale_evaluations(limit=50):
    """Compensate for a process crash between DB commit and broker publish."""

    cutoff = timezone.now() - timedelta(
        seconds=max(30, int(getattr(settings, "GOVERNANCE_EVALUATION_DISPATCH_STALE_SECONDS", 60)))
    )
    jobs = AssistantEvaluationJob.objects.filter(
        status=AssistantEvaluationJob.Status.QUEUED,
        celery_task_id="",
        created_at__lte=cutoff,
    ).order_by("created_at", "id")[: max(1, min(int(limit), 200))]
    dispatched = 0
    for job in jobs:
        if _dispatch_evaluation(job.id):
            dispatched += 1
    return {"dispatched": dispatched}


@shared_task(name="governance.reconcile_stale_evaluations")
def reconcile_stale_evaluations(limit=50):
    """Close jobs whose claiming worker disappeared before returning."""

    cutoff = timezone.now() - timedelta(
        seconds=max(300, int(getattr(settings, "GOVERNANCE_EVALUATION_STALE_SECONDS", 600)))
    )
    jobs = AssistantEvaluationJob.objects.filter(
        status=AssistantEvaluationJob.Status.RUNNING,
        started_at__isnull=False,
        started_at__lte=cutoff,
    ).order_by("started_at", "id")[: max(1, min(int(limit), 200))]
    reconciled = 0
    for job in jobs:
        # Reuse the same short claim/terminal fence. A duplicate worker that
        # is still finishing will either win the row lock first or observe a
        # terminal status; no provider response is replayed here.
        with transaction.atomic():
            current = AssistantEvaluationJob.objects.select_for_update().filter(
                pk=job.id,
                status=AssistantEvaluationJob.Status.RUNNING,
                started_at__lte=cutoff,
            ).first()
            if not current:
                continue
            current.status = AssistantEvaluationJob.Status.FAILED
            current.error_code = "EVALUATION_WORKER_LOST"
            current.error_message = "Evaluation worker did not finish within the service deadline."
            current.finished_at = timezone.now()
            current._execution_service_write = True
            try:
                current.save(update_fields=["status", "error_code", "error_message", "finished_at", "updated_at"])
            finally:
                current._execution_service_write = False
            reconciled += 1
    return {"reconciled": reconciled}
