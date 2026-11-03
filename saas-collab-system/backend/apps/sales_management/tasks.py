"""Hour-based known-return polling; never discover or backfill historical warehouse data."""
from datetime import timedelta
from time import monotonic

from celery import shared_task
from django.db import transaction
from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.permissions.services import check_user_permission
from .aftersales import MANAGE, require_full_scope, visible_cases, refresh_case, ingest_receipt
from .aftersales_models import AftersalesCase, AftersalesSyncSettings


@shared_task
def dispatch_aftersales_sync():
    now = timezone.now()
    # Timeout bookkeeping is local, independent of network availability. It
    # never uses a failed API request as evidence that stock was not received.
    for pk in AftersalesCase.objects.filter(return_status__in=['pending', 'partial'], due_at__lte=now).order_by('pk').values_list('pk', flat=True)[:1000]:
        with transaction.atomic():
            case = AftersalesCase.objects.select_for_update().get(pk=pk)
            refresh_case(case, now=now)
    rows = AftersalesSyncSettings.objects.filter(is_enabled=True, authorization__isnull=False).filter(
        next_run_at__isnull=True) | AftersalesSyncSettings.objects.filter(is_enabled=True, authorization__isnull=False, next_run_at__lte=now)
    count = 0
    for pk in rows.order_by('pk').values_list('pk', flat=True)[:100]:
        synchronize_aftersales.apply_async(args=[pk], kwargs={'scheduled': True}, queue='sync', retry=False)
        count += 1
    return {'submitted': count}


@shared_task(soft_time_limit=840, time_limit=900, acks_late=True)
def synchronize_aftersales(pk, *, scheduled=False):
    now = timezone.now()
    with transaction.atomic():
        row = AftersalesSyncSettings.objects.select_for_update().select_related(
            'authorization__warehouse', 'authorization__integration_config', 'requested_by').get(pk=pk)
        if not row.authorization_id:
            return {'status': 'unbound', 'called_provider': False}
        if scheduled and (not row.is_enabled or row.next_run_at and row.next_run_at > now):
            return {'status': 'not_due', 'called_provider': False}
        if row.running_until and row.running_until > now:
            return {'status': 'already_running', 'called_provider': False}
        authorization, user = row.authorization, row.requested_by
        if (authorization.tenant_id != row.tenant_id or authorization.warehouse.tenant_id != row.tenant_id
                or authorization.provider != 'jifeng_wms' or not user or not user.is_active or user.tenant_id != row.tenant_id
                or not check_user_permission(user, MANAGE)):
            row.last_error_code = 'AFTERSALES_BINDING_OR_PERMISSION_INVALID'
            row.save(update_fields=['last_error_code'])
            return {'status': 'blocked', 'called_provider': False}
        try:
            require_full_scope(user)
        except PermissionDenied:
            row.last_error_code = 'AFTERSALES_SCOPE_CHANGED'
            row.save(update_fields=['last_error_code'])
            return {'status': 'blocked', 'called_provider': False}
        row.running_until = now + timedelta(minutes=15)
        row.last_run_at = now
        row.next_run_at = now + timedelta(minutes=row.interval_minutes)
        row.last_error_code = ''
        row.save()
    queried, received, failed, no_lookup = 0, 0, 0, 0
    blocked = False
    budget_exceeded = False
    started = monotonic()
    try:
        from apps.integrations.readonly_clients import JifengWmsReadonlyClient
        candidates = visible_cases(user, MANAGE).filter(warehouse=authorization.warehouse, requires_return=True).exclude(return_status='received')
        no_lookup = candidates.filter(tracking_no='').count()
        for case in candidates.exclude(tracking_no='').order_by('last_checked_at', 'pk').iterator(chunk_size=100):
            # Do not silently limit an hourly scan to the first few orders.
            # Stop before the worker hard limit and report incomplete coverage.
            if monotonic() - started >= 600:
                budget_exceeded = True
                break
            # Recheck before each external call: permissions or the binding may
            # have been revoked while the previous request was in flight.
            user.refresh_from_db()
            row.refresh_from_db()
            if (not user.is_active or user.tenant_id != row.tenant_id or not check_user_permission(user, MANAGE)
                    or row.authorization_id != authorization.pk or row.requested_by_id != user.pk
                    or scheduled and not row.is_enabled):
                blocked = True
                break
            try:
                require_full_scope(user)
            except PermissionDenied:
                blocked = True
                break
            try:
                authorization.refresh_from_db()
                if authorization.tenant_id != row.tenant_id or authorization.warehouse.tenant_id != row.tenant_id:
                    blocked = True
                    break
                client = JifengWmsReadonlyClient(authorization.integration_config, authorization)
                result = client.fetch_return_detail(tracking_no=case.tracking_no)
                queried += 1
                if result['received_at']:
                    ingest_receipt(user, authorization.warehouse, result, source='api')
                    received += 1
            except Exception:
                # Provider exceptions may contain request data. Persist only a
                # stable classification, not URLs, credentials, or payloads.
                failed += 1
            finally:
                AftersalesCase.objects.filter(pk=case.pk).update(last_checked_at=timezone.now())
    except Exception:
        # Constructor/database failures must not leave a misleading success
        # marker or leak a provider exception into the worker result.
        failed += 1
    finally:
        code = 'AFTERSALES_BINDING_OR_PERMISSION_INVALID' if blocked else 'AFTERSALES_QUERY_FAILED' if failed else 'AFTERSALES_POLL_TIME_BUDGET' if budget_exceeded else 'AFTERSALES_MISSING_RETURN_LOOKUP' if no_lookup else ''
        AftersalesSyncSettings.objects.filter(pk=pk).update(running_until=None, last_error_code=code)
    return {'status': 'blocked' if blocked else 'partial' if failed or no_lookup or budget_exceeded else 'finished' if queried else 'no_targets', 'queried': queried,
            'received_documents': received, 'failed': failed, 'missing_lookup': no_lookup, 'budget_exceeded': budget_exceeded}


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
