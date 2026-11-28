"""Explicit source refreshes; browsing never refreshes business-source records."""
from datetime import datetime, time
from zoneinfo import ZoneInfo
import hashlib
import json
import uuid

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from .summary_models import FinanceSummarySnapshot as Snapshot, FinanceSummaryBuildLease as BuildLease
from .summary_models import FinanceSummaryCalculation as Calculation
from .summary_service import require_access, private_root


def enabled():
    return getattr(settings, 'FINANCE_SUMMARY_SCHEDULED_READS_ENABLED', True)


def daily_times():
    return list(getattr(settings, 'FINANCE_SUMMARY_DAILY_TIMES', ('02:00', '12:30')))


def scope_key(scope):
    return hashlib.sha256(json.dumps(scope, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def register_scope(user, scope):
    require_access(user)
    return Snapshot.objects.get_or_create(tenant=user.tenant, scope_key=scope_key(scope),
        defaults={'scope': scope, 'actor': user})[0]


def request_build(user, scope, *, slot=None):
    from apps.tenants.models import Tenant
    from .summary_jobs import request_calculation
    from .summary_read_query import seed_for, settings_version
    require_access(user)
    # Bound a manual read to a month or a cross-month natural week, never all history.
    first, last = scope['from'][:7], scope['to'][:7]
    year, month = map(int, first.split('-'));end_year, end_month = map(int, last.split('-'))
    if (end_year-year)*12+end_month-month not in (0, 1):
        raise ValidationError('手动汇总请选择具体月份或跨月周，不能一次汇总全部历史。')
    seed = seed_for(user)
    with transaction.atomic():
        Tenant.objects.select_for_update().get(pk=user.tenant_id)
        record = register_scope(user, scope)
        record = Snapshot.objects.select_for_update().select_related('pending_job').get(pk=record.pk)
        if slot and record.scheduled_slot == slot:
            return record.pending_job
        if slot:
            record.scheduled_slot = slot
            record.save(update_fields=['scheduled_slot'])
        if record.pending_job and record.pending_job.status in {'queued', 'running'}:
            from .summary_scopes import check_job_scope
            check_job_scope(record.pending_job, user)
            return record.pending_job
        filters = {'month': first if first == last else '', 'period_type': 'month',
                   '_stores': list(map(str, scope['stores']))}
        spec = {'scope': scope, 'settings': settings_version(user.tenant_id),
                'generation': uuid.uuid4().hex, 'snapshot': True, 'refresh': True}
        job = request_calculation(seed, user, {'action': 'table', 'view': 'store', 'mode': 'operations',
            'scope': 'store', 'page': 1, 'page_size': 100, 'filters': filters,
            '_database_query': spec, '_snapshot_build': record.pk})
        record.actor, record.pending_job = user, job
        record.save(update_fields=['actor', 'pending_job', 'updated_at'])
    return job


def acquire_build(job, token):
    with transaction.atomic():
        BuildLease.objects.get_or_create(key='global')
        lock = BuildLease.objects.select_for_update().select_related('job').get(pk='global')
        if (lock.job_id and lock.expires_at and lock.expires_at > timezone.now()
                and lock.job.status == 'running' and lock.job.lease == lock.token):
            return lock.job_id == job.pk and lock.token == token
        lock.job, lock.token, lock.expires_at = job, token, job.running_until
        lock.save(update_fields=['job', 'token', 'expires_at'])
    return True


def release_build(job_id, token):
    BuildLease.objects.filter(pk='global', job_id=job_id, token=token).update(job=None, token=None, expires_at=None)


def publish(job, info):
    # Called in the calculation's final, lease-checked publication transaction.
    record = Snapshot.objects.select_for_update().get(pk=job.request['_snapshot_build'], tenant_id=job.tenant_id)
    if record.pending_job_id != job.pk:
        raise ValidationError('已有更新的汇总任务，保留原成功版本。')
    from .summary_jobs import QUEUE_META
    job.request = {**job.request, QUEUE_META: {**job.request.get(QUEUE_META, {}), 'source_info': info}}
    record.active_job = job
    record.save(update_fields=['active_job', 'updated_at'])


def source_info(job):
    from .summary_jobs import QUEUE_META
    info = job.request.get(QUEUE_META, {}).get('source_info') or {}
    if info.get('file') != f'scheduled-source-{job.pk}.html.gz':
        raise ValidationError('已汇总来源版本不可用，请手动汇总；未重新读取业务来源。')
    return info


def read_source(user, job_id):
    from .summary_jobs import current_dataset
    from .summary_scopes import check_job_scope
    job = Calculation.objects.select_related('dataset__accounting_state').get(pk=job_id, tenant=user.tenant, status='ready')
    check_job_scope(job, user)
    if not job.request.get('_snapshot_build') or not current_dataset(job):
        raise ValidationError('汇总口径已更新，请手动汇总；未自动重算。')
    return job, source_info(job)


def find_source(user, scope, context=None):
    from .summary_scopes import store_ids
    allowed = set(store_ids(user));wanted = set(scope['stores'])
    if context:
        child = Calculation.objects.filter(pk=context, tenant=user.tenant, status='ready').first()
        if child:
            spec = child.request.get('_database_query', {})
            if spec.get('scope') == scope:
                try:return read_source(user, spec.get('source_job') or child.pk)[0]
                except (ValidationError, Calculation.DoesNotExist):pass
    rows = Snapshot.objects.filter(tenant=user.tenant, active_job__status='ready').select_related(
        'active_job__dataset__accounting_state').order_by('-updated_at')
    for record in rows.iterator(chunk_size=50):
        candidate = record.scope
        if (candidate['from'] <= scope['from'] and candidate['to'] >= scope['to']
                and wanted.issubset(candidate['stores']) and set(candidate['stores']).issubset(allowed)):
            try:return read_source(user, record.active_job_id)[0]
            except ValidationError:continue
    return None


def status_for(user, scope):
    record = Snapshot.objects.filter(tenant=user.tenant, scope_key=scope_key(scope)).select_related('pending_job').first()
    job = record.pending_job if record else None
    return {'status': job.status if job else 'missing', 'job_id': job.pk if job else None,
            'schedule': daily_times(), 'timezone': 'Asia/Shanghai'}


def empty_result(user, payload, scope):
    from apps.masterdata.models import StoreMaster
    stores = list(StoreMaster.objects.filter(tenant=user.tenant, pk__in=scope['stores']).values(
        'id', 'code', 'country_code', 'currency', 'platform__platform_type'))
    options = {'months': [payload['filters'].get('month')] if payload['filters'].get('month') else [],
        'stores': [{'id': str(s['id']), 'code': s['code'], 'country': s['country_code'],
                    'platform': s['platform__platform_type']} for s in stores],
        'countries': {s['country_code']: s['country_code'] for s in stores},
        'platforms': sorted({s['platform__platform_type'] for s in stores}),
        'currencies': sorted({s['currency'] for s in stores})}
    return {'rows': [], 'total': 0, 'page': payload['page'], 'options': options, 'revision': 0,
        'summary_totals': [], 'attribution': {'pending_rows': 0, 'totals': [], 'item_gaps': []},
        'scheduled_summary': True, 'summary_state': status_for(user, scope),
        'summary_completed_at': None, 'source_read_at': None,
        'period_warning': '本期尚未生成可用汇总，请点击“手动汇总”。空表不代表金额为零。'}


def table_response(user, payload, *, refresh=False, context=None):
    from .summary_read_query import query_scope
    from .summary_jobs import request_calculation, job_data
    scope = query_scope(user, payload['filters'])
    if refresh:
        return job_data(request_build(user, scope), user)
    parent = find_source(user, scope, context)
    if parent is None:
        return {'pending': False, 'result': empty_result(user, payload, scope)}
    # The common store table is already calculated, including its compositions.
    filters = payload['filters']
    if (payload['view'] == 'store' and payload['mode'] == 'operations'
            and scope == parent.request['_database_query']['scope']
            and not any(v for k,v in filters.items() if k not in {'month', 'period_type', '_stores', 'attribution'})
            and filters.get('period_type', 'month') == 'month'):
        data = job_data(parent, user)['result']
        if data is not None and len(data['rows']) == data['total']:
            page, size = payload['page'], payload['page_size']
            data = {**data, 'rows': data['rows'][(page-1)*size:page*size], 'page': page,
                    'summary_state': status_for(user, parent.request['_database_query']['scope'])}
            return {'pending': False, 'result': data}
    spec = {**parent.request['_database_query'], 'scope': scope, 'source_job': parent.pk}
    row = request_calculation(parent.dataset, user, {**payload,
        'filters': {**filters, '_stores': list(map(str, scope['stores']))}, '_database_query': spec})
    reply = job_data(row, user)
    if reply['result'] is not None:reply['result']['summary_state'] = status_for(user, parent.request['_database_query']['scope'])
    return reply


@shared_task
def dispatch_due_summaries():
    if not enabled():return {'queued': 0}
    from apps.accounts.models import CustomUser
    from .summary_read_query import query_scope
    now = timezone.localtime(timezone.now(), ZoneInfo('Asia/Shanghai'))
    due = [time.fromisoformat(value) for value in daily_times() if time.fromisoformat(value) <= now.time().replace(tzinfo=None)]
    if not due:return {'queued': 0}
    slot = datetime.combine(now.date(), max(due)).isoformat(timespec='minutes')
    actors = Snapshot.objects.order_by().values_list('actor_id', flat=True).union(
        Calculation.objects.filter(kind='query', status='ready', request__has_key='_database_query')
        .order_by().values_list('actor_id', flat=True))
    count = 0
    for user in CustomUser.objects.filter(pk__in=actors, is_active=True, user_type='internal').iterator(chunk_size=50):
        try:
            scope = query_scope(user, {'month': now.strftime('%Y-%m')})
            job = request_build(user, scope, slot=slot)
            count += bool(job and job.status in {'queued', 'running'})
        except (PermissionDenied, ValidationError):continue
    return {'queued': count}
