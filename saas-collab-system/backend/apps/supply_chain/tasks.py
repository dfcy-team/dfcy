from celery import shared_task
from .notifications import dispatch_due


@shared_task(name='apps.supply_chain.tasks.dispatch_notifications')
def dispatch_notifications():
    return dispatch_due(limit=20)
