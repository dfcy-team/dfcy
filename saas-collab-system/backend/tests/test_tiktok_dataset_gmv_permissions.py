"""Synthetic Stage API authorization; no collection, credentials or live DB."""

from datetime import UTC, date, datetime
import socket

import pytest
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.accounts.models import CustomUser
from apps.influencers.models import TikTokDatasetStageBatch, TikTokDatasetStagePartition, TikTokDatasetStageRecord
from apps.influencers.tiktok_dataset_api import TikTokDatasetQualityView
from apps.integrations import ads_sync
from apps.integrations.models import PlatformIntegrationConfig, TikTokAdsAdvertiserMapping, authorization_service_write
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def ctx(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No network, custody or live bound-evidence checks")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(ads_sync, "bound_evidence", forbidden)
    tenant = Tenant.objects.create(code="gmv-read-test", name="Synthetic read permissions")
    actor = CustomUser.objects.create_user(username="gmv-reader", tenant=tenant, user_type="internal")
    platform = PlatformMaster.objects.create(tenant=tenant, code="tk-read", name="Synthetic", platform_type="tiktok")
    stores = [StoreMaster.objects.create(tenant=tenant, platform=platform, code=f"READ{n}", name="Synthetic",
              country_code="PH", currency="PHP", timezone="Asia/Manila") for n in range(2)]
    with authorization_service_write():
        config = PlatformIntegrationConfig.objects.create(tenant=tenant, created_by=actor, platform="tiktok",
            account_alias="Synthetic Ads", environment="pilot", status="verified", sync_write_enabled=False,
            platform_config={"api_type": "advertising"})
    mappings = [TikTokAdsAdvertiserMapping.objects.create(tenant=tenant, store=store, integration_config=config,
                advertiser_id=str(100 + n), token_id="tok_" + str(n + 1) * 32, currency="USD", timezone="UTC",
                enabled=False) for n, store in enumerate(stores)]

    def grant(code, scope_type="all", scope=None):
        role, _ = Role.objects.get_or_create(tenant=tenant, code=code, defaults={"name": code})
        UserRole.objects.get_or_create(tenant=tenant, user=actor, role=role)
        permission, _ = Permission.objects.get_or_create(code=code, defaults={"name": code, "module": "test", "action": "view"})
        role.permissions.add(permission)
        DataScope.objects.update_or_create(tenant=tenant, role=role,
                                          defaults={"scope_type": scope_type, "config": scope or {"all": True}})

    grant("influencers.view")
    sequence = 0

    def batch(kind="gmv_max", mapping=None, evidence=None, store=None):
        nonlocal sequence
        sequence += 1
        mapping = mapping or mappings[0]
        store = store or mapping.store
        item = TikTokDatasetStageBatch.objects.create(tenant=tenant, store=store, created_by=actor,
            manifest_digest=f"{sequence:064x}", schema_version=1, window_start=date(2026, 1, 2),
            window_end=date(2026, 1, 2), source_created_at=datetime(2026, 1, 3, tzinfo=UTC), store_identity={"store_code": store.code})
        meta = {"mapping_id": mapping.pk, "advertiser_id": mapping.advertiser_id,
                "currency": mapping.currency, "timezone": mapping.timezone} if evidence is None else evidence
        partition = TikTokDatasetStagePartition.objects.create(tenant=tenant, batch=item, kind=kind,
            partition_date=date(2026, 1, 2), quality="partial" if kind == "gmv_max" else "complete",
            observed_count=1, expected_count=2, rejected_count=1 if kind == "gmv_max" else 0,
            import_status="pending" if kind == "gmv_max" else "completed", evidence=meta)
        TikTokDatasetStageRecord.objects.create(tenant=tenant, partition=partition,
            record_type="gmv_max_campaign" if kind == "gmv_max" else "legacy", record_key="a" * 64,
            payload_hash="b" * 64, payload={"cost": "92.26"} if kind == "gmv_max" else {"legacy": True})
        return item, partition

    def get(batch_id=None, partition_id=None):
        request = APIRequestFactory().get("/synthetic-stage/", {"partition_id": partition_id} if partition_id else {})
        force_authenticate(request, user=actor)
        return TikTokDatasetQualityView.as_view()(request, **({"batch_id": batch_id} if batch_id else {}))

    return tenant, actor, stores, mappings, grant, batch, get


def assert_hidden(ctx, item, partition):
    get = ctx[-1]
    listing = get()
    assert listing.status_code == 200
    data = listing.data["data"]
    assert data["batch_count"] == 1 and len(data["results"]) == 1
    assert data["results"][0]["id"] != item.pk
    assert all(data[key] == 0 for key in ("partial", "failed", "pending", "rejected"))
    assert get(item.pk).status_code == 404
    assert get(item.pk, partition.pk).status_code == 404
    assert "92.26" not in str(listing.data)


@pytest.mark.parametrize("grants", [(), ("analytics.view",), ("integrations.store.view",)])
def test_missing_action_hides_list_summary_detail_and_records(ctx, grants):
    *_, grant, batch, get = ctx
    batch("creators")
    item, partition = batch()
    for code in grants:
        grant(code)
    assert_hidden(ctx, item, partition)


def test_correct_intersection_reads_disabled_historical_mapping_without_live_evidence(ctx):
    tenant, actor, stores, mappings, grant, batch, get = ctx
    grant("integrations.store.view", "custom", {"store_ids": [stores[0].pk]})
    grant("analytics.view", "custom", {"analytics_dimensions": [
        {"platform": "tiktok", "store_id": str(stores[0].pk), "country": "PH"}]})
    item, partition = batch()
    assert not mappings[0].enabled
    data = get().data["data"]
    assert data["batch_count"] == data["partial"] == data["pending"] == data["rejected"] == 1
    assert get(item.pk).status_code == 200
    response = get(item.pk, partition.pk)
    assert response.status_code == 200
    assert response.data["data"]["records"][0]["payload"]["cost"] == "92.26"


@pytest.mark.parametrize("denied_scope", ["ads", "analytics", "country"])
def test_actions_without_matching_scope_do_not_reveal_batches(ctx, denied_scope):
    tenant, actor, stores, mappings, grant, batch, get = ctx
    grant("integrations.store.view", "custom", {"store_ids": [stores[denied_scope == "ads"].pk]})
    grant("analytics.view", "custom", {"analytics_dimensions": [{"platform": "tiktok",
        "store_id": str(stores[denied_scope == "analytics"].pk), "country": "MY" if denied_scope == "country" else "PH"}]})
    batch("creators")
    item, partition = batch()
    assert_hidden(ctx, item, partition)


@pytest.mark.parametrize("evidence", [[], "invalid", {}, {"mapping_id": True}, {"mapping_id": "1"},
    {"mapping_id": 2**80}, {"mapping_id": 999999}, {"mapping_id": 1, "advertiser_id": "wrong"}])
def test_malformed_or_unknown_mapping_evidence_fails_closed(ctx, evidence):
    *_, grant, batch, get = ctx
    grant("integrations.store.view")
    grant("analytics.view")
    batch("creators")
    item, partition = batch(evidence=evidence)
    assert_hidden(ctx, item, partition)


@pytest.mark.parametrize("field", ["advertiser_id", "currency", "timezone"])
def test_mismatched_or_missing_mapping_fields_fail_closed(ctx, field):
    tenant, actor, stores, mappings, grant, batch, get = ctx
    grant("integrations.store.view")
    grant("analytics.view")
    batch("creators")
    evidence = {"mapping_id": mappings[0].pk, "advertiser_id": mappings[0].advertiser_id,
                "currency": "USD", "timezone": "UTC"}
    evidence.pop(field)
    item, partition = batch(evidence=evidence)
    assert_hidden(ctx, item, partition)


def test_mapping_from_other_store_is_not_accepted(ctx):
    tenant, actor, stores, mappings, grant, batch, get = ctx
    grant("integrations.store.view")
    grant("analytics.view")
    batch("creators")
    item, partition = batch(mapping=mappings[1], store=stores[0])
    assert_hidden(ctx, item, partition)


def test_same_store_other_advertising_config_is_not_visible(ctx):
    tenant, actor, stores, mappings, grant, batch, get = ctx
    grant("integrations.store.view", "custom", {"integration_config_ids": [mappings[0].integration_config_id]})
    grant("analytics.view")
    with authorization_service_write():
        config = PlatformIntegrationConfig.objects.create(tenant=tenant, created_by=actor, platform="tiktok",
            account_alias="Other synthetic Ads", environment="pilot", status="verified",
            platform_config={"api_type": "advertising"}, sync_write_enabled=False)
    mapping = TikTokAdsAdvertiserMapping.objects.create(tenant=tenant, store=stores[0], integration_config=config,
        advertiser_id="999", token_id="tok_" + "c" * 32, currency="USD", timezone="UTC")
    batch("creators")
    item, partition = batch(mapping=mapping)
    assert_hidden(ctx, item, partition)


def test_any_hidden_gmv_partition_excludes_whole_mixed_batch(ctx):
    tenant, actor, stores, mappings, grant, batch, get = ctx
    grant("integrations.store.view")
    grant("analytics.view")
    batch("creators")
    item, partition = batch()
    TikTokDatasetStagePartition.objects.create(tenant=tenant, batch=item, kind="gmv_max",
        partition_date=date(2026, 1, 1), quality="partial", evidence={"mapping_id": 999999})
    TikTokDatasetStagePartition.objects.create(tenant=tenant, batch=item, kind="creators",
        partition_date=date(2026, 1, 2), quality="complete")
    assert_hidden(ctx, item, partition)


def test_legacy_visibility_and_bd_record_gates_are_unchanged(ctx):
    *_, grant, batch, get = ctx
    legacy = []
    for kind in ("affiliate_orders", "videos", "creators"):
        item, partition = batch(kind)
        legacy.append((item, partition))
        assert get(item.pk).status_code == 200
        assert get(item.pk, partition.pk).status_code == (200 if kind == "creators" else 403)
    grant("influencers.outreach.view")
    grant("influencers.fulfillment.view")
    assert get().data["data"]["batch_count"] == 3
    for item, partition in legacy:
        assert get(item.pk, partition.pk).status_code == 200


def test_cross_tenant_batch_is_always_not_found(ctx):
    tenant, actor, stores, mappings, grant, batch, get = ctx
    grant("integrations.store.view")
    grant("analytics.view")
    item, partition = batch()
    other = Tenant.objects.create(code="gmv-read-other", name="Synthetic other")
    outsider = CustomUser.objects.create_user(username="gmv-outsider", tenant=other, user_type="internal", is_superuser=True)
    request = APIRequestFactory().get("/synthetic-stage/", {"partition_id": partition.pk})
    force_authenticate(request, user=outsider)
    response = TikTokDatasetQualityView.as_view()(request, batch_id=item.pk)
    assert response.status_code == 404
