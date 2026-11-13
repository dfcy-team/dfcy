"""Complete samples only from exact stored API identity, product and time evidence."""
import hashlib
import logging

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.tenants.models import Tenant
from .models import (
    Influencer, InfluencerRestriction, SampleFulfillment, TikTokShopVideo,
    TikTokVideoProduct, VideoResult, normalize_tiktok_username,
)

logger = logging.getLogger(__name__)


def enqueue_video_completion(*, tenant_id, store_id, video_ids):
    ids = sorted(set(video_ids))
    if not ids:
        return

    def dispatch():
        from .tasks import reconcile_sample_videos_task
        try:
            reconcile_sample_videos_task.delay(tenant_id=tenant_id, store_id=store_id, video_ids=ids)
        except Exception:
            # Ingestion has committed; the nightly sweep repairs a missed dispatch.
            logger.exception("Video completion dispatch failed tenant=%s store=%s", tenant_id, store_id)
    transaction.on_commit(dispatch)


def enqueue_registered_video_completion(result):
    if not result.store_id or result.platform.casefold() != "tiktok":
        return
    ids = TikTokShopVideo.objects.filter(
        tenant_id=result.tenant_id, store_id=result.store_id, external_video_id=result.external_content_id,
    ).values_list("pk", flat=True)
    enqueue_video_completion(tenant_id=result.tenant_id, store_id=result.store_id, video_ids=ids)


@transaction.atomic
def complete_sample_from_video(*, actor, video_id):
    from .services import transition_sample_fulfillment

    Tenant.objects.select_for_update().get(pk=actor.tenant_id)
    actor.refresh_from_db()
    if not actor.is_active or actor.user_type != CustomUser.UserType.INTERNAL:
        return "invalid_actor"
    video = TikTokShopVideo.objects.select_for_update().select_related("store").get(
        tenant_id=actor.tenant_id, pk=video_id,
    )
    published = video.published_at
    if video.video_type == "self_operated":
        return "self_operated"
    if not published or not timezone.is_aware(published) or published > timezone.now():
        return "publication_unknown"
    handle = normalize_tiktok_username(video.creator_username)
    if not handle:
        return "identity_unknown"
    digest = hashlib.sha256(handle.encode("utf-8")).hexdigest()
    creators = list(Influencer.objects.filter(
        tenant_id=actor.tenant_id, platform__iexact="tiktok", canonical_handle_digest=digest,
    ).order_by("pk")[:2])
    if len(creators) != 1 or (video.influencer_id and video.influencer_id != creators[0].pk):
        return "identity_ambiguous"
    creator = creators[0]
    if InfluencerRestriction.objects.filter(
        tenant_id=actor.tenant_id, influencer=creator, is_blacklisted=True,
    ).exists():
        return "blacklisted"
    products = set(TikTokVideoProduct.objects.filter(
        tenant_id=actor.tenant_id, video=video, source="api", parse_status="parsed",
    ).exclude(external_product_id="").values_list("external_product_id", flat=True))
    if not products:
        return "product_unknown"
    samples = SampleFulfillment.objects.select_for_update().filter(
        tenant_id=actor.tenant_id, influencer=creator, store_id=video.store_id, is_deleted=False,
        status__in=["shipped", "delivered", "overdue", "published", "completed"],
    ).filter(Q(external_product_id__in=products) | Q(items__external_product_id__in=products)).distinct().order_by("pk")
    eligible = []
    for sample in samples:
        times = [value for value in (sample.shipped_at, sample.sample_sent_at) if value]
        if not times or any(not timezone.is_aware(value) for value in times) or published <= max(times):
            continue
        item_products = set(sample.items.filter(tenant_id=actor.tenant_id).exclude(
            external_product_id="",
        ).values_list("external_product_id", flat=True))
        required = item_products | ({sample.external_product_id} if sample.external_product_id else set())
        if required and required.issubset(products):
            eligible.append(sample)
    if len(eligible) != 1:
        return "multiple_samples" if eligible else "no_eligible_sample"
    sample = eligible[0]
    if not sample.sample_order_no.strip():
        return "sample_order_unknown"
    if SampleFulfillment.objects.filter(
        tenant_id=actor.tenant_id, store_id=sample.store_id,
        sample_order_no=sample.sample_order_no, is_deleted=False,
    ).exclude(pk=sample.pk).exists():
        return "sample_order_conflict"
    registered = list(VideoResult.objects.select_for_update().filter(
        tenant_id=actor.tenant_id, platform__iexact="tiktok", external_content_id=video.external_video_id,
    ).order_by("pk")[:2])
    if len(registered) > 1:
        return "registered_identity_conflict"
    if registered:
        result = registered[0]
        if (result.influencer_id != creator.pk or result.store_id != video.store_id
                or result.content_type != "video" or result.published_at != published
                or result.sample_fulfillment_id not in (None, sample.pk)
                or result.outreach_task_id not in (None, sample.outreach_task_id)):
            return "registered_identity_conflict"
    if sample.status == "completed":
        return "already_completed"
    if registered:
        result.sample_fulfillment = sample
        result.outreach_task_id = sample.outreach_task_id
        result.save(update_fields=["sample_fulfillment", "outreach_task", "updated_at"])
    else:
        VideoResult.objects.create(
            tenant_id=actor.tenant_id, influencer=creator, store=video.store,
            sample_fulfillment=sample, outreach_task_id=sample.outreach_task_id,
            platform="tiktok", content_type="video", external_content_id=video.external_video_id,
            title=video.title[:240], published_at=published, metric_date=published.date(),
            currency=video.store.currency, source="api_sample_completion",
        )
    transition_sample_fulfillment(
        user=actor, fulfillment=sample, status="completed", expected_version=sample.version,
        confirm_terminal=True, reason=f"api_video_verified:{video.pk}:{video.external_video_id}",
    )
    return "completed"
