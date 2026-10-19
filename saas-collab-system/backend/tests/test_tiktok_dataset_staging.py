import json
from datetime import UTC, datetime

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from rest_framework.test import APIClient

from tests.test_tiktok_dataset_import import trial, _video
from apps.influencers import tiktok_dataset_staging as staging
from apps.influencers.models import (
    AffiliateOrderSnapshot, Influencer, InfluencerProfile, TikTokShopVideo,
    TikTokVideoDailyMetric, TikTokDatasetStageBatch, TikTokDatasetStagePartition,
    TikTokDatasetStageRecord,
)
from apps.influencers.tiktok_shop_dataset import canonical_bytes, digest_bytes
from apps.permissions.models import Permission
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def write_artifact(trial, *, videos=(), affiliates=(), creators=(), quality="complete", version=2):
    root = trial["manifest_path"].parent
    store, tenant = trial["store"], trial["tenant"]
    components = []
    for kind, payloads in (("videos", videos), ("affiliate_orders", affiliates), ("creators", creators)):
        content = b"".join(canonical_bytes(dict(kind=kind, tenant_id=tenant.pk, store_id=store.pk,
            store_code=store.code, payload=payload)) + b"\n" for payload in payloads)
        filename = kind + ".jsonl"
        (root / filename).write_bytes(content)
        component = dict(kind=kind, store_id=store.pk, status=quality if kind == "videos" else "complete",
            row_count=len(payloads), request_count=1, file=filename, sha256=digest_bytes(content))
        if version == 2:
            day_quality = quality if kind == "videos" else "complete"
            component["days"] = [dict(date="2026-09-02", status=day_quality,
                reason="pagination_total_mismatch" if day_quality == "partial" else "pagination_exhausted", observed_count=len(payloads),
                expected_count=len(payloads) + (1 if day_quality == "partial" else 0), page_count=1, pagination_exhausted=True)]
        components.append(component)
    manifest = dict(schema_version=version, tenant_id=tenant.pk, start_date="2026-09-02", end_date="2026-09-02",
        created_at="2026-09-03T00:00:00+00:00", stores=[dict(store_id=store.pk, store_code=store.code,
            platform_shop_id=store.external_store_id, timezone=store.timezone)], components=components)
    content = canonical_bytes(manifest)
    trial["manifest_path"].write_bytes(content)
    return digest_bytes(content)


def run(trial, digest, apply=True, **kwargs):
    return staging.stage_artifact(manifest_path=trial["manifest_path"], manifest_sha256=digest,
        tenant_id=kwargs.get("tenant_id", trial["tenant"].pk), store_id=trial["store"].pk,
        actor_id=trial["actor"].pk, apply=apply)


def line(sku="sku-one", payment="100"):
    return dict(order_id="order-one", sku_id=sku, product_id="product-one", creator_username="creator",
        content_id="video-one", commission_model="STANDARD", quantity=1,
        create_time=int(datetime(2026, 9, 2, 5, tzinfo=UTC).timestamp()),
        price={"amount": "0", "currency": "PHP"}, actual_commission_base={"amount": "80", "currency": "PHP"},
        order_payment={"amount": payment, "currency": "PHP", "status": "matched", "source": "ordinary_order_detail"})


def test_settlement_staging_persists_known_quarantines_unknown_and_preserves_prior_observations(trial):
    valid = dict(line(), settlement_status="SETTLED")
    unknown = dict(line(sku="unknown-sku"), settlement_status="UNKNOWN")
    result = run(trial, write_artifact(trial, affiliates=[valid, unknown]))
    assert result["rejected"] == 1 and result["canonical_writes"] == 0
    known = TikTokDatasetStageRecord.objects.get(record_type="affiliate_line")
    assert known.payload["settlement_status"] == "\u5df2\u7ed3\u7b97"
    assert known.partition.rejection_reasons == {"unknown_settlement_status": 1}
    assert run(trial, write_artifact(trial, affiliates=[valid, unknown]))["created"] == 0
    run(trial, write_artifact(trial, affiliates=[line()]))
    known.refresh_from_db()
    assert known.payload["settlement_status"] == "\u5df2\u7ed3\u7b97"
    missing = TikTokDatasetStageRecord.objects.filter(record_type="affiliate_line").exclude(pk=known.pk).get()
    assert missing.payload["settlement_status"] is None and missing.record_key == known.record_key
    from apps.influencers.tiktok_dataset_import import _canonical_digest
    assert missing.payload_hash == _canonical_digest({key: value for key, value in missing.payload.items()
        if key not in {"settlement_status", "actual_paid_shop_ads_commission"}})
    assert AffiliateOrderSnapshot.objects.count() == 0


