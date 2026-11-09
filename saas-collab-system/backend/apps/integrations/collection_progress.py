"""Store-scoped observation only; never infer scheduler state from data rows."""
from django.db.models import Count, Max, Q


def store_collection_progress(*, tenant_id, store_id, platform, can_view):
    if str(platform).lower() != 'tiktok':
        return []
    rows = [dict(code=code, label=label, visibility='allowed' if can_view else 'restricted',
                 scheduler_status='unknown', last_at=None, stored_count=None,
                 verified_count=None, latest_status='unknown', recent_batches=[])
            for code, label in [('CREATOR', '达人采集'), ('VIDEO', '视频采集')]]
    if not can_view:
        return rows
    from apps.influencers.models import TikTokCreatorProfileSnapshot, TikTokVideoSyncBatch
    snapshots = TikTokCreatorProfileSnapshot.objects.filter(tenant_id=tenant_id, store_id=store_id)
    stats = snapshots.aggregate(total=Count('pk'), matched=Count('pk', filter=Q(identity_status='matched')),
                                last=Max('fetched_at'))
    rows[0].update(stored_count=stats['total'], verified_count=stats['matched'],
                   last_at=stats['last'], latest_status='has_snapshots' if stats['total'] else 'no_records')
    batches = list(TikTokVideoSyncBatch.objects.filter(tenant_id=tenant_id, store_id=store_id)
                   .order_by('-updated_at', '-id').values('id', 'window_start', 'window_end',
                       'status', 'video_count', 'detail_succeeded_count', 'detail_failed_count',
                       'updated_at', 'next_retry_at')[:14])
    rows[1]['recent_batches'] = batches
    if batches:
        latest = batches[0]
        rows[1].update(last_at=latest['updated_at'], latest_status=latest['status'],
                       stored_count=latest['video_count'] if latest['status'] == 'completed' else None)
    else:
        rows[1]['latest_status'] = 'no_records'
    return rows
