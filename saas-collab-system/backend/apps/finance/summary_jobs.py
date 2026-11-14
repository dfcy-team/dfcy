"""Persistent derived results. Celery performs calculations, never provider reads."""
from datetime import timedelta
import gzip
import hashlib
import json
from pathlib import Path
import uuid

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from .summary_models import FinanceSummaryCalculation, FinanceSummaryDataset
from .summary_service import require_access, document_path, metadata

QUEUE = 'finance-summary'


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def calculation_key(dataset, kind, payload):
    path = document_path(dataset)
    stamp = path.stat()
    code = Path(__file__).parent
    rules = hashlib.sha256(b''.join((code / name).read_bytes() for name in (
        'summary_native.cjs', 'summary_engine.cjs', 'summary_runtime.js', 'summary_composition.js',
        'summary_periods.cjs', 'summary_allocation.cjs', 'summary_order_ledger.cjs',
        'summary_cost_detail.cjs', 'summary_database.py', 'summary_database_document.py',
        'summary_composition.py', 'summary_shipped_items.py', 'summary_raw_flows.py', 'summary_return_costs.py', 'summary_recent.py', 'summary_rebuild.py', 'summary_service.py', 'summary_worker.cjs')) +
        (code.parent / 'masterdata' / 'monthly_exchange_rates.py').read_bytes()).hexdigest()
    state = dataset.accounting_state
    return hashlib.sha256(encoded([dataset.tenant_id, dataset.pk, dataset.source_hash,
        state.revision, state.values, stamp.st_mtime_ns, stamp.st_size, rules, kind, payload])).hexdigest()


def enqueue(row):
    try:
        queue = getattr(settings, 'FINANCE_SUMMARY_REBUILD_QUEUE', QUEUE) if row.kind == 'rebuild' else QUEUE
        run_calculation.apply_async(args=[row.pk], queue=queue, retry=False)
    except Exception:
        FinanceSummaryCalculation.objects.filter(pk=row.pk, status='queued').update(error_code='BROKER_UNAVAILABLE')


def request_calculation(dataset, user, payload, *, kind='query'):
    require_access(user, write=kind == 'rebuild')
    key = calculation_key(dataset, kind, payload)
    with transaction.atomic():
        row, created = FinanceSummaryCalculation.objects.select_for_update().get_or_create(cache_key=key,
            defaults={'tenant': user.tenant, 'dataset': dataset, 'actor': user, 'kind': kind,
                      'revision': dataset.accounting_state.revision, 'request': payload})
        if row.status in {'failed', 'blocked', 'superseded'}:
            row.status, row.error_code, row.actor = 'queued', '', user
            row.lease, row.running_until = None, None
            row.finished_at, row.result, row.result_hash = None, None, ''
            row.save(update_fields=['status', 'error_code', 'actor', 'lease', 'running_until',
                                    'finished_at', 'result', 'result_hash'])
            created = True
        if created:
            transaction.on_commit(lambda: enqueue(row))
    return row


def current_dataset(row):
    dataset = FinanceSummaryDataset.objects.select_related('accounting_state').filter(
        pk=row.dataset_id, tenant_id=row.tenant_id, active=True).first()
    if not dataset or dataset.accounting_state.revision != row.revision:
        return None
    return dataset if calculation_key(dataset, row.kind, row.request) == row.cache_key else None


def job_data(row, user):
    require_access(user)
    if row.tenant_id != user.tenant_id:
        raise PermissionDenied('财务计算任务不属于当前租户。')
    if row.status == 'ready' and row.kind == 'rebuild':
        dataset = FinanceSummaryDataset.objects.select_related('accounting_state').filter(
            pk=row.result_dataset_id, tenant=user.tenant, active=True).first()
        if not dataset:
            return {'pending': False, 'job': {'id': row.pk, 'status': 'superseded', 'error_code': 'VERSION_CHANGED'}}
        result = metadata(dataset, user, include_values=False)
    elif row.status == 'ready':
        if not current_dataset(row):
            return {'pending': False, 'job': {'id': row.pk, 'status': 'superseded', 'error_code': 'VERSION_CHANGED'}}
        try:
            raw = gzip.decompress(bytes(row.result))
            if hashlib.sha256(raw).hexdigest() != row.result_hash:
                raise ValueError()
            result = json.loads(raw)
        except (ValueError, TypeError, OSError):
            FinanceSummaryCalculation.objects.filter(pk=row.pk).update(status='failed', error_code='RESULT_INTEGRITY_FAILED')
            raise ValidationError('财务计算结果校验失败，请重新查询；未使用损坏结果。') from None
    else:
        result = None
    return {'pending': row.status in {'queued', 'running'},
        'job': {'id': row.pk, 'status': row.status, 'error_code': row.error_code,
                'created_at': row.created_at, 'finished_at': row.finished_at}, 'result': result}