@pytest.mark.parametrize("value", [None, "0", "1.2345"])
def test_ads_money_stages_independently_with_legacy_hash_compatibility_and_no_promotion(trial, value):
    from apps.influencers.tiktok_dataset_import import _canonical_digest
    payload = line()
    payload["actual_paid_commission"] = {"amount": "2", "currency": "PHP"}
    if value is not None:
        payload["actual_paid_shop_ads_commission"] = {"amount": value, "currency": "PHP"}
    digest = write_artifact(trial, affiliates=[payload])
    result = run(trial, digest)
    record = TikTokDatasetStageRecord.objects.get(record_type="affiliate_line")
    assert record.payload["actual_paid_commission"] == {"amount": "2", "currency": "PHP"}
    assert record.payload["actual_paid_shop_ads_commission"] == {
        "amount": value, "currency": "PHP" if value is not None else None,
    }
    hash_values = {key: item for key, item in record.payload.items() if key != "settlement_status"}
    if value is None:
        hash_values.pop("actual_paid_shop_ads_commission")
    assert record.payload_hash == _canonical_digest(hash_values)
    assert run(trial, digest)["created"] == 0
    assert result["canonical_writes"] == 0 and AffiliateOrderSnapshot.objects.count() == 0


@pytest.mark.parametrize("money", [
    {"amount": "0", "currency": "MYR"}, {"amount": "2", "currency": None},
    {"amount": None, "currency": "MYR"},
])
def test_ads_currency_mismatch_is_quarantined_without_assuming_store_currency(trial, money):
    payload = line()
    payload["actual_paid_shop_ads_commission"] = money
    result = run(trial, write_artifact(trial, affiliates=[payload]))
    assert result["rejected"] == 1 and result["canonical_writes"] == 0
    partition = TikTokDatasetStagePartition.objects.get(kind="affiliate_orders")
    assert partition.rejection_reasons == {"affiliate_currency_mismatch": 1}
    assert not TikTokDatasetStageRecord.objects.filter(record_type="affiliate_line").exists()
    assert AffiliateOrderSnapshot.objects.count() == 0


def test_partial_null_zero_long_title_and_unknown_identity_stay_nonformal(trial):
    digest = write_artifact(trial, videos=[_video(title="x" * 688, author_type="UNRECOGNIZED",
        metrics={"views": 0})], quality="partial")
    report = run(trial, digest)
    row = TikTokDatasetStageRecord.objects.get(record_type="video_daily")
    assert row.payload["metrics"]["views"] == 0
    assert row.payload["metrics"]["likes"] is None
    assert row.payload["metrics"]["gmv"]["amount"] is None
    assert row.payload["video_type"] == "unknown"
    assert len(row.payload["title"]) == 688
    assert row.partition.quality == "partial"
    assert report["canonical_writes"] == 0
    assert TikTokShopVideo.objects.count() == TikTokVideoDailyMetric.objects.count() == AffiliateOrderSnapshot.objects.count() == 0


def test_two_skus_have_one_payment_not_two_gmv(trial):
    digest = write_artifact(trial, affiliates=[line(), line("sku-two")])
    run(trial, digest)
    assert TikTokDatasetStageRecord.objects.filter(record_type="affiliate_line").count() == 2
    payment = TikTokDatasetStageRecord.objects.get(record_type="order_payment")
    assert payment.payload["amount"] == "100"
    for row in TikTokDatasetStageRecord.objects.filter(record_type="affiliate_line"):
        assert "order_payment" not in row.payload and "payment_amount" not in row.payload
        assert row.payload["price"]["amount"] == "0"


def test_missing_details_remain_unknown_and_commission_is_not_payment(trial):
    payload = line()
    payload.pop("order_payment")
    run(trial, write_artifact(trial, affiliates=[payload]))
    assert TikTokDatasetStageRecord.objects.get(record_type="order_payment").payload["amount"] is None


def test_dry_run_no_business_or_stage_writes(trial):
    result = run(trial, write_artifact(trial, videos=[_video()]), apply=False)
    assert result["created"] == 0
    assert TikTokDatasetStageBatch.objects.count() == 0


def test_replay_is_idempotent_and_observations_immutable(trial):
    digest = write_artifact(trial, videos=[_video()])
    run(trial, digest)
    run(trial, digest)
    assert TikTokDatasetStageRecord.objects.count() == 1
    row = TikTokDatasetStageRecord.objects.get()
    with pytest.raises(Exception, match="immutable"):
        row.save()


