"""Opt-in bounded sampling. Never enables report delivery."""
from celery import shared_task
from django.conf import settings


@shared_task(soft_time_limit=50, time_limit=55)
def capture_due_sales_nine():
    if not getattr(settings, 'SALES_NINE_SNAPSHOT_ENABLED', False):
        return {'status': 'disabled', 'created': 0}
    raw = getattr(settings, 'SALES_NINE_SNAPSHOT_STORE_IDS', [])
    if not isinstance(raw, (list, tuple)) or not raw or len(raw) > 100:
        return {'status': 'invalid_allowlist', 'created': 0}
    if any(not str(v).isascii() or not str(v).isdecimal() or len(str(v)) > 19 or not 1 <= int(v) <= 9223372036854775807 for v in raw):
        return {'status': 'invalid_allowlist', 'created': 0}
    from apps.masterdata.models import StoreMaster
    from .nine_snapshot_capture import capture_store
    created = errors = 0
    for store in StoreMaster.objects.filter(pk__in=[int(v) for v in raw]).order_by('pk'):
        try:
            _, fresh = capture_store(store)
            created += int(fresh)
        except (ValueError, KeyError):
            errors += 1
    return {'status': 'completed', 'created': created, 'invalid_timezone': errors}
