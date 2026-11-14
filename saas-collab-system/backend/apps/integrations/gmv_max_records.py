"""Stored GMV Max audit evidence, not fabricated scheduler execution history."""
from datetime import datetime, time, timedelta, timezone

from django.db.models import Q

from .ads_capability_api import visible_mappings
from .ads_subject import mapping_allowed
from .gmv_max_sync import REPORT_PATH
from .models import IntegrationAuditLog, SharedAdvertisingRawPayload


def audit_row(audit, mapping):
    detail = audit.masked_detail
    saved = audit.result == 'success' and detail.get('committed') is True
    evidence = {key: detail.get(key) for key in (
        'date', 'advertiser_id', 'platform_store_id', 'currency', 'timezone',
        'raw_payload_id', 'committed', 'created', 'error_code', 'error_type') if key in detail}
    return dict(id=f'gmv-max-{audit.pk}', run_id=f'gmv-max-{audit.pk}',
        record_source='gmv_max', resource_type='gmv_max_report', platform='tiktok',
        subject_key=f'store:{mapping.store_id}', subject_name=f'{mapping.store.code} {mapping.store.name}',
        status=audit.result, sync_job_id=None, started_at=None, finished_at=None,
        evidence_at=audit.created_at, execution_mode='evidence',
        stored_count=1 if saved else None, fetched_count=None, created_count=None,
        updated_count=None, failed_count=None, evidence=evidence,
        evidence_note=f"GMV Max · {detail.get('date', '日期未记录')} · 广告户 {mapping.advertiser_id}；"
            + ('已保存/复用1份日快照，不是订单或计划条数。' if saved else '本次采集失败，不能据此判定历史数据缺失。')
            + ' 独立采集审计，未记录系统任务ID或调度状态。')


def gmv_max_records(user, params):
    mappings = [m for m in visible_mappings(user) if mapping_allowed(user, m, 'integrations.view')]
    by_id = {m.pk: m for m in mappings}
    scope = Q(pk__in=[])
    for m in mappings:
        # A rebind must not re-label a previous store's successful observations.
        raw_ids = SharedAdvertisingRawPayload.objects.filter(tenant_id=user.tenant_id,
            store_id=m.store_id, platform='tiktok', endpoint=REPORT_PATH,
            payload__schema='gmv-max-day-v1', payload__advertiser_id=m.advertiser_id).values('pk')
        scope |= (Q(integration_config_id=m.integration_config_id,
            masked_detail__mapping_id=m.pk, masked_detail__advertiser_id=m.advertiser_id)
            & (Q(result='failed', masked_detail__store_id=m.store_id)
               | Q(result='success', masked_detail__committed=True,
                   masked_detail__raw_payload_id__in=raw_ids)))
    qs = IntegrationAuditLog.objects.filter(scope, tenant_id=user.tenant_id, action='ads_gmv_max_day')
    if params.get('platform') not in (None, '', 'tiktok') or params.get('resource_type') not in (None, '', 'gmv_max_report'):
        qs = qs.none()
    if params.get('sync_job_id') or params.get('trigger_type') or params.get('run_pk'):
        qs = qs.none()
    if params.get('subject_key'):
        selected = [m.pk for m in mappings if params['subject_key'] == f'store:{m.store_id}']
        qs = qs.filter(masked_detail__mapping_id__in=selected)
    if params.get('status'):
        qs = qs.filter(result=params['status'])
    if params.get('run_id'):
        identity = str(params['run_id']).removeprefix('gmv-max-')
        qs = qs.filter(pk=int(identity)) if identity.isdigit() else qs.none()
    for key, lookup, offset in [('started_from', 'gte', 0), ('started_to', 'lt', 1)]:
        if params.get(key):
            day = datetime.strptime(params[key], '%Y-%m-%d').date() + timedelta(days=offset)
            qs = qs.filter(**{f'created_at__{lookup}': datetime.combine(day, time.min, timezone.utc)})
    size = min(100, max(1, int(params.get('page_size', 50))))
    total = qs.count()
    pages = max(1, (total + size - 1) // size)
    page = min(pages, max(1, int(params.get('page', 1))))
    rows = list(qs.order_by('-created_at', '-pk')[(page-1)*size:page*size])
    subjects = {m.store_id: {'value': f'store:{m.store_id}', 'label': f'{m.store.code} {m.store.name}'} for m in mappings}
    return {'results': [audit_row(a, by_id[a.masked_detail['mapping_id']]) for a in rows],
        'pagination': {'page': page, 'page_size': size, 'total': total, 'page_count': pages},
        'options': {'platforms': ['tiktok'], 'resource_types': ['gmv_max_report'],
            'statuses': ['success', 'failed'], 'subjects': list(subjects.values())}}
