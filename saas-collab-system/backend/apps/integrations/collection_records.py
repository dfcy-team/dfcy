"""Read-only collection evidence, never synthesized SyncRun history."""
from datetime import datetime, time, timedelta, timezone

from apps.permissions.ui_p6_scopes import filter_store_authorizations
from .models import MarketplaceStoreAuthorization


def collection_records(user, params):
    if params.get('record_source') == 'gmv_max':
        from .gmv_max_records import gmv_max_records
        return gmv_max_records(user, params)
    from apps.influencers.models import TikTokCreatorProfileSnapshot, TikTokVideoSyncBatch

    video = params.get('record_source') == 'video'
    auths = MarketplaceStoreAuthorization.objects.filter(tenant_id=user.tenant_id)
    for permission in ('integrations.view', 'integrations.store.view'):
        auths = filter_store_authorizations(user, auths, permission)
    store_ids = auths.values('store_id')
    model = TikTokVideoSyncBatch if video else TikTokCreatorProfileSnapshot
    field = 'updated_at' if video else 'fetched_at'
    status_field = 'status' if video else 'identity_status'
    base = model.objects.filter(tenant_id=user.tenant_id, store_id__in=store_ids)
    subjects = list(base.order_by().values('store_id', 'store__code', 'store__name').distinct())
    statuses = list(base.order_by().values_list(status_field, flat=True).distinct())
    qs = base
    resource = 'video_metrics' if video else 'creator_profile'
    if params.get('platform') not in (None, '', 'tiktok') or params.get('resource_type') not in (None, '', resource):
        qs = qs.none()
    # Evidence has no trustworthy scheduler/SyncJob identity.
    if params.get('sync_job_id') or params.get('trigger_type') or params.get('run_pk'):
        qs = qs.none()
    subject = params.get('subject_key')
    if subject:
        if str(subject).startswith('store:') and str(subject)[6:].isdigit():
            qs = qs.filter(store_id=int(str(subject)[6:]))
        else:
            qs = qs.none()
    if params.get('status'):
        qs = qs.filter(**{status_field: params['status']})
    prefix = 'video-' if video else 'creator-'
    if params.get('run_id'):
        identity = str(params['run_id']).removeprefix(prefix)
        qs = qs.filter(pk=int(identity)) if identity.isdigit() else qs.none()
    for key, lookup, offset in [('started_from', 'gte', 0), ('started_to', 'lt', 1)]:
        if params.get(key):
            day = datetime.strptime(params[key], '%Y-%m-%d').date() + timedelta(days=offset)
            qs = qs.filter(**{f'{field}__{lookup}': datetime.combine(day, time.min, timezone.utc)})
    size = min(100, max(1, int(params.get('page_size', 50))))
    total = qs.count()
    pages = max(1, (total + size - 1) // size)
    page = min(pages, max(1, int(params.get('page', 1))))
    results = []
    for obj in qs.select_related('store').order_by('-' + field, '-pk')[(page-1)*size:page*size]:
        evidence = ({'window_start': obj.window_start, 'window_end_exclusive': obj.window_end,
                     'video_count': obj.video_count if obj.status == 'completed' else None,
                     'detail_succeeded_count': obj.detail_succeeded_count,
                     'detail_failed_count': obj.detail_failed_count,
                     'next_retry_at': obj.next_retry_at, 'attempt_count': obj.attempt_count}
                    if video else {'identity_status': obj.identity_status})
        note = ('视频批次记录；不是系统 SyncRun，新增/更新条数未记录。'
                if video else '最新已保存快照；不是历史运行次数，身份匹配状态单独核对。')
        results.append(dict(id=prefix+str(obj.pk), run_id=prefix+str(obj.pk),
            record_source='video' if video else 'creator', sync_job_id=None,
            platform='tiktok', resource_type=resource, subject_key=f'store:{obj.store_id}',
            subject_name=f'{obj.store.code} {obj.store.name}', status=getattr(obj, status_field),
            started_at=obj.started_at if video else None,
            finished_at=obj.completed_at if video else None, evidence_at=getattr(obj, field),
            stored_count=(obj.video_count if obj.status == 'completed' else None) if video else 1,
            evidence_note=note, evidence=evidence, execution_mode='evidence',
            fetched_count=None, created_count=None, updated_count=None, failed_count=None))
    return {'results': results, 'pagination': {'page': page, 'page_size': size, 'total': total, 'page_count': pages},
            'options': {'platforms': ['tiktok'], 'resource_types': [resource], 'statuses': statuses,
                        'subjects': [{'value': f"store:{s['store_id']}", 'label': f"{s['store__code']} {s['store__name']}"} for s in subjects]}}
