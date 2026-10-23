from celery import shared_task
from .notifications import dispatch_due
from .replenishment_jobs import run_replenishment_calculation, purge_replenishment_jobs, recover_replenishment_jobs


@shared_task(name='apps.supply_chain.tasks.dispatch_notifications')
def dispatch_notifications():
    return dispatch_due(limit=20)


@shared_task(name='apps.supply_chain.tasks.run_replenishment_calculation', soft_time_limit=110, time_limit=120, ignore_result=True)
def calculate_replenishment(job_id):
    return run_replenishment_calculation(job_id)


@shared_task(name='apps.supply_chain.tasks.purge_replenishment_jobs', ignore_result=True)
def cleanup_replenishment_jobs():
    return purge_replenishment_jobs()


@shared_task(name='apps.supply_chain.tasks.recover_replenishment_jobs', ignore_result=True)
def recover_replenishment_calculation_jobs():
    return recover_replenishment_jobs()
