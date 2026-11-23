from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.db.models import QuerySet
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.influencers.models import (
    Influencer, InfluencerRestriction, SampleFulfillment, SampleItem,
    TikTokShopVideo, TikTokVideoProduct, VideoResult,
)
from apps.influencers.sample_video_completion import complete_sample_from_video, enqueue_video_completion
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.tenants.models import Tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def data():
    tenant = Tenant.objects.create(code="video-completion", name="Video completion")
    actor = CustomUser.objects.create_user(username="video-worker", tenant=tenant, user_type=CustomUser.UserType.INTERNAL)
    platform = PlatformMaster.objects.create(tenant=tenant, code="tiktok", name="TikTok")
    store = StoreMaster.objects.create(tenant=tenant, platform=platform, code="PH", name="PH", country_code="PH", currency="PHP")
    creator = Influencer.objects.create(tenant=tenant, code="creator", name="Creator", platform="TikTok", handle="exact.creator")
    sent = timezone.now() - timedelta(days=3)
    sample = SampleFulfillment.objects.create(
        tenant=tenant, fulfillment_no="YPDD1", request_key="s1", request_hash="hash", store=store,
        influencer=creator, owner=actor, sample_sent_at=sent,
        external_product_id="123", sample_order_no="ORDER1",
    )
    QuerySet.update(SampleFulfillment.objects.filter(pk=sample.pk), status="shipped", shipped_at=sent)
    video = TikTokShopVideo.objects.create(
        tenant=tenant, store=store, external_video_id="video-1", creator_username="@EXACT.creator",
        published_at=sent + timedelta(days=1),
    )
    product = TikTokVideoProduct.objects.create(
        tenant=tenant, video=video, external_product_id="123", parse_status="parsed", source="api",
    )
    return SimpleNamespace(tenant=tenant, actor=actor, store=store, creator=creator,
                           sample=sample, video=video, product=product, sent=sent)


def run(data):
    return complete_sample_from_video(actor=data.actor, video_id=data.video.pk)


@pytest.mark.parametrize("status", ["shipped", "delivered", "overdue", "published"])
def test_verified_video_completes_sample_once(data, status):
    QuerySet.update(SampleFulfillment.objects.filter(pk=data.sample.pk), status=status)
    assert run(data) == "completed"
    data.sample.refresh_from_db()
    assert data.sample.status == "completed" and data.sample.finalized_at is not None
    assert data.sample.version == 2
    assert data.sample.status_events.count() == 1
    assert VideoResult.objects.get().sample_fulfillment_id == data.sample.pk
    assert run(data) == "already_completed"
    assert data.sample.status_events.count() == 1


@pytest.mark.parametrize("status", ["pending", "cancelled", "blacklisted"])
def test_non_shipped_or_protected_states_untouched(data, status):
    QuerySet.update(SampleFulfillment.objects.filter(pk=data.sample.pk), status=status)
    assert run(data) == "no_eligible_sample"
    assert not VideoResult.objects.exists()


@pytest.mark.parametrize("offset", [-1, 0])
def test_publication_must_be_strictly_after_sending(data, offset):
    data.video.published_at = data.sent + timedelta(seconds=offset)
    data.video.save()
    assert run(data) == "no_eligible_sample"


def test_actual_shipping_timestamp_takes_precedence(data):
    QuerySet.update(SampleFulfillment.objects.filter(pk=data.sample.pk), shipped_at=timezone.now())
    assert run(data) == "no_eligible_sample"


def test_missing_future_publication_and_deleted_sample(data):
    data.video.published_at = None
    data.video.save()
    assert run(data) == "publication_unknown"
    data.video.published_at = timezone.now() + timedelta(days=1)
    data.video.save()
    assert run(data) == "publication_unknown"
    data.video.published_at = data.sent + timedelta(days=1)
    data.video.save()
    QuerySet.update(SampleFulfillment.objects.filter(pk=data.sample.pk), is_deleted=True, deleted_at=timezone.now())
    assert run(data) == "no_eligible_sample"


def test_multiple_orders_never_share_one_video(data):
    second = SampleFulfillment.objects.create(
        tenant=data.tenant, fulfillment_no="YPDD2", request_key="s2", request_hash="hash",
        store=data.store, influencer=data.creator, owner=data.actor,
        sample_sent_at=data.sent, external_product_id="123", sample_order_no="ORDER2",
    )
    QuerySet.update(SampleFulfillment.objects.filter(pk=second.pk), status="shipped", shipped_at=data.sent)
    assert run(data) == "multiple_samples"
    assert not VideoResult.objects.exists()


def test_identity_product_and_store_must_all_match(data):
    data.video.creator_username = "different.creator"
    data.video.save()
    assert run(data) == "identity_ambiguous"
    data.video.creator_username = data.creator.handle
    data.video.save()
    data.product.external_product_id = "other"
    data.product.save()
    assert run(data) == "no_eligible_sample"
    data.product.external_product_id = "123"
    data.product.save()
    other = StoreMaster.objects.create(tenant=data.tenant, platform=data.store.platform, code="PH2", name="PH2", country_code="PH", currency="PHP")
    data.video.store = other
    data.video.save()
    assert run(data) == "no_eligible_sample"


def test_blacklisted_creator_and_unparsed_products_do_not_complete(data):
    data.product.parse_status = "pending"
    data.product.save()
    assert run(data) == "product_unknown"
    data.product.parse_status = "parsed"
    data.product.save()
    InfluencerRestriction.objects.create(tenant=data.tenant, influencer=data.creator, is_blacklisted=True, created_by=data.actor)
    assert run(data) == "blacklisted"