def test_v1_complete_artifacts_still_stage_without_promotion(trial):
    result = run(trial, write_artifact(trial, videos=[_video()], version=1))
    assert result["created"] == 1


def test_tenant_or_permission_denial_before_any_writes(trial):
    digest = write_artifact(trial, videos=[_video()])
    other = Tenant.objects.create(code="stage-other", name="Other")
    with pytest.raises(staging.DatasetImportError):
        run(trial, digest, tenant_id=other.pk)
    trial["role"].permissions.clear()
    with pytest.raises(staging.DatasetImportError, match="permission"):
        run(trial, digest)
    assert TikTokDatasetStageRecord.objects.count() == 0


def test_tampered_file_fails_hash_gate(trial):
    digest = write_artifact(trial, videos=[_video()])
    (trial["manifest_path"].parent / "videos.jsonl").write_text("tampered")
    with pytest.raises(staging.DatasetImportError, match="artifact_invalid"):
        run(trial, digest)
    assert TikTokDatasetStageBatch.objects.count() == 0


def test_unknown_creator_id_saved_unlinked_without_profile_overwrite(trial):
    digest = write_artifact(trial, creators=[dict(external_influencer_id="123456", influencer_id=999,
        username="same.nickname", follower_count=0, selection_region="PH")])
    run(trial, digest)
    row = TikTokDatasetStageRecord.objects.get(record_type="creator_snapshot")
    assert row.payload["influencer_id"] is None
    assert row.payload["identity_status"] == "untrusted_or_conflicting_id"
    assert InfluencerProfile.objects.count() == 0


def test_existing_unique_id_link_rechecked_without_changing_handle(trial):
    creator = Influencer.objects.create(tenant=trial["tenant"], code="stage-creator", name="Creator", platform="tiktok", handle="trusted.creator")
    InfluencerProfile.objects.create(tenant=trial["tenant"], influencer=creator, external_influencer_id="123456")
    digest = write_artifact(trial, creators=[dict(external_influencer_id="123456", influencer_id=creator.pk,
        username="trusted.creator", follower_count=100, selection_region="PH")])
    run(trial, digest)
    row = TikTokDatasetStageRecord.objects.get(record_type="creator_snapshot")
    assert row.payload["influencer_id"] == creator.pk and row.payload["identity_status"] == "matched"
    creator.refresh_from_db()
    assert creator.handle == "trusted.creator"


def test_conflicting_order_payment_rejects_page_atomically(trial):
    digest = write_artifact(trial, affiliates=[line(), line("sku-two", payment="200")])
    with pytest.raises(staging.DatasetImportError, match="conflicting_dataset_identity"):
        run(trial, digest)
    assert TikTokDatasetStageRecord.objects.count() == 0


def test_interruption_after_committed_page_resumes_without_duplicate(trial, monkeypatch):
    digest = write_artifact(trial, videos=[_video(video_id=f"video-{i}") for i in range(51)])
    original = TikTokDatasetStageRecord.save
    attempts = []
    def interrupted(self, *args, **kwargs):
        attempts.append(self.record_key)
        if len(attempts) == 51:
            raise RuntimeError("simulated_stop")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(TikTokDatasetStageRecord, "save", interrupted)
    with pytest.raises(RuntimeError, match="simulated_stop"):
        run(trial, digest)
    partition = TikTokDatasetStagePartition.objects.get(kind="videos")
    assert partition.next_offset == 50 and partition.import_status == "pending"
    assert TikTokDatasetStageRecord.objects.count() == 50
    monkeypatch.setattr(TikTokDatasetStageRecord, "save", original)
    run(trial, digest)
    partition.refresh_from_db()
    assert partition.next_offset == 51 and partition.import_status == "completed"
    assert TikTokDatasetStageRecord.objects.count() == 51


def test_crash_before_cursor_commit_rolls_back_page(trial, monkeypatch):
    digest = write_artifact(trial, videos=[_video()])
    original = TikTokDatasetStagePartition.save
    def broken(self, *args, **kwargs):
        if self.kind == "videos" and self.next_offset:
            raise RuntimeError("simulated_cursor_stop")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(TikTokDatasetStagePartition, "save", broken)
    with pytest.raises(RuntimeError):
        run(trial, digest)
    assert TikTokDatasetStageRecord.objects.count() == 0
    monkeypatch.setattr(TikTokDatasetStagePartition, "save", original)
    assert run(trial, digest)["created"] == 1


