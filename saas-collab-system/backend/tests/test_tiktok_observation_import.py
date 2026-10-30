"""Synthetic SQLite data only; no provider or custody operations."""

from copy import deepcopy
from datetime import UTC, datetime
import socket

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import CustomUser
from apps.influencers import tiktok_observation_import as service
from apps.influencers.models import (
    AffiliateOrderSnapshot, TikTokShopVideo, TikTokVideoDailyMetric,
    TikTokDatasetStageBatch, TikTokDatasetStagePartition, TikTokDatasetStageRecord,
)
from apps.integrations.models import (
    AdsOAuthSession, PlatformIntegrationConfig, TikTokAdsAdvertiserMapping, TikTokAdsDailySpend,
    authorization_service_write,
)
from apps.integrations.oauth_state_service import configuration_digest
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def ctx(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Network/canonical write forbidden")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    for model in (AffiliateOrderSnapshot, TikTokShopVideo, TikTokVideoDailyMetric, TikTokAdsDailySpend):
        monkeypatch.setattr(model, "save", forbidden)
    tenant = Tenant.objects.create(code="obs-synthetic", name="Synthetic observations")
    platform = PlatformMaster.objects.create(tenant=tenant, code="tiktok", name="Synthetic", platform_type="tiktok")
    store = StoreMaster.objects.create(tenant=tenant, platform=platform, code="OBS", name="Synthetic PH",
        external_store_id="synthetic-shop", country_code="PH", currency="PHP", timezone="Asia/Manila")
    actor = CustomUser.objects.create_user(username="obs-actor", tenant=tenant, user_type="internal")
    role = Role.objects.create(tenant=tenant, code="integration_admin", name="Synthetic API admin")
    UserRole.objects.create(tenant=tenant, user=actor, role=role)
    for code in ("influencers.manage", "integrations.run_live_readonly", "masterdata.view",
                 "integrations.view", "integrations.store.view"):
        permission, _ = Permission.objects.get_or_create(code=code, defaults={"name": code, "module": "test", "action": "view"})
        role.permissions.add(permission)
    DataScope.objects.create(tenant=tenant, role=role, scope_type="all", config={"all": True})
    return tenant, actor, store, role


def document(ctx, n=1, kind="affiliate_observation"):
    tenant, actor, store, role = ctx
    row = {"order_id": "order-1", "sku_id": "sku-1", "product_id": "product-1",
           "create_time": int(datetime(2026, 1, 2, tzinfo=UTC).timestamp()), "quantity": 1,
           "source_settlement_status": "AWAITING PAYMENT", "settlement_mapping_status": "unmapped",
           "settlement_status": None, "payment_amount": None,
           "blockers": ["unmapped_settlement_status", "sku_payment_semantics_not_verified"]}
    rows = [{**deepcopy(row), "sku_id": f"sku-{i}"} for i in range(n)]
    return {"schema_version": service.VERSION, "tenant_id": tenant.pk, "store_id": store.pk,
            "day": "2026-01-02", "observed_at": "2026-01-03T01:00:00+08:00", "kind": kind,
            "quality": "complete", "expected_count": n, "observed_count": n, "reason": "",
            "endpoint": service.ENDPOINTS.get(kind, "/affiliate_seller/202406/marketplace_creators/123"),
            "store_identity": {"platform_store_id": store.external_store_id, "store_code": store.code, "timezone": store.timezone},
            "evidence": {"count_unit": "order_sku", "pagination_exhausted": True, "page_count": 1,
                         "source_total": n, "source_sha256": "a" * 64}, "rows": rows}


def test_unknown_dry_run_apply_replay_preserves_source(ctx):
    doc = document(ctx)
    doc["rows"][0]["affiliate_observed_at"] = "2026-01-03T01:01:00+08:00"
    original = deepcopy(doc)
    with CaptureQueriesContext(connection) as queries:
        preview = service.import_observations(doc, ctx[1].pk)
    assert not any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries)
    assert preview["would_create"] == preview["unknown_count"] == 1
    assert not TikTokDatasetStageBatch.objects.exists()
    result = service.import_observations(doc, ctx[1].pk, apply=True)
    assert result["created"] == 1 and result["canonical_writes"] == 0 and result["is_formal"] is False
    record = TikTokDatasetStageRecord.objects.get()
    assert record.payload["observation"]["source_settlement_status"] == "AWAITING PAYMENT"
    assert record.payload["observation"]["payment_amount"] is None
    assert record.payload["provenance"]["observed_at"] == doc["observed_at"]
    replay = service.import_observations(doc, ctx[1].pk, apply=True)
    assert replay["created"] == 0 and replay["noop"] == 1
    assert doc == original
    assert TikTokDatasetStagePartition.objects.get().import_status == "completed"


