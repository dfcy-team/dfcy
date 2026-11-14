from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.influencers import tiktok_video_sync
from apps.influencers.models import (
    Influencer, InfluencerProfile, TikTokShopVideo, TikTokVideoDailyMetric,
    TikTokVideoSyncBatch, TikTokVideoSyncEvidence, VideoResult,
)
from tests.test_lazada_store_authorization import lazada_context
from tests.test_marketplace_callback_acceptance import MANUAL, marketplace_callback

pytestmark = pytest.mark.django_db


def test_reconcile_links_only_unique_exact_registered_video_and_is_idempotent(lazada_context, monkeypatch):
    _, store, _ = lazada_context
    actor = store.tenant.users.first()
    monkeypatch.setattr("apps.influencers.video_registered_reconcile.check_user_permission", lambda *a: True)
    monkeypatch.setattr("apps.influencers.video_registered_reconcile._scope_matches_store", lambda *a: True)
    from apps.influencers.video_registered_reconcile import reconcile

    creator = Influencer.objects.create(tenant=store.tenant, code="linked-creator", name="Creator", platform="tiktok", handle="@Exact.Name")
    profile = InfluencerProfile.objects.create(tenant=store.tenant, influencer=creator,
        historical_performance={"manual": {"source": "human", "score": 5}})
    VideoResult.objects.create(tenant=store.tenant, influencer=creator, store=store,
        content_type="video", platform="tiktok", external_content_id="1001", metric_date=timezone.localdate(), currency="PHP")
    linked = TikTokShopVideo.objects.create(tenant=store.tenant, store=store, external_video_id="1001",
        creator_username="exact.name")
    conflict = TikTokShopVideo.objects.create(tenant=store.tenant, store=store, external_video_id="1002",
        creator_username="someone.else")
    VideoResult.objects.create(tenant=store.tenant, influencer=creator, store=store,
        content_type="video", platform="tiktok", external_content_id="1002", metric_date=timezone.localdate(), currency="PHP")
    result = reconcile(actor, store.pk, apply=True)
    linked.refresh_from_db(); conflict.refresh_from_db(); profile.refresh_from_db()
    assert linked.influencer_id == creator.pk
    assert conflict.influencer_id is None
    assert result.get("identity_conflict", 0) >= 1
    assert profile.historical_performance["manual"] == {"source": "human", "score": 5}
    assert reconcile(actor, store.pk, apply=True).get("profiles_updated", 0) == 0


def test_sync_quarantines_bad_rate_and_commits_degraded_readback(marketplace_callback, monkeypatch, django_capture_on_commit_callbacks):
    from urllib.parse import urlencode
    from rest_framework.test import APIClient
    client, store, config, params, _ = marketplace_callback
    if config.platform != "tiktok": pytest.skip("TikTok integration test")
    response = client.post(MANUAL, {"store_id":store.pk, "integration_config_id":config.pk,
        "callback_url":config.callback_url+"?"+urlencode(params)}, format="json")
    assert response.status_code == 200
    store.currency = "PHP"; store.timezone = "UTC"; store.save(update_fields=["currency", "timezone"])
    from apps.integrations.models import MarketplaceStoreAuthorization
    auth = MarketplaceStoreAuthorization.objects.get(store=store)
    auth.scopes=["data.shop_analytics.public.read"]
    auth.expires_at=timezone.now()+timedelta(days=1)
    from apps.integrations.models import authorization_service_write
    with authorization_service_write(): auth.save(update_fields=["scopes","expires_at","updated_at"])
    day = timezone.now().date() - timedelta(days=1)
    monkeypatch.setattr(tiktok_video_sync, "resolve", lambda actor, store_id: auth)
    monkeypatch.setattr(tiktok_video_sync, "fingerprint", lambda auth: "fixed-test-binding")
    monkeypatch.setattr(tiktok_video_sync, "lock_sources", lambda auth: None)
    monkeypatch.setattr(tiktok_video_sync, "get_runtime_platform_config", lambda platform: {})
    prior_batch = TikTokVideoSyncBatch.objects.create(tenant=store.tenant, store=store,
        window_start=day, window_end=day+timedelta(days=1), api_version=tiktok_video_sync.VERSION,
        idempotency_key=f"{tiktok_video_sync.VERSION}:{day}")
    video = TikTokShopVideo.objects.create(tenant=store.tenant, store=store, external_video_id="8001")
    TikTokVideoDailyMetric.objects.create(tenant=store.tenant, store=store, video=video, batch=prior_batch,
        metric_date=day, currency="PHP", views=5, finish_rate=Decimal("0.6000"), row_hash="old-hash", quality_status="passed")
    payload = {"id":"8001", "creator":{"user_name":"creator"}, "total_performance":{
        "views":11, "video_finish_rate":"2.0000", "v_to_l_rate":"0.2500"}}

    class Client:
        def __init__(self, *_): pass
        def verify_shop(self): pass
        def _request(self, *_args, **_kwargs):
            return {"data":{"latest_available_date":str(day), "total_count":1, "videos":[payload]}}

    actor = store.tenant.users.first()
    from apps.influencers.tasks import reconcile_sample_videos_task
    dispatched = []
    monkeypatch.setattr(reconcile_sample_videos_task, "delay", lambda **kwargs: dispatched.append(kwargs))
    with django_capture_on_commit_callbacks(execute=True):
        result = tiktok_video_sync.run_day(actor, store.pk, day, apply=True, client_factory=Client)
        assert dispatched == []
    assert dispatched == [{"tenant_id": store.tenant_id, "store_id": store.pk, "video_ids": [video.pk]}]
    metric = TikTokVideoDailyMetric.objects.get(store=store, metric_date=day)
    batch = TikTokVideoSyncBatch.objects.get(pk=result["batch_id"])
    evidence = TikTokVideoSyncEvidence.objects.filter(batch=batch, page=0).get().payload
    assert result["database_verified"] is True and result["quarantined_rate_rows"] == 1
    assert metric.views == 11 and metric.finish_rate == Decimal("0.6000")
    assert metric.quality_status == "degraded"
    assert "previous known values retained" in metric.diagnosis
    assert evidence["database_verified"] is True and evidence["quarantined_rate_rows"] == 1
