"""Read-only completion provenance from scoped samples and exact stored evidence."""
import hashlib
from collections import defaultdict
from django.db.models import Count, OuterRef, Subquery
from django.utils import timezone
from .completion_provenance import parse_completion_reason
from .models import FulfillmentStatusEvent, Influencer, SampleFulfillment, VideoResult, normalize_tiktok_username


def attach_completion_evidence(samples):
    by_tenant = defaultdict(list)
    for sample in samples:
        sample._completion_evidence = None
        sample._completion_evidence_version = sample.version
        if sample.status == 'completed':
            by_tenant[sample.tenant_id].append(sample)
    for tenant, items in by_tenant.items():
        subjects = {s.pk: s for s in items}
        last = FulfillmentStatusEvent.objects.filter(tenant_id=tenant,
            fulfillment_id=OuterRef('pk'), to_status='completed').order_by('-created_at', '-pk')
        latest_ids = SampleFulfillment.objects.filter(tenant_id=tenant, pk__in=subjects,
            status='completed').annotate(latest_completion=Subquery(last.values('pk')[:1])).values_list('latest_completion', flat=True)
        events = FulfillmentStatusEvent.objects.filter(tenant_id=tenant, pk__in=latest_ids,
            actor__tenant_id=tenant).select_related('actor')
        candidates = {}
        for event in events:
            sample = subjects[event.fulfillment_id]
            if event.source:
                continue
            if (event.reason or '').startswith('manual_completion:'):
                sample._completion_evidence = {'kind':'manual','at':event.created_at,'actor':event.actor.get_username()}
                continue
            if event.reason == 'manual_edit':
                sample._completion_evidence = {'kind':'generic','at':event.created_at,'actor':event.actor.get_username()}
                continue
            parsed = parse_completion_reason(event.reason, tenant_id=tenant,
                sample_id=sample.pk, actor_id=event.actor_id)
            if parsed:
                candidates[sample.pk] = (event, *parsed)
        if not candidates:
            continue
        from .models import TikTokShopVideo
        raw = {v.pk:v for v in TikTokShopVideo.objects.filter(tenant_id=tenant,
            pk__in={c[1] for c in candidates.values()}).select_related('store')}
        external_ids = {candidate[2] for candidate in candidates.values()}
        # Mirror the writer: any registered result with this tenant/external ID
        # makes the identity ambiguous when there is more than one row.
        registered_counts = dict(VideoResult.objects.filter(tenant_id=tenant, platform__iexact='tiktok',
            external_content_id__in=external_ids).values('external_content_id').annotate(count=Count('pk'))
            .values_list('external_content_id', 'count'))
        registered = defaultdict(list)
        for result in VideoResult.objects.filter(tenant_id=tenant, platform__iexact='tiktok',
                external_content_id__in=external_ids, published_at__isnull=False):
            registered[result.external_content_id].append(result)
        # Require unique canonical creator identity even when the raw row has
        # a direct FK, and require that FK to agree with the unique identity.
        handles = {hashlib.sha256(handle.encode()).hexdigest() for v in raw.values()
            if (handle := normalize_tiktok_username(v.creator_username))}
        creators = {r['canonical_handle_digest']:r for r in Influencer.objects.filter(
            tenant_id=tenant, platform__iexact='tiktok', canonical_handle_digest__in=handles
        ).values('canonical_handle_digest').annotate(count=Count('pk'))}
        creator_ids = dict(Influencer.objects.filter(tenant_id=tenant, platform__iexact='tiktok',
            canonical_handle_digest__in={d for d,r in creators.items() if r['count']==1}
        ).values_list('canonical_handle_digest','pk')) if handles else {}
        for sample_id, (event, raw_id, external_id, writer_verified) in candidates.items():
            sample = subjects[sample_id]
            source = raw.get(raw_id)
            if (source is None or source.external_video_id != external_id or source.store_id != sample.store_id
                    or source.store.tenant_id != tenant or source.video_type == 'self_operated'):
                continue
            handle = normalize_tiktok_username(source.creator_username)
            digest = hashlib.sha256(handle.encode()).hexdigest() if handle else ''
            if (creator_ids.get(digest) != sample.influencer_id
                    or (source.influencer_id is not None and source.influencer_id != creator_ids.get(digest))):
                continue
            valid = [v for v in registered[external_id] if v.external_content_id == external_id
                and v.content_type == 'video' and v.store_id == sample.store_id and v.influencer_id == sample.influencer_id
                and v.outreach_task_id == sample.outreach_task_id
                and v.published_at <= timezone.now()
                and (source.published_at is None or source.published_at == v.published_at)]
            if registered_counts.get(external_id) == 1 and len(valid) == 1:
                sample._completion_evidence = {'kind':'system' if writer_verified else 'linked','at':event.created_at,'video_id':external_id}