@pytest.mark.parametrize("raw,status,blocker", [("SETTLED", "mapped", None), (None, "absent", "absent_settlement_status"),
                                                ("", "absent", "absent_settlement_status")])
def test_mapping_recomputed(ctx, raw, status, blocker):
    doc = document(ctx)
    row = doc["rows"][0]
    row.update(source_settlement_status=raw, settlement_mapping_status=status,
               settlement_status=service.normalize_settlement_status(raw))
    row["blockers"] = ["sku_payment_semantics_not_verified"] + ([blocker] if blocker else [])
    assert service.import_observations(doc, ctx[1].pk, apply=True)["unknown_count"] == 0


@pytest.mark.parametrize("change", [
    lambda d: d.update(tenant_id=True),
    lambda d: d.update(schema_version="affiliate-daily-v3"),
    lambda d: d.update(day="2099-01-01"),
    lambda d: d.update(observed_at="2026-01-03T00:00:00"),
    lambda d: d.update(endpoint=d["endpoint"] + "?access_token=forbidden"),
    lambda d: d.update(observed_count=2),
    lambda d: d.update(expected_count=None),
    lambda d: d["store_identity"].update(platform_store_id="wrong"),
    lambda d: d["evidence"].update(pagination_exhausted=False),
    lambda d: d["evidence"].update(source_sha256="invalid"),
    lambda d: d["evidence"].update(source_total=2),
    lambda d: d["rows"][0].update(access_token="test-forbidden"),
    lambda d: d["rows"][0].update(create_time=0),
    lambda d: d["rows"][0].update(payment_amount="1.00"),
    lambda d: d["rows"][0].update(settlement_mapping_status="mapped"),
    lambda d: d["rows"][0].update(blockers=[]),
    lambda d: d["rows"][0].update(quantity=True),
    lambda d: d["rows"][0].update(estimated_commission_base={"amount": 1.1, "currency": "PHP"}),
    lambda d: d["rows"][0].update(estimated_commission_base={"amount": "1", "currency": "USD"}),
])
def test_invalid_document_is_rejected_before_writes(ctx, change):
    doc = document(ctx)
    change(doc)
    with pytest.raises((service.DatasetImportError, ValueError)):
        service.import_observations(doc, ctx[1].pk, apply=True)
    assert not TikTokDatasetStageBatch.objects.exists()


def test_duplicate_row_and_max_bound(ctx):
    doc = document(ctx, 2)
    doc["rows"][1] = deepcopy(doc["rows"][0])
    with pytest.raises(service.DatasetImportError, match="duplicate"):
        service.import_observations(doc, ctx[1].pk, apply=True)
    doc = document(ctx, 10001)
    with pytest.raises(service.DatasetImportError, match="row_count"):
        service.import_observations(doc, ctx[1].pk, apply=True)
    assert not TikTokDatasetStageBatch.objects.exists()


def test_partial_and_nullable_totals_not_zero(ctx):
    doc = document(ctx)
    doc.update(quality="partial", expected_count=None, reason="pagination_incomplete")
    doc["evidence"].update(pagination_exhausted=False, source_total=None)
    result = service.import_observations(doc, ctx[1].pk, apply=True)
    assert result["source_total"] is None and result["expected_count"] is None
    assert TikTokDatasetStagePartition.objects.get().quality == "partial"


