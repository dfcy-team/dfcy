from celery import shared_task
from django.conf import settings
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
    if getattr(settings, 'REPLENISHMENT_MAINTENANCE_ENABLED', False) is not True:
        return 0
    return purge_replenishment_jobs()


@shared_task(name='apps.supply_chain.tasks.recover_replenishment_jobs', ignore_result=True)
def recover_replenishment_calculation_jobs():
    if getattr(settings, 'REPLENISHMENT_MAINTENANCE_ENABLED', False) is not True:
        return 0
    return recover_replenishment_jobs()

from .inbound_notification_tasks import dispatch as dispatch_inbound_notifications


@shared_task(name='apps.supply_chain.tasks.refresh_daily_batch_costs', ignore_result=True)
def refresh_daily_batch_costs(actor_id, limit=100, after_id=0):
    if getattr(settings, 'SUPPLY_MONTHLY_COST_JOBS_ENABLED', False) is not True:
        return {'status': 'disabled', 'processed': 0}
    from django.contrib.auth import get_user_model
    actor = get_user_model().objects.filter(pk=actor_id, user_type='internal', is_active=True).first()
    if actor is None or actor.tenant_id is None:
        return {'status': 'missing_actor', 'processed': 0}
    from .monthly_cost_jobs import run_daily_batch_costs
    return run_daily_batch_costs(actor, limit=limit, after_id=after_id)