def test_multi_product_sample_requires_all_products_in_video(data):
    SampleItem.objects.create(tenant=data.tenant, fulfillment=data.sample, external_product_id="456", site_code="PH", quantity=1)
    assert run(data) == "no_eligible_sample"
    TikTokVideoProduct.objects.create(tenant=data.tenant, video=data.video, external_product_id="456", source="api", parse_status="parsed")
    assert run(data) == "completed"


def test_conflicting_registered_video_is_not_overwritten(data):
    VideoResult.objects.create(
        tenant=data.tenant, influencer=data.creator, store=data.store, platform="TikTok", content_type="video",
        external_content_id=data.video.external_video_id, metric_date=timezone.localdate(),
        published_at=data.video.published_at - timedelta(hours=1), currency="PHP",
    )
    assert run(data) == "registered_identity_conflict"
    assert not data.sample.status_events.exists()


def test_order_identity_is_required_and_conflicting_order_is_deferred(data):
    QuerySet.update(SampleFulfillment.objects.filter(pk=data.sample.pk), sample_order_no="")
    assert run(data) == "sample_order_unknown"
    QuerySet.update(SampleFulfillment.objects.filter(pk=data.sample.pk), sample_order_no="ORDER1")
    other_creator = Influencer.objects.create(tenant=data.tenant, code="other", name="Other", platform="TikTok", handle="other")
    SampleFulfillment.objects.create(
        tenant=data.tenant, fulfillment_no="OTHER", request_key="other", request_hash="hash",
        store=data.store, influencer=other_creator, owner=data.actor, sample_order_no="ORDER1",
    )
    assert run(data) == "sample_order_conflict"


def test_worker_uses_audited_completion_and_nightly_schedule(data):
    from django.conf import settings
    from apps.influencers.tasks import reconcile_sample_videos_task
    assert reconcile_sample_videos_task(data.tenant.pk, data.store.pk) == {"completed": 1, "publication_unknown": 0}
    assert reconcile_sample_videos_task(data.tenant.pk, data.store.pk) == {"already_completed": 1, "publication_unknown": 0}
    schedule = settings.CELERY_BEAT_SCHEDULE["nightly-sample-video-completion"]
    assert schedule["schedule"].hour == {17} and schedule["schedule"].minute == {0}


def test_registered_result_links_only_with_matching_evidence(data):
    result = VideoResult.objects.create(
        tenant=data.tenant, influencer=data.creator, store=data.store, platform="TikTok", content_type="video",
        external_content_id=data.video.external_video_id, metric_date=timezone.localdate(),
        published_at=data.video.published_at, currency="PHP",
    )
    assert run(data) == "completed"
    result.refresh_from_db()
    assert result.sample_fulfillment_id == data.sample.pk
    assert VideoResult.objects.count() == 1


def test_link_and_status_roll_back_together_on_transition_failure(data, monkeypatch):
    def fail(**kwargs):
        raise RuntimeError("transition failed")
    monkeypatch.setattr("apps.influencers.services.transition_sample_fulfillment", fail)
    with pytest.raises(RuntimeError, match="transition failed"):
        run(data)
    assert not VideoResult.objects.exists()
    data.sample.refresh_from_db()
    assert data.sample.status == "shipped" and data.sample.version == 1


def test_readonly_plan_does_not_write_or_advance_status(data):
    details = {}
    assert complete_sample_from_video(actor=data.actor, video_id=data.video.pk, apply=False, details=details) == "would_complete"
    assert details["sample_id"] == data.sample.pk
    assert not VideoResult.objects.exists() and not data.sample.status_events.exists()
    data.sample.refresh_from_db()
    assert data.sample.status == "shipped" and data.sample.version == 1


def test_registered_timestamp_can_supply_missing_api_time_only_for_exact_identity(data):
    published = data.video.published_at
    data.video.published_at = None
    data.video.save()
    result = VideoResult.objects.create(
        tenant=data.tenant, influencer=data.creator, store=data.store, platform="TikTok", content_type="video",
        external_content_id=data.video.external_video_id, metric_date=timezone.localdate(), published_at=published, currency="PHP",
    )
    details = {}
    assert complete_sample_from_video(actor=data.actor, video_id=data.video.pk, apply=False, details=details) == "would_complete"
    assert details["publication_source"] == "registered_video"
    other = StoreMaster.objects.create(tenant=data.tenant, platform=data.store.platform, code="WRONG", name="Wrong")
    result.store = other
    result.save()
    assert run(data) == "registered_identity_conflict"


def test_cross_tenant_and_inactive_actor_rejected(data):
    other = Tenant.objects.create(code="other-video", name="Other")
    actor = CustomUser.objects.create_user(username="other-video", tenant=other, user_type=CustomUser.UserType.INTERNAL)
    with pytest.raises(TikTokShopVideo.DoesNotExist):
        complete_sample_from_video(actor=actor, video_id=data.video.pk)
    data.actor.is_active = False
    data.actor.save(update_fields=["is_active"])
    assert run(data) == "invalid_actor"


def test_enqueue_only_after_commit_and_nightly_dispatch(data, monkeypatch, django_capture_on_commit_callbacks):
    from apps.influencers.tasks import reconcile_sample_videos_task, dispatch_nightly_sample_video_reconciliation_task
    calls = []
    monkeypatch.setattr(reconcile_sample_videos_task, "delay", lambda **kwargs: calls.append(kwargs))
    with django_capture_on_commit_callbacks(execute=True):
        enqueue_video_completion(tenant_id=data.tenant.pk, store_id=data.store.pk, video_ids=[data.video.pk] * 2)
        assert calls == []
    assert calls[0]["video_ids"] == [data.video.pk]
    calls.clear()
    assert dispatch_nightly_sample_video_reconciliation_task()["queued_stores"] == 1
    assert calls == [{"tenant_id": data.tenant.pk, "store_id": data.store.pk}]