def test_empty_complete_and_maximum_preview(ctx):
    empty = document(ctx, 0)
    assert service.import_observations(empty, ctx[1].pk, apply=True)["created"] == 0
    assert TikTokDatasetStagePartition.objects.get().import_status == "completed"
    assert service.import_observations(empty, ctx[1].pk, apply=True)["noop"] == 0
    assert service.import_observations(document(ctx, 10000), ctx[1].pk)["would_create"] == 10000


def test_permission_revocation_between_pages_stops_new_page(ctx, monkeypatch):
    doc = document(ctx, 51)
    original = service._scope
    calls = 0
    def scope(*a, **kw):
        nonlocal calls
        if kw.get("lock"):
            calls += 1
            if calls == 2:
                raise service.DatasetImportError("synthetic_scope_revoked")
        return original(*a, **kw)
    monkeypatch.setattr(service, "_scope", scope)
    with pytest.raises(service.DatasetImportError, match="scope_revoked"):
        service.import_observations(doc, ctx[1].pk, apply=True)
    assert TikTokDatasetStageRecord.objects.count() == 50
    assert TikTokDatasetStagePartition.objects.get().next_offset == 50


def test_resume_after_second_page_failure(ctx, monkeypatch):
    doc = document(ctx, 51)
    original = TikTokDatasetStageRecord.save
    calls = 0
    def save(record, *a, **kw):
        nonlocal calls
        calls += 1
        if calls == 51:
            raise RuntimeError("synthetic interruption")
        return original(record, *a, **kw)
    monkeypatch.setattr(TikTokDatasetStageRecord, "save", save)
    with pytest.raises(RuntimeError, match="interruption"):
        service.import_observations(doc, ctx[1].pk, apply=True)
    partition = TikTokDatasetStagePartition.objects.get()
    assert partition.next_offset == 50 and partition.import_status == "pending"
    assert partition.records.count() == 50
    result = service.import_observations(doc, ctx[1].pk, apply=True)
    assert result["created"] == 1 and result["noop"] == 50
    assert TikTokDatasetStageRecord.objects.count() == 51


def test_replay_does_not_trust_completed_cursor_or_stored_hash(ctx):
    doc = document(ctx)
    service.import_observations(doc, ctx[1].pk, apply=True)
    record = TikTokDatasetStageRecord.objects.get()
    changed = deepcopy(record.payload)
    changed["observation"]["source_settlement_status"] = "SETTLED"
    # Simulate out-of-band corruption, not a supported application write.
    with connection.cursor() as cursor:
        import json
        cursor.execute(f"UPDATE {record._meta.db_table} SET payload = %s WHERE id = %s", [json.dumps(changed), record.pk])
    for apply in (False, True):
        with pytest.raises(service.DatasetImportError, match="immutable_payload_conflict"):
            service.import_observations(doc, ctx[1].pk, apply=apply)


def test_actor_and_store_scopes(ctx):
    doc = document(ctx)
    other = Tenant.objects.create(code="obs-other", name="Other synthetic")
    actor = CustomUser.objects.create_user(username="obs-other", tenant=other, user_type="internal")
    with pytest.raises(service.DatasetImportError):
        service.import_observations(doc, actor.pk, apply=True)
    permission = Permission.objects.get(code="integrations.run_live_readonly")
    ctx[3].code = "revoked-api-admin"
    ctx[3].save(update_fields=["code"])
    with pytest.raises(service.DatasetImportError):
        service.import_observations(doc, ctx[1].pk, apply=True)
    assert not TikTokDatasetStageBatch.objects.exists()


