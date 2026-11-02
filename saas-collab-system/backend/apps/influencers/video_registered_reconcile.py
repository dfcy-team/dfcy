"""Link API observations only through an already registered exact video identity."""
from collections import Counter
from django.db import transaction
from django.db.models import Count, Min, Max
from django.utils import timezone
from apps.audit.services import write_operation_log
from apps.permissions.services import check_user_permission
from apps.tenants.models import Tenant
from .models import (TikTokShopVideo, TikTokVideoProduct, TikTokVideoDailyMetric,
                     VideoResult, InfluencerProfile, SampleFulfillment, normalize_tiktok_username)
from .tiktok_dataset_import import _scope_matches_store


def identity_matches(video, registered):
    return bool(
        video.tenant_id == registered.tenant_id
        and video.store_id == registered.store_id
        and video.external_video_id == registered.external_content_id
        and registered.platform.lower() == 'tiktok'
        and registered.influencer.tenant_id == video.tenant_id
        and registered.influencer.platform.lower() == 'tiktok'
        and normalize_tiktok_username(video.creator_username)
        and normalize_tiktok_username(video.creator_username) == normalize_tiktok_username(registered.influencer.handle)
        and video.influencer_id in (None, registered.influencer_id))


def reconcile(actor, store_id, *, apply=False):
    from apps.masterdata.models import StoreMaster
    from .services import refresh_sample_fulfillment_video_status
    store=StoreMaster.objects.get(pk=store_id,tenant_id=actor.tenant_id)
    def authorize():
        actor.refresh_from_db()
        if not actor.is_active or not check_user_permission(actor,'influencers.manage') or not _scope_matches_store(actor,store):
            raise PermissionError('Influencer reconciliation scope denied.')
    authorize()
    counts=Counter(); affected=set()
    ids=TikTokShopVideo.objects.filter(tenant_id=actor.tenant_id,store=store).order_by('pk').values_list('pk',flat=True)
    for pk in ids.iterator(chunk_size=500):
        with transaction.atomic():
            Tenant.objects.select_for_update().get(pk=actor.tenant_id)
            authorize()
            video=TikTokShopVideo.objects.select_for_update().get(pk=pk,tenant_id=actor.tenant_id,store=store)
            records=list(VideoResult.objects.select_for_update().filter(tenant_id=actor.tenant_id,
                store=store,platform='tiktok',external_content_id=video.external_video_id).select_related('influencer')[:2])
            if len(records)!=1:
                counts['no_unique_registered_video']+=1;continue
            registered=records[0]
            if not identity_matches(video,registered):
                counts['identity_conflict']+=1;continue
            affected.add(registered.influencer_id)
            if video.influencer_id is None:
                counts['linked' if apply else 'would_link']+=1
                if apply:
                    video.influencer_id=registered.influencer_id
                    video.save(update_fields=['influencer','updated_at'])
                    write_operation_log(tenant=actor.tenant,user=actor,module='influencers',
                        action='api_video_registered_link',object_type='tiktok_shop_video',object_id=video.pk,
                        before_data={'influencer_id':None},after_data={'influencer_id':video.influencer_id,
                            'registered_video_id':registered.pk,'basis':'exact_video_store_and_handle'})
            else:counts['already_linked']+=1
            # Do not infer sample identity or publication timezone from API usernames.
            if not registered.sample_fulfillment_id or not registered.published_at:
                counts['sample_or_publication_missing']+=1;continue
            sample=SampleFulfillment.objects.select_for_update().filter(pk=registered.sample_fulfillment_id,
                tenant_id=actor.tenant_id,store=store,influencer_id=registered.influencer_id,is_deleted=False).first()
            if sample is None:
                counts['sample_scope_conflict']+=1;continue
            sent=sample.sample_sent_at or sample.shipped_at
            if (not sent or not timezone.is_aware(registered.published_at)
                    or registered.published_at<sent or registered.published_at>timezone.now()
                    or not sample.external_product_id
                    or not TikTokVideoProduct.objects.filter(tenant_id=actor.tenant_id,video=video,
                        external_product_id=sample.external_product_id,source='api',parse_status='parsed').exists()):
                counts['sample_product_or_time_unverified']+=1;continue
            candidates=SampleFulfillment.objects.filter(tenant_id=actor.tenant_id,store=store,
                influencer_id=registered.influencer_id,external_product_id=sample.external_product_id,is_deleted=False)
            if candidates.count()!=1:
                counts['multiple_samples']+=1;continue
            before=sample.status
            if apply:
                sample=refresh_sample_fulfillment_video_status(user=actor,fulfillment=sample.pk)
                counts['fulfillment_updated' if sample.status!=before else 'fulfillment_unchanged']+=1
            else:counts['sample_evidence_eligible']+=1
    if apply:
        for influencer_id in sorted(affected):
            with transaction.atomic():
                Tenant.objects.select_for_update().get(pk=actor.tenant_id);authorize()
                profile=InfluencerProfile.objects.select_for_update().filter(tenant_id=actor.tenant_id,influencer_id=influencer_id).first()
                if not profile:counts['missing_profile']+=1;continue
                metrics=TikTokVideoDailyMetric.objects.filter(tenant_id=actor.tenant_id,store=store,video__influencer_id=influencer_id)
                summary=metrics.aggregate(video_count=Count('video_id',distinct=True),daily_rows=Count('id'),
                    first_date=Min('metric_date'),last_date=Max('metric_date'))
                summary={k:v.isoformat() if hasattr(v,'isoformat') else v for k,v in summary.items()}
                summary['basis']='registered_video_id_store_and_handle'
                history=dict(profile.historical_performance or {})
                all_stores=dict(history.get('api_video_observations') or {})
                if all_stores.get(store.code)==summary:continue
                before=all_stores.get(store.code)
                all_stores[store.code]=summary;history['api_video_observations']=all_stores
                profile.historical_performance=history;profile.save(update_fields=['historical_performance','updated_at'])
                counts['profiles_updated']+=1
                write_operation_log(tenant=actor.tenant,user=actor,module='influencers',action='api_video_profile_summary',
                    object_type='influencer',object_id=influencer_id,before_data={store.code:before},after_data={store.code:summary})
    return dict(counts)
