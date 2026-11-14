"""Durable manual requests and opt-in scheduling, from activation onward."""
import uuid
from datetime import timedelta
from time import monotonic

from celery import shared_task
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .platform_wallet_models import PlatformWalletSync, PlatformWalletCursor
from .platform_wallet_service import require_sync, visible_stores, sync_store
from .summary_jobs import run_calculation, dispatch_calculations  # noqa: F401


@shared_task(acks_late=True, soft_time_limit=1740, time_limit=1800)
def process_warehouse_bill(pk, version, operation):
    from .warehouse_bill_uploads import process_job
    process_job(pk, version, operation)


def enqueue(sync):
    try:
        run_platform_wallet_sync.apply_async(args=[sync.pk], queue='platform-wallet', retry=False)
        return True
    except Exception:
        PlatformWalletSync.objects.filter(pk=sync.pk, state='queued').update(last_error_code='BROKER_UNAVAILABLE')
        return False


@shared_task
def dispatch_platform_wallet_sync():
    now = timezone.now()
    query = PlatformWalletSync.objects.filter(Q(state='queued') | Q(enabled=True, next_run_at__lte=now)
        | Q(state='running', running_until__lte=now))
    dispatched = 0
    for row in query.order_by('pk')[:100]:
        if row.state == 'running' and row.running_until and row.running_until <= now:
            PlatformWalletSync.objects.filter(pk=row.pk, lease=row.lease, running_until__lte=now).update(state='queued')
            row.refresh_from_db()
        # Worker claims a lease and rechecks user/store permissions. Duplicate
        # deliveries do not acquire the same lease or advance checkpoints.
        try:
            run_platform_wallet_sync.apply_async(args=[row.pk], kwargs={'scheduled': row.state != 'queued'}, queue='platform-wallet', retry=False)
            dispatched += 1
        except Exception:
            PlatformWalletSync.objects.filter(pk=row.pk).update(last_error_code='BROKER_UNAVAILABLE')
    return {'dispatched': dispatched}


@shared_task(soft_time_limit=840, time_limit=900, acks_late=True)
def run_platform_wallet_sync(pk, *, scheduled=False):
    now, lease = timezone.now(), uuid.uuid4()
    with transaction.atomic():
        row = PlatformWalletSync.objects.select_for_update().select_related('actor').get(pk=pk)
        if row.running_until and row.running_until > now:
            return {'status': 'already_running'}
        if scheduled and (not row.enabled or not row.next_run_at or row.next_run_at > now):
            return {'status': 'not_due'}
        if not scheduled and row.state != 'queued':
            return {'status': 'not_requested'}
        if row.actor.tenant_id != row.tenant_id:
            row.state, row.last_error_code, row.enabled = 'blocked', 'PERMISSION_CHANGED', False
            row.save(update_fields=['state', 'last_error_code', 'enabled'])
            return {'status': 'blocked'}
        try:
            require_sync(row.actor)
        except Exception:
            row.state, row.last_error_code, row.enabled = 'blocked', 'PERMISSION_CHANGED', False
            row.save(update_fields=['state', 'last_error_code', 'enabled'])
            return {'status': 'blocked'}
        row.lease, row.running_until = lease, now + timedelta(minutes=15)
        row.state, row.last_run_at, row.last_error_code = 'running', now, ''
        row.next_run_at = now + timedelta(minutes=row.interval_minutes) if row.enabled else None
        row.save()
    results, began = [], monotonic()
    try:
        stores = visible_stores(row.actor).filter(pk__in=visible_stores(row.actor, 'finance.import').values('pk'))
        for store in stores:
            if monotonic() - began > 600:
                results.append({'status': 'incomplete', 'error_code': 'RUNTIME_BUDGET'})
                break
            current = PlatformWalletSync.objects.get(pk=pk)
            if current.lease != lease or scheduled and not current.enabled:
                results.append({'status': 'blocked', 'error_code': 'SYNC_CANCELLED'})
                break
            try:
                result = sync_store(row, store, end=now, lease=lease)
            except Exception:
                # Never store a provider exception; it may contain a signed URL.
                code = 'STORE_API_SYNC_FAILED'
                if store.platform.platform_type == 'lazada':
                    code = 'LAZADA_TIMEZONE_OR_API_NOT_VERIFIED'
                cursor, _ = PlatformWalletCursor.objects.get_or_create(sync=row, store=store)
                cursor.last_error_code, cursor.last_attempt_at = code, timezone.now()
                cursor.save(update_fields=['last_error_code', 'last_attempt_at'])
                result = {'store_id': store.pk, 'status': 'failed', 'error_code': code}
            results.append(result)
        problem = any(result['status'] in {'failed', 'incomplete', 'blocked', 'unsupported'} for result in results)
        state = 'partial' if problem else 'succeeded'
        if results and all(result['status'] == 'unsupported' for result in results):
            state = 'unsupported'
        if not results:
            state = 'no_visible_stores'
    except Exception:
        state = 'failed'
        results = [{'status': 'failed', 'error_code': 'WALLET_SYNC_FAILED'}]
    PlatformWalletSync.objects.filter(pk=pk, lease=lease).update(state=state,
        summary={'results': results}, running_until=None, lease=None,
        last_error_code='PARTIAL_OR_FAILED' if state in {'partial', 'failed'} else '')
    return {'status': state}