def test_video_and_creator_keep_raw_identity_not_formal_link(ctx):
    doc = document(ctx, kind="video_observation")
    doc["evidence"]["count_unit"] = "video"
    doc["rows"] = [{"external_video_id": "synthetic-video", "metric_date": doc["day"],
                    "author_type": "MARKETING_ACCOUNTS", "metrics": {"views": None, "gmv": {"amount": None, "currency": None}}}]
    assert service.import_observations(doc, ctx[1].pk, apply=True)["created"] == 1
    doc = document(ctx, kind="creator_snapshot")
    doc["evidence"]["count_unit"] = "creator"
    doc["rows"] = [{"external_influencer_id": "123", "influencer_id": None,
                    "username": "synthetic", "follower_count": None}]
    service.import_observations(doc, ctx[1].pk, apply=True)
    observation = TikTokDatasetStageRecord.objects.get(record_type="creator_snapshot").payload["observation"]
    assert observation["matched_influencer_id"] is None
    assert observation["identity_status"] == "untrusted_or_conflicting_id"


def ads_document(ctx):
    tenant, actor, store, role = ctx
    with authorization_service_write():
        config = PlatformIntegrationConfig.objects.create(tenant=tenant, created_by=actor, platform="tiktok",
            account_alias="Synthetic Ads", environment="pilot", status="verified", sync_write_enabled=False,
            platform_config={"api_type": "advertising"}, credential_id="cre_" + "a" * 32)
    mapping = TikTokAdsAdvertiserMapping.objects.create(tenant=tenant, store=store, integration_config=config,
        advertiser_id="12345", token_id="tok_" + "b" * 32, currency="USD", timezone="UTC", enabled=True)
    AdsOAuthSession.objects.create(tenant=tenant, actor=actor, store=store, integration_config=config, token_id=mapping.token_id,
        expires_at=datetime(2026, 1, 4, tzinfo=UTC),
        status="bound", credential_id="cre_" + "a" * 32, config_fingerprint=configuration_digest(config),
        candidates=[{"advertiser_id": mapping.advertiser_id, "verify_state": "verified", "verified_at": "2026-01-01T00:00:00Z",
                     "currency": "USD", "timezone": "UTC"}],
        binding_results=[{"mapping_id": mapping.pk, "advertiser_id": mapping.advertiser_id}])
    doc = document(ctx, kind="gmv_max_campaign")
    doc["observed_at"] = "2026-01-03T10:00:00+08:00"
    doc.update(mapping_id=mapping.pk, advertiser_id=mapping.advertiser_id, currency="USD", timezone="UTC")
    doc["evidence"]["count_unit"] = "campaign"
    doc["rows"] = [{"campaign_id": "123", "stat_time_day": doc["day"], "cost": "92.260000"}]
    return doc, mapping


def test_gmv_separate_kind_and_verified_mapping(ctx):
    doc, mapping = ads_document(ctx)
    doc["rows"][0]["cost"] = "92.26000001"
    result = service.import_observations(doc, ctx[1].pk, apply=True)
    assert result["created"] == 1
    assert TikTokDatasetStagePartition.objects.get().kind == "gmv_max"
    record = TikTokDatasetStageRecord.objects.get()
    assert record.payload["provenance"]["currency"] == "USD"
    assert record.payload["observation"]["cost"] == "92.26000001"


@pytest.mark.parametrize("mutation", ["advertiser_id", "currency", "mapping_id", "permission", "binding", "cost", "date"])
def test_gmv_scope_and_money_fail_closed(ctx, mutation):
    doc, mapping = ads_document(ctx)
    if mutation in {"advertiser_id", "currency"}:
        doc[mutation] = "wrong"
    elif mutation == "mapping_id":
        doc[mutation] += 1000
    elif mutation == "permission":
        ctx[3].code = "revoked-api-admin"
        ctx[3].save(update_fields=["code"])
    elif mutation == "binding":
        AdsOAuthSession.objects.all().delete()
    elif mutation == "cost":
        doc["rows"][0]["cost"] = 92.26
    else:
        doc["rows"][0]["stat_time_day"] = "2026-01-01"
    with pytest.raises((service.DatasetImportError, ValidationError)):
        service.import_observations(doc, ctx[1].pk, apply=True)
    assert not TikTokDatasetStageBatch.objects.exists()