@shared_task(soft_time_limit=840, time_limit=900, acks_late=True, reject_on_worker_lost=True)
def run_calculation(pk):
    now, lease = timezone.now(), uuid.uuid4()
    with transaction.atomic():
        row = FinanceSummaryCalculation.objects.select_for_update().select_related('actor').get(pk=pk)
        if row.status not in {'queued', 'running'} or row.running_until and row.running_until > now:
            return {'status': 'not_claimed'}
        row.status, row.lease, row.running_until = 'running', lease, now + timedelta(minutes=15)
        row.error_code = ''
        row.save(update_fields=['status', 'lease', 'running_until', 'error_code'])
    status, error, result, result_dataset = 'ready', '', None, None
    try:
        user = row.actor
        if not user.is_active or user.user_type != 'internal' or user.tenant_id != row.tenant_id:
            raise PermissionDenied()
        require_access(user, write=row.kind == 'rebuild')
        dataset = current_dataset(row)
        if not dataset:
            status, error = 'superseded', 'VERSION_CHANGED'
        elif row.kind == 'rebuild':
            from .summary_rebuild import rebuild
            def publication_guard():
                locked = FinanceSummaryCalculation.objects.select_for_update().get(pk=pk)
                if locked.lease != lease or not locked.running_until or locked.running_until <= timezone.now():
                    raise ValidationError('计算任务已失去执行资格，原批次保持有效。')
                if not current_dataset(row):
                    raise ValidationError('计算版本已变化，原批次保持有效。')
            options = {'publication_guard': publication_guard}
            if 'scope' in row.request:
                options['scope_override'] = row.request['scope']
            if 'automatic_scope' in row.request:
                options['automatic_scope'] = row.request['automatic_scope']
            result_dataset = rebuild(dataset, user, row.revision, **options)
            if result_dataset is None:
                status, error = 'superseded', 'VERSION_CHANGED'
            else:
                result = {'dataset': result_dataset.pk}
        else:
            from .summary_native import query
            result = query(dataset, dict(row.request))
            result.update(dataset=dataset.pk, revision=row.revision)
        with transaction.atomic():
            locked = FinanceSummaryCalculation.objects.select_for_update().get(pk=pk)
            if locked.lease != lease or not locked.running_until or locked.running_until <= timezone.now():
                return {'status': 'lease_lost'}
            user.refresh_from_db()
            if not user.is_active or user.user_type != 'internal' or user.tenant_id != row.tenant_id:
                raise PermissionDenied()
            require_access(user, write=row.kind == 'rebuild')
            if row.kind == 'query' and not current_dataset(row):
                status, error, result = 'superseded', 'VERSION_CHANGED', None
            if result is not None and status == 'ready':
                raw = encoded(result)
                locked.result, locked.result_hash = gzip.compress(raw), hashlib.sha256(raw).hexdigest()
                locked.result_dataset = result_dataset
            locked.status, locked.error_code = status, error
            locked.finished_at, locked.lease, locked.running_until = timezone.now(), None, None
            locked.save()
    except PermissionDenied:
        status, error = 'blocked', 'PERMISSION_CHANGED'
    except Exception:
        # Provider exceptions and raw inputs must never enter task logs/results.
        status, error = 'failed', 'CALCULATION_FAILED'
    if error:
        FinanceSummaryCalculation.objects.filter(pk=pk, lease=lease).update(
            status=status, error_code=error, finished_at=timezone.now(), lease=None, running_until=None)
    return {'status': status}


@shared_task
def dispatch_calculations():
    from .summary_maintenance import schedule_changed_summaries
    schedule_changed_summaries()
    now = timezone.now()
    FinanceSummaryCalculation.objects.filter(status='running', running_until__lte=now).update(
        status='queued', lease=None, running_until=None, error_code='LEASE_EXPIRED')
    for row in FinanceSummaryCalculation.objects.filter(status='queued').order_by('pk')[:100]:
        enqueue(row)
