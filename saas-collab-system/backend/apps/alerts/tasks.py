from celery import shared_task
from time import monotonic
from django.conf import settings


def _disabled_result():
    return {'skipped': True, 'reason': 'inventory_decision_background_tasks_disabled'}


@shared_task(soft_time_limit=240, time_limit=300)
def refresh_inventory_decisions(limit=50):
    if not settings.INVENTORY_DECISION_BACKGROUND_TASKS_ENABLED:
        return _disabled_result()
    from .inventory_refresh import refresh_due_decisions
    return refresh_due_decisions(limit)


@shared_task(soft_time_limit=240, time_limit=300)
def build_inventory_decision_views():
    if not settings.INVENTORY_DECISION_BACKGROUND_TASKS_ENABLED:
        return _disabled_result()
    from .inventory_views import build_pending_views, recover_views
    recover_views()
    result = {'processed': 0, 'completed': 0, 'failed': 0}
    deadline = monotonic() + 3.0
    # Drain a few bounded chunks without an artificial five-second Beat gap
    # between each 100 SKUs. Each chunk commits progress and yields the view
    # claim; ordering in build_pending_views keeps active views fair.
    for _ in range(10):
        chunk = build_pending_views(limit=2)
        for key in result:
            result[key] += chunk[key]
        if not any(chunk.values()) or monotonic() >= deadline:
            break
    return result
