"""Persistent derived results. Celery performs calculations, never provider reads."""
from datetime import timedelta
from functools import lru_cache
import gzip
import hashlib
import json
import logging
import re
from pathlib import Path
import uuid

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import PermissionDenied, ValidationError

from .summary_models import FinanceSummaryCalculation, FinanceSummaryDataset
from .summary_service import require_access, document_path, metadata

QUEUE = getattr(settings, 'FINANCE_SUMMARY_QUEUE', 'finance-summary')
QUEUE_META = '_summary_queue'
logger = logging.getLogger(__name__)


def logical_payload(payload):
    return {key: value for key, value in payload.items() if key != QUEUE_META}


def deadline(payload, key):
    value = payload.get(QUEUE_META, {}).get(key)
    try:
        parsed = parse_datetime(value) if isinstance(value, str) else None
    except ValueError:
        return None
    return parsed if parsed and timezone.is_aware(parsed) else None


def queue_status(status, payload, error_code=''):
    due = deadline(payload, 'not_before')
    return {'phase': ('retrying' if error_code=='CALCULATOR_BUSY' else 'merging') if status == 'queued' and due and due > timezone.now() else status,
            'not_before': due}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


@lru_cache(maxsize=4)
def rules_fingerprint(stamps):
    return hashlib.sha256(b''.join(Path(name).read_bytes() for name, *_ in stamps)).hexdigest()


def calculation_key(dataset, kind, payload):
    path = document_path(dataset)
    stamp = path.stat()
    code = Path(__file__).parent
    files = [code / name for name in (
        'summary_native.py', 'summary_native.cjs', 'summary_flow_view.cjs', 'summary_engine.cjs', 'summary_participation.js', 'summary_accounting_rules.json', 'summary_runtime.js', 'summary_composition.js',
        'summary_periods.cjs', 'summary_allocation.cjs', 'summary_order_ledger.cjs',
        'summary_cost_detail.cjs', 'summary_database.py', 'summary_database_document.py', 'summary_read_query.py', 'summary_source_worker.py', 'summary_cost_classification.py',
        'summary_composition.py', 'summary_shipped_items.py', 'summary_raw_flows.py', 'summary_return_costs.py', 'summary_recent.py', 'summary_rebuild.py', 'summary_service.py', 'summary_worker.cjs', 'summary_schedule.py')] + [code.parent / 'masterdata' / 'monthly_exchange_rates.py']
    stamps = []
    for file in files:
        stat = file.stat()
        stamps.append((str(file), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size))
    rules = rules_fingerprint(tuple(stamps))
    state = dataset.accounting_state
    return hashlib.sha256(encoded([dataset.tenant_id, dataset.pk, dataset.source_hash,
        state.revision, state.values, stamp.st_mtime_ns, stamp.st_size, rules, kind, logical_payload(payload)])).hexdigest()


def enqueue(row):
    now = timezone.now()
    with transaction.atomic():
        locked = FinanceSummaryCalculation.objects.select_for_update().filter(pk=row.pk, status='queued').first()
        if not locked or any(due and due > now for due in (
                deadline(locked.request, 'not_before'), deadline(locked.request, 'dispatch_after'))):
            return
        request = dict(locked.request)
        request[QUEUE_META] = {**request.get(QUEUE_META, {}),
                               'dispatch_after': (now + timedelta(seconds=60)).isoformat()}
        locked.request, locked.error_code = request, ''
        locked.save(update_fields=['request', 'error_code'])
    try:
        query_queue = getattr(settings, 'FINANCE_SUMMARY_QUEUE', QUEUE)
        queue = getattr(settings, 'FINANCE_SUMMARY_REBUILD_QUEUE', query_queue) if locked.kind == 'rebuild' else query_queue
        run_calculation.apply_async(args=[row.pk], queue=queue, retry=False)
    except Exception:
        FinanceSummaryCalculation.objects.filter(pk=row.pk, status='queued').update(error_code='BROKER_UNAVAILABLE')