def test_gmv_null_cost_remains_unknown_and_mapping_scope_is_enforced(ctx):
    doc, mapping = ads_document(ctx)
    doc["rows"][0]["cost"] = None
    result = service.import_observations(doc, ctx[1].pk)
    assert result["missing_cost_count"] == 1 and result["unknown_settlement_count"] == 0
    DataScope.objects.filter(role=ctx[3]).update(scope_type="custom", config={"store_ids": [ctx[2].pk + 1000]})
    with pytest.raises((service.DatasetImportError, PermissionDenied)):
        service.import_observations(doc, ctx[1].pk, apply=True)
    assert not TikTokDatasetStageBatch.objects.exists()


def test_multiple_creator_observations_use_allowlisted_endpoint_template(ctx):
    doc = document(ctx, 2, kind="creator_snapshot")
    doc["endpoint"] = service.CREATOR_ENDPOINT
    doc["evidence"]["count_unit"] = "creator"
    doc["rows"] = [{"external_influencer_id": str(n), "influencer_id": None} for n in (123, 124)]
    assert service.import_observations(doc, ctx[1].pk, apply=True)["created"] == 2


@pytest.mark.parametrize("separator", ["\n", "\r\n", "\t"])
def test_video_title_preserves_legal_multiline_text(ctx, separator):
    doc = document(ctx, kind="video_observation")
    doc["evidence"]["count_unit"] = "video"
    title = "First line" + separator + "Second line"
    doc["rows"] = [{"external_video_id": "synthetic-video", "metric_date": doc["day"],
                    "title": title, "metrics": {"views": None}}]
    assert service.import_observations(doc, ctx[1].pk, apply=True)["created"] == 1
    assert TikTokDatasetStageRecord.objects.get().payload["observation"]["title"] == title
    doc["rows"][0]["external_video_id"] += "\n"
    with pytest.raises(service.DatasetImportError, match="invalid_text"):
        service.import_observations(doc, ctx[1].pk)


def test_partial_preserves_more_observations_than_declared_total(ctx):
    doc = document(ctx, n=2)
    doc.update(quality="partial", expected_count=1, reason="pagination_total_mismatch")
    doc["evidence"]["source_total"] = 1
    result = service.import_observations(doc, ctx[1].pk, apply=True)
    assert result["created"] == 2 and result["source_total"] == 1
    partition = TikTokDatasetStagePartition.objects.get()
    assert partition.quality == "partial" and partition.observed_count == 2 and partition.expected_count == 1
    doc["quality"] = "complete"
    with pytest.raises(service.DatasetImportError, match="unproven_complete"):
        service.import_observations(doc, ctx[1].pk)


def test_source_claim_never_becomes_authenticated_provider_proof(ctx):
    doc = document(ctx)
    result = service.import_observations(doc, ctx[1].pk, apply=True)
    assert result["source_provenance"] == "unverified_source_claim"
    assert TikTokDatasetStageRecord.objects.get().payload["provenance"]["status"] == "unverified_source_claim"
    assert TikTokDatasetStagePartition.objects.get().evidence["source_provenance"] == "unverified_source_claim"


def test_capture_time_and_page_bounds(ctx):
    doc = document(ctx)
    doc["observed_at"] = "2026-01-01T00:00:00Z"
    with pytest.raises(service.DatasetImportError, match="capture_before_day_completed"):
        service.import_observations(doc, ctx[1].pk)
    doc = document(ctx)
    doc["rows"][0]["affiliate_observed_at"] = "2026-01-02T23:59:59+08:00"
    with pytest.raises(service.DatasetImportError, match="observation_before_capture"):
        service.import_observations(doc, ctx[1].pk)
    doc = document(ctx)
    doc["evidence"]["page_count"] = 101
    with pytest.raises(service.DatasetImportError, match="page_limit_exceeded"):
        service.import_observations(doc, ctx[1].pk)


def test_advertiser_midnight_is_an_independent_capture_boundary(ctx):
    doc, mapping = ads_document(ctx)
    doc["observed_at"] = "2026-01-03T01:00:00+08:00"
    with pytest.raises(service.DatasetImportError, match="capture_before_advertiser_day_completed"):
        service.import_observations(doc, ctx[1].pk)