def test_quality_api_tenant_filter_readonly_and_unknown_missing_count(trial):
    run(trial, write_artifact(trial, videos=[_video()], quality="partial"))
    permission, _ = Permission.objects.get_or_create(code="influencers.view", defaults=dict(name="View", module="influencers", action="view"))
    trial["role"].permissions.add(permission)
    client = APIClient()
    client.force_authenticate(trial["actor"])
    result = client.get("/api/internal/influencers/tiktok-datasets/")
    assert result.status_code == 200
    assert result.data["data"]["partial"] == 1
    assert result.data["data"]["missing_count"] is None
    assert result.data["data"]["is_formal"] is False
    assert client.post("/api/internal/influencers/tiktok-datasets/", {}).status_code == 403


def test_cli_defaults_dry_run(trial):
    digest = write_artifact(trial, videos=[_video()])
    call_command("stage_tiktok_shop_dataset", manifest=str(trial["manifest_path"]), manifest_sha256=digest,
        tenant_id=trial["tenant"].pk, store_id=trial["store"].pk, actor_id=trial["actor"].pk)
    assert TikTokDatasetStageRecord.objects.count() == 0


@pytest.mark.parametrize("kind", ["affiliate_orders", "videos"])
def test_monetary_observations_need_separate_bd_permission(trial, kind):
    payloads = {"affiliates": [line()]} if kind == "affiliate_orders" else {
        "videos": [_video(metrics={"gmv": {"amount": "100", "currency": "PHP"}})]}
    result = run(trial, write_artifact(trial, **payloads))
    permission, _ = Permission.objects.get_or_create(code="influencers.view", defaults=dict(name="View", module="influencers", action="view"))
    trial["role"].permissions.add(permission)
    client = APIClient()
    client.force_authenticate(trial["actor"])
    partition = TikTokDatasetStagePartition.objects.get(kind=kind)
    response = client.get(f"/api/internal/influencers/tiktok-datasets/{result['batch_id']}/", {"partition_id": partition.pk})
    assert response.status_code == 403


@pytest.mark.parametrize("kind", ["affiliate_orders", "videos"])
@pytest.mark.parametrize("grants", [("influencers.outreach.view",), ("influencers.fulfillment.view",),
    ("influencers.outreach.view", "influencers.fulfillment.view")])
def test_registered_bd_permissions_allow_only_both_non_superuser_grants(trial, kind, grants):
    from apps.permissions.catalog import ALL_PERMISSION_DEFINITIONS
    definitions = {definition["code"]: definition for definition in ALL_PERMISSION_DEFINITIONS}
    payloads = {"affiliates": [line()]} if kind == "affiliate_orders" else {
        "videos": [_video(metrics={"gmv": {"amount": "100", "currency": "PHP"}})]}
    result = run(trial, write_artifact(trial, **payloads))
    for code in ("influencers.view", *grants):
        assert code in definitions
        permission, _ = Permission.objects.get_or_create(code=code,
            defaults={key: definitions[code][key] for key in ("name", "module", "action")})
        trial["role"].permissions.add(permission)
    assert not trial["actor"].is_superuser
    client = APIClient()
    client.force_authenticate(trial["actor"])
    partition = TikTokDatasetStagePartition.objects.get(kind=kind)
    response = client.get(f"/api/internal/influencers/tiktok-datasets/{result['batch_id']}/", {"partition_id": partition.pk})
    assert response.status_code == (200 if len(grants) == 2 else 403)
    if len(grants) == 2:
        assert response.data["data"]["records"]


def test_preview_detects_payment_conflicts_across_import_pages(trial):
    rows = [line(f"sku-{i}") for i in range(50)] + [line("last", payment="200")]
    with pytest.raises(staging.DatasetImportError, match="conflicting_dataset_identity"):
        run(trial, write_artifact(trial, affiliates=rows), apply=False)
    assert TikTokDatasetStageRecord.objects.count() == 0


def test_tenant_fk_validation_and_cross_tenant_api_detail_denied(trial):
    result = run(trial, write_artifact(trial, videos=[_video()]))
    other = Tenant.objects.create(code="stage-foreign", name="Foreign")
    record = TikTokDatasetStageRecord.objects.get()
    with pytest.raises(Exception, match="same tenant"):
        TikTokDatasetStageRecord.objects.create(tenant=other, partition=record.partition, record_type="video_daily",
            record_key="c" * 64, payload_hash="d" * 64, payload={"views": 0})
    permission, _ = Permission.objects.get_or_create(code="influencers.view", defaults=dict(name="View", module="influencers", action="view"))
    trial["role"].permissions.add(permission)
    trial["actor"].tenant = other
    trial["actor"].save()
    client = APIClient()
    client.force_authenticate(trial["actor"])
    assert client.get(f"/api/internal/influencers/tiktok-datasets/{result['batch_id']}/").status_code in (403, 404)