def request_calculation(dataset, user, payload, *, kind='query', debounce_seconds=0):
    require_access(user, write=kind == 'rebuild')
    key = calculation_key(dataset, kind, payload)
    with transaction.atomic():
        row, created = FinanceSummaryCalculation.objects.select_for_update().get_or_create(cache_key=key,
            defaults={'tenant': user.tenant, 'dataset': dataset, 'actor': user, 'kind': kind,
                      'revision': dataset.accounting_state.revision, 'request': logical_payload(payload)})
        if kind=='query':
            from .summary_scopes import check_job_scope
            check_job_scope(row,user)
            if row.status=='queued' and row.actor_id!=user.pk:
                previous=row.actor
                try:
                    if not previous.is_active or previous.user_type!='internal' or previous.tenant_id!=row.tenant_id:
                        raise PermissionDenied()
                    require_access(previous)
                    check_job_scope(row,previous)
                except PermissionDenied:
                    row.actor=user
                    row.save(update_fields=['actor'])
        if row.status in {'failed', 'blocked', 'superseded', 'expired'} or row.status == 'queued' and row.error_code == 'BROKER_UNAVAILABLE':
            row.status, row.error_code, row.actor = 'queued', '', user
            row.lease, row.running_until = None, None
            row.finished_at, row.result, row.result_hash = None, None, ''
            row.request = logical_payload(row.request)
            row.save(update_fields=['status', 'error_code', 'actor', 'lease', 'running_until',
                                    'finished_at', 'result', 'result_hash', 'request'])
            created = True
        if created:
            if debounce_seconds:
                row.request = {**row.request, QUEUE_META: {
                    'not_before': (timezone.now() + timedelta(seconds=debounce_seconds)).isoformat()}}
                row.save(update_fields=['request'])
            transaction.on_commit(lambda: enqueue(row))
    return row


def current_dataset(row):
    bootstrap = row.kind == 'rebuild' and row.request.get('bootstrap') is True
    direct = row.kind == 'query' and '_database_query' in row.request
    dataset = FinanceSummaryDataset.objects.select_related('accounting_state').filter(
        pk=row.dataset_id, tenant_id=row.tenant_id, active=not (bootstrap or direct)).first()
    if direct:
        from .summary_read_query import settings_version
        spec = row.request['_database_query']
        interval = 60 if spec.get('refresh') else 300
        source_expired = not spec.get('snapshot') and (timezone.now().timestamp()-spec['generation']*interval > 3600+interval or row.created_at < timezone.now()-timedelta(hours=1))
        if source_expired or not dataset or not dataset.metadata.get('query_template') or spec['settings'] != settings_version(row.tenant_id):
            return None
    if bootstrap and dataset and not dataset.metadata.get('bootstrap_template'):
        return None
    if not dataset or dataset.accounting_state.revision != row.revision:
        return None
    return dataset if calculation_key(dataset, row.kind, row.request) == row.cache_key else None


def job_data(row, user):
    require_access(user)
    if row.tenant_id != user.tenant_id:
        raise PermissionDenied('财务计算任务不属于当前租户。')
    from .summary_scopes import check_job_scope
    check_job_scope(row,user)
    if row.status == 'ready' and row.kind == 'rebuild':
        dataset = FinanceSummaryDataset.objects.select_related('accounting_state').filter(
            pk=row.result_dataset_id, tenant=user.tenant, active=not row.request.get('bootstrap', False)).first()
        if not dataset:
            return {'pending': False, 'job': {'id': row.pk, 'status': 'superseded', 'error_code': 'VERSION_CHANGED'}}
        result = metadata(dataset, user, include_values=False, checkpoint=False)
        result['candidate'] = bool(row.request.get('bootstrap'))
    elif row.status == 'ready':
        if not current_dataset(row):
            return {'pending': False, 'job': {'id': row.pk, 'status': 'superseded', 'error_code': 'VERSION_CHANGED'}}
        try:
            raw = gzip.decompress(bytes(row.result))
            if hashlib.sha256(raw).hexdigest() != row.result_hash:
                raise ValueError()
            result = json.loads(raw)
            if row.request.get('_snapshot_build'):
                result['summary_completed_at'] = row.finished_at.isoformat()
        except (ValueError, TypeError, OSError):
            FinanceSummaryCalculation.objects.filter(pk=row.pk).update(status='failed', error_code='RESULT_INTEGRITY_FAILED')
            raise ValidationError('财务计算结果校验失败，请重新查询；未使用损坏结果。') from None
    else:
        result = None
    return {'pending': row.status in {'queued', 'running'},
        'job': {'id': row.pk, 'status': row.status, 'error_code': row.error_code,
                'created_at': row.created_at, 'finished_at': row.finished_at,
                **queue_status(row.status, row.request, row.error_code)}, 'result': result}


