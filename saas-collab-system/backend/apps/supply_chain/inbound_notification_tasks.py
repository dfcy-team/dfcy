from celery import shared_task
from .inbound_notifications import dispatch_due

@shared_task(name='apps.supply_chain.inbound_notification_tasks.dispatch', ignore_result=True, soft_time_limit=110, time_limit=120)
def dispatch():
    return dispatch_due(limit=10)
