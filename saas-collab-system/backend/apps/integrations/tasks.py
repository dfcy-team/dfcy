from celery import shared_task

from .models import SyncJob
from .scheduler import dispatch_due_jobs
from .sync_services import run_sync_job


@shared_task(bind=True, soft_time_limit=840, time_limit=900)
def run_readonly_sync_job(self, sync_job_id, idempotency_key=None):
    sync_job = SyncJob.objects.select_related("tenant", "integration_config").get(pk=sync_job_id)
    run, created = run_sync_job(sync_job, idempotency_key=idempotency_key)
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