@shared_task(soft_time_limit=840, time_limit=900, acks_late=True, reject_on_worker_lost=True)
def run_calculation(pk):
    from .summary_native import CalculationBusy, CalculationTimeout
    from .summary_read_query import SourceReadTimeout
    now, lease = timezone.now(), uuid.uuid4()
    with transaction.atomic():
        row = FinanceSummaryCalculation.objects.select_for_update().select_related('actor').get(pk=pk)
        if row.status not in {'queued', 'running'} or row.running_until and row.running_until > now:
            return {'status': 'not_claimed'}
        if row.status == 'queued' and (due := deadline(row.request, 'not_before')) and due > now:
            return {'status': 'deferred'}
        row.status, row.lease, row.running_until = 'running', lease, now + timedelta(minutes=15)
        row.error_code = ''
        row.save(update_fields=['status', 'lease', 'running_until', 'error_code'])
    status, error, result, result_dataset = 'ready', '', None, None
    snapshot_build = bool(row.request.get('_snapshot_build'))
    source_info = None
    try:
        if snapshot_build:
            from .summary_schedule import acquire_build
            if not acquire_build(row, lease):raise CalculationBusy()
        user = row.actor
        if not user.is_active or user.user_type != 'internal' or user.tenant_id != row.tenant_id:
            raise PermissionDenied()
        require_access(user, write=row.kind == 'rebuild')
        from .summary_scopes import check_job_scope
        check_job_scope(row,user)
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
            if row.request.get('bootstrap'):
                options['bootstrap'] = True
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
            if '_database_query' in row.request:
                from .summary_read_query import execute
                if snapshot_build:
                    result = execute(dataset, user, logical_payload(row.request), snapshot_job_id=row.pk)
                    source_info = result.pop('_prepared_source_info')
                else:
                    result = execute(dataset, user, logical_payload(row.request))
                result['query_context'] = row.pk
            else:
                result = query(dataset, logical_payload(row.request))
            result.update(dataset=dataset.pk, revision=row.revision)
        with transaction.atomic():
            locked = FinanceSummaryCalculation.objects.select_for_update().get(pk=pk)
            if locked.lease != lease or not locked.running_until or locked.running_until <= timezone.now():
                return {'status': 'lease_lost'}
            user.refresh_from_db()
            if not user.is_active or user.user_type != 'internal' or user.tenant_id != row.tenant_id:
                raise PermissionDenied()
            require_access(user, write=row.kind == 'rebuild')
            check_job_scope(row,user)
            if row.kind == 'query' and not current_dataset(row):
                status, error, result = 'superseded', 'VERSION_CHANGED', None
            if result is not None and status == 'ready':
                if snapshot_build:
                    from .summary_schedule import publish
                    publish(locked, source_info)
                raw = encoded(result)
                locked.result, locked.result_hash = gzip.compress(raw), hashlib.sha256(raw).hexdigest()
                locked.result_dataset = result_dataset
            locked.status, locked.error_code = status, error
            locked.finished_at, locked.lease, locked.running_until = timezone.now(), None, None
            locked.save()
    except PermissionDenied:
        status, error = 'blocked', 'PERMISSION_CHANGED'
    except CalculationBusy:
        status, error = 'queued', 'CALCULATOR_BUSY'
    except CalculationTimeout:
        status, error = 'failed', 'CALCULATOR_TIMEOUT'
    except SourceReadTimeout:
        status, error = 'failed', 'SOURCE_READ_TIMEOUT'
    except Exception:
        # Provider exceptions and raw inputs must never enter task logs/results.
        status, error = 'failed', 'CALCULATION_FAILED'
    finally:
        if snapshot_build:
            from .summary_schedule import release_build
            release_build(row.pk, lease)
    if error:
        fields = {}
        if error=='CALCULATOR_BUSY':
            request=dict(row.request)
            request[QUEUE_META]={**request.get(QUEUE_META,{}),'not_before':(timezone.now()+timedelta(seconds=30)).isoformat()}
            fields['request']=request
        FinanceSummaryCalculation.objects.filter(pk=pk, lease=lease).update(
            status=status, error_code=error, finished_at=None if status=='queued' else timezone.now(), lease=None, running_until=None, **fields)
    if status == 'superseded' and row.kind == 'rebuild' and 'automatic_scope' in row.request:
        cache.delete(f'finance-summary-check:{row.dataset_id}')
    return {'status': status}


@shared_task
def dispatch_calculations():
    from .summary_maintenance import schedule_changed_summaries
    now = timezone.now()
    FinanceSummaryCalculation.objects.filter(status='running', running_until__lte=now).update(
        status='queued', lease=None, running_until=None, error_code='LEASE_EXPIRED')
    dispatched = 0
    queued = FinanceSummaryCalculation.objects.filter(status='queued').only('pk', 'request').order_by('pk')
    for row in queued.iterator(chunk_size=100):
        if any(due and due > now for due in (
                deadline(row.request, 'not_before'), deadline(row.request, 'dispatch_after'))):
            continue
        enqueue(row)
        dispatched += 1
        if dispatched >= 100:
            break
    try:
        from .summary_schedule import enabled, dispatch_due_summaries
        if enabled():dispatch_due_summaries()
        else:schedule_changed_summaries()
    except Exception:
        logger.error('Finance dispatch stage failed: automatic_check')
    try:
        if cache.add('finance-summary-prune-derived',True,300):
            prune_expired_results(now)
    except Exception:
        logger.error('Finance dispatch stage failed: cache_cleanup')


def prune_expired_results(now=None):
    """Expire only obsolete query blobs; preserve task, rebuild and audit history."""
    from django.db.models import F, Q
    from django.db.models.functions import Length
    from .summary_documents import prune_settings_fragments
    from .summary_service import private_root
    now=now or timezone.now()
    expired = Q(finished_at__lt=now-timedelta(days=30)) | Q(request__has_key='_database_query', finished_at__lt=now-timedelta(hours=1))
    obsolete=FinanceSummaryCalculation.objects.filter(expired, kind='query',
        status__in=['ready','failed','blocked','superseded'],result__isnull=False
        ).exclude(dataset__active=True,revision=F('dataset__accounting_state__revision'))
    from .summary_models import FinanceSummarySnapshot
    protected = FinanceSummarySnapshot.objects.filter(active_job__isnull=False).values_list('active_job_id', flat=True)
    obsolete = obsolete.exclude(pk__in=protected).exclude(Q(request___database_query__has_key='snapshot') &
        Q(request___database_query__snapshot=True, finished_at__gte=now-timedelta(days=30)))
    selected=list(obsolete.order_by('pk').annotate(blob_bytes=Length('result')).values_list('pk','blob_bytes')[:500])
    ids=[pk for pk,_ in selected]
    cleared=FinanceSummaryCalculation.objects.filter(expired, pk__in=ids,kind='query',
        status__in=['ready','failed','blocked','superseded'],result__isnull=False
        ).update(status='expired',error_code='CACHE_EXPIRED',result=None) if ids else 0
    prune_settings_fragments(private_root()/'settings-documents-v1',(now-timedelta(days=30)).timestamp())
    # Direct-query documents are disposable evidence caches, never accepted batches.
    cutoff = (now-timedelta(hours=2)).timestamp()
    for path in private_root().glob('read-query-*'):
        if re.fullmatch(r'read-query-[a-f0-9]{64}\.html\.(gz|json)', path.name) and path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)
    # Keep every successful head; remove only retired source versions after 30 days.
    retired = FinanceSummaryCalculation.objects.filter(kind='query',
        status__in=['expired','failed','blocked','superseded'],finished_at__lt=now-timedelta(days=30)).exclude(pk__in=protected)
    for path in private_root().glob('scheduled-source-*.html.gz'):
        match = re.fullmatch(r'scheduled-source-(\d+)\.html\.gz',path.name)
        if (match and path.is_file() and path.stat().st_mtime < (now-timedelta(days=30)).timestamp()
                and retired.filter(pk=int(match[1])).exists()):
            path.unlink(missing_ok=True)
    if selected:
        logger.info('Finance derived cache cleanup: expired_query_rows=%s selected_query_bytes=%s',cleared,sum(size or 0 for _,size in selected))
    return cleared
