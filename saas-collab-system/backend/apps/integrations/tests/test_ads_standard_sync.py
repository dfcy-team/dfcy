"""Synthetic-only Ads contracts. No custody, socket, or production DB access."""
import json
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as ModelValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.tenants.models import Tenant
from apps.integrations import ads_sync, ads_subject, ads_capability_api, tiktok_ads_pilot as pilot
from apps.integrations.models import (
    AdsOAuthSession, IntegrationAuditLog, PlatformIntegrationConfig, SyncCheckpoint, SyncJob,
    SyncRun, SyncScheduleDispatch, TikTokAdsAdvertiserMapping, TikTokAdsDailySpend,
    TikTokAdsSyncLease, authorization_service_write,
)
from apps.integrations.serializers import SyncJobSerializer
from apps.integrations.sync_services import enqueue_sync_run, run_sync_job

pytestmark = pytest.mark.django_db


class Http:
    def __init__(self, *, spend="0", missing_day=None, fail_once=False, hook=None, bad_metadata=False):
        self.calls = []
        self.spend, self.missing_day, self.fail_once = spend, missing_day, fail_once
        self.hook, self.bad_metadata = hook, bad_metadata

    def request(self, method, url, **kwargs):
        assert method == "GET"
        self.calls.append(url)
        query = parse_qs(urlparse(url).query)
        if urlparse(url).path == pilot.INFO_PATH:
            data = {"list": [{"advertiser_id": json.loads(query["advertiser_ids"][0])[0],
                "currency": "EUR" if self.bad_metadata else "USD", "timezone": "UTC"}]}
        else:
            assert query["report_type"] == ["BASIC"] and query["data_level"] == ["AUCTION_CAMPAIGN"]
            assert query["metrics"] == ['["spend"]']
            assert query["start_date"] == query["end_date"]
            if self.fail_once:
                self.fail_once = False
                raise TimeoutError("synthetic transient failure")
            if self.hook:
                hook, self.hook = self.hook, None
                hook()
            missing = query["start_date"][0] == self.missing_day
            data = {"page_info": {"total_page": 0 if missing else 1, "page": 1,
                                  "total_number": 0 if missing else 1},
                    "list": [] if missing else [{"dimensions": {"campaign_id": "123"}, "metrics": {"spend": self.spend}}]}
        return SimpleNamespace(json=lambda: {"code": 0, "data": data})


@pytest.fixture
def ctx(monkeypatch):
    monkeypatch.setattr(ads_sync, "is_module_enabled", lambda *a: True)
    monkeypatch.setattr(ads_sync, "require_live_mode", lambda *a: None)
    monkeypatch.setattr(ads_sync, "get_runtime_setting", lambda *a, **kw: True)
    monkeypatch.setattr(ads_sync, "get_runtime_platform_config", lambda *a: {"contract_approved": True})
    monkeypatch.setattr(ads_sync, "configuration_digest", lambda c: f"synthetic-config-{c.pk}-{c.config_version}")
    monkeypatch.setattr(pilot.PlatformHttpClient, "request", Mock(side_effect=AssertionError("No real network allowed")))
    custody = Mock()
    custody.retrieve_access_token.return_value = "SYNTHETIC_ONLY"
    monkeypatch.setattr(pilot, "get_custody_backend", lambda: custody)
    tenant = Tenant.objects.create(code="ads-synthetic-one", name="Synthetic one")
    actor = get_user_model().objects.create_user(username="ads-synthetic", tenant=tenant,
        user_type="internal", is_superuser=True, is_staff=True)
    platform = PlatformMaster.objects.create(tenant=tenant, code="tk-test", name="Synthetic TK", platform_type="tiktok")
    with authorization_service_write():
        config = PlatformIntegrationConfig.objects.create(tenant=tenant, created_by=actor, platform="tiktok",
            account_alias="Synthetic Ads", environment="pilot", status="verified", network_enabled=True,
            sync_read_enabled=True, sync_write_enabled=False, credential_id="cre_" + "a" * 32,
            credential_status="configured", contract_version="synthetic-contract", platform_config={"api_type": "advertising"})
    stores, mappings = [], []
    for n in range(2):
        store = StoreMaster.objects.create(tenant=tenant, platform=platform, code=f"TEST{n}", name=f"Synthetic store {n}",
            country_code="US", currency="USD", timezone="UTC")
        stores.append(store)
        for account in range(2):
            mapping = TikTokAdsAdvertiserMapping.objects.create(tenant=tenant, store=store, integration_config=config,
                advertiser_id=str(1000 + n * 10 + account), token_id="tok_" + "b" * 32,
                currency="USD", timezone="UTC", enabled=True)
            mappings.append(mapping)
    session = AdsOAuthSession.objects.create(tenant=tenant, actor=actor, store=stores[0], integration_config=config,
        status="bound", state_hash="c" * 64, config_fingerprint=ads_sync.configuration_digest(config),
        expires_at=timezone.now() + timedelta(minutes=5), credential_id="cre_" + "d" * 32, token_id=mappings[0].token_id,
        candidates=[{"advertiser_id": m.advertiser_id, "currency": "USD", "timezone": "UTC",
                     "verify_state": "verified", "verified_at": timezone.now().isoformat()} for m in mappings[:2]],
        binding_results=[{"mapping_id": m.pk, "advertiser_id": m.advertiser_id} for m in mappings[:2]])
    AdsOAuthSession.objects.create(tenant=tenant, actor=actor, store=stores[1], integration_config=config,
        status="bound", state_hash="e" * 64, config_fingerprint=session.config_fingerprint,
        expires_at=session.expires_at, credential_id=session.credential_id, token_id=session.token_id,
        candidates=[{"advertiser_id": m.advertiser_id, "currency": "USD", "timezone": "UTC",
                     "verify_state": "verified", "verified_at": timezone.now().isoformat()} for m in mappings[2:]],
        binding_results=[{"mapping_id": m.pk, "advertiser_id": m.advertiser_id} for m in mappings[2:]])
    job = SyncJob.objects.create(tenant=tenant, integration_config=config, ads_mapping=mappings[0],
        resource_type="advertising_report", is_enabled=True, status="idle", max_retry_count=0,
        sync_scope={"execution_mode": "live_readonly", "query": {"mode": "range", "start_at": "2026-09-22", "end_at": "2026-09-28"}})
    return SimpleNamespace(tenant=tenant, actor=actor, stores=stores, mappings=mappings, config=config, job=job,
                           session=session, custody=custody, monkeypatch=monkeypatch)


def execute(ctx, http=None, **kwargs):
    ctx.monkeypatch.setattr(pilot, "PlatformHttpClient", lambda: http or Http())
    return run_sync_job(ctx.job, idempotency_key=kwargs.pop("idempotency_key", "synthetic-run"), retry_wait=lambda _: None, **kwargs)[0]


def api(view, ctx, method="get", data=None, **kwargs):
    request = getattr(APIRequestFactory(), method)("/synthetic/", data=data, format="json")
    force_authenticate(request, user=ctx.actor)
    return view(request, **kwargs)


def test_verified_zero_complete_window_is_success(ctx):
    run = execute(ctx)
    assert run.status == "success" and run.created_count == 7 and run.failed_count == 0
    assert set(TikTokAdsDailySpend.objects.values_list("spend", flat=True)) == {Decimal("0")}
    assert SyncCheckpoint.objects.get(sync_job=ctx.job).last_success_run_id == run.pk
    assert run.masked_log["runtime_budget"]["resolved_scope"]["report_scope"] == "AUCTION_CAMPAIGN"
    assert run.raw_envelopes.get().store_id == ctx.stores[0].pk
    assert "tok_" not in str(run.masked_log) and "SYNTHETIC_ONLY" not in str(run.masked_log)


def test_missing_is_unknown_not_zero_and_rolls_back_whole_window(ctx):
    run = execute(ctx, Http(missing_day="2026-09-28"))
    assert run.status == "failed" and run.created_count == 0
    assert not TikTokAdsDailySpend.objects.exists() and not SyncCheckpoint.objects.exists()
    assert not run.raw_envelopes.exists()


@pytest.mark.parametrize("spend", [None, True, "NaN", "-1", "1.1234567", "100000000000000"])
def test_invalid_spend_never_advances_checkpoint(ctx, spend):
    assert execute(ctx, Http(spend=spend)).status == "failed"
    assert not TikTokAdsDailySpend.objects.exists() and not SyncCheckpoint.objects.exists()


def test_current_account_metadata_is_required(ctx):
    assert execute(ctx, Http(bad_metadata=True)).status == "failed"
    assert not TikTokAdsDailySpend.objects.exists()


@pytest.mark.parametrize("switch", ["mapping", "config", "token", "session", "store", "lease"])
def test_concurrent_approval_changes_abort_complete_window(ctx, switch):
    def change():
        if switch == "mapping":
            TikTokAdsAdvertiserMapping.objects.filter(pk=ctx.job.ads_mapping_id).update(enabled=False)
        elif switch == "config":
            PlatformIntegrationConfig.objects.filter(pk=ctx.config.pk).update(sync_read_enabled=False)
        elif switch == "token":
            TikTokAdsAdvertiserMapping.objects.filter(pk=ctx.job.ads_mapping_id).update(token_id="tok_" + "f" * 32)
        elif switch == "session":
            AdsOAuthSession.objects.filter(pk=ctx.session.pk).update(status="failed")
        elif switch == "store":
            StoreMaster.objects.filter(pk=ctx.stores[0].pk).update(status="inactive")
        else:
            TikTokAdsSyncLease.objects.filter(tenant=ctx.tenant).update(generation=999)
    run = execute(ctx, Http(hook=change))
    assert run.status == "failed"
    assert not TikTokAdsDailySpend.objects.exists() and not SyncCheckpoint.objects.exists()


def test_mid_upsert_failure_rolls_back_existing_and_new_rows(ctx, monkeypatch):
    old = TikTokAdsDailySpend.objects.create(tenant=ctx.tenant, mapping=ctx.mappings[0], date="2026-09-22", spend="9", currency="USD")
    original = TikTokAdsDailySpend.objects.update_or_create
    def fail_second(*args, **kwargs):
        if kwargs["date"] == "2026-09-23":
            raise ValidationError("synthetic persistence failure")
        return original(*args, **kwargs)
    monkeypatch.setattr(TikTokAdsDailySpend.objects, "update_or_create", fail_second)
    assert execute(ctx).status == "failed"
    old.refresh_from_db()
    assert old.spend == Decimal("9") and TikTokAdsDailySpend.objects.count() == 1
    assert not SyncCheckpoint.objects.exists()


def test_pilot_tenant_lease_blocks_standard_job(ctx):
    owner, generation = pilot._claim_lease(ctx.tenant.pk)
    run = execute(ctx)
    assert run.status == "queued" and run.error_code == "ADS_LEASE_BUSY" and run.retry_count == 0
    assert not TikTokAdsDailySpend.objects.exists()
    lease = TikTokAdsSyncLease.objects.get(tenant=ctx.tenant)
    assert (lease.owner_token, lease.generation) == (owner, generation)


def test_standard_lease_blocks_pilot_and_other_accounts(ctx):
    def competing():
        with pytest.raises(ModelValidationError):
            pilot._claim_lease(ctx.tenant.pk)
    assert execute(ctx, Http(hook=competing)).status == "success"
    owner, generation = pilot._claim_lease(ctx.tenant.pk)
    pilot._release_lease(ctx.tenant.pk, owner, generation)


def test_retry_keeps_enqueued_dates_without_mutating_recurring_policy(ctx):
    ctx.job.max_retry_count = 1
    ctx.job.sync_scope = {"execution_mode": "live_readonly", "query": {"mode": "incremental", "lookback_days": 7}}
    ctx.job.save()
    queued, _ = enqueue_sync_run(ctx.job, "frozen-enqueue")
    frozen = ads_sync.resolve_scope(ctx.mappings[0], {"query": {"mode": "range", "start_at": "2026-09-22", "end_at": "2026-09-28"}})
    queued.masked_log["runtime_budget"]["resolved_scope"] = frozen
    queued.save()
    http = Http(fail_once=True)
    run = execute(ctx, http, idempotency_key="frozen-enqueue")
    assert run.status == "success" and run.retry_count == 1
    days = [parse_qs(urlparse(u).query)["start_date"][0] for u in http.calls if "report/integrated" in u]
    assert set(days) == {f"2026-09-{d}" for d in range(22, 29)}
    ctx.job.refresh_from_db()
    assert ctx.job.sync_scope["query"] == {"mode": "incremental", "lookback_days": 7}


@pytest.mark.parametrize("lookback", [0, 8, True, 1.5, "7"])
def test_invalid_incremental_dates(ctx, lookback):
    with pytest.raises(ValidationError):
        ads_sync.resolve_scope(ctx.mappings[0], {"query": {"lookback_days": lookback}})


@pytest.mark.parametrize("start,end", [("2026-09-21", "2026-09-28"), ("2026-09-29", "2026-09-28"),
    ("2026-09-29", "2026-09-29"), ("2026-09-22T00:00:00Z", "2026-09-28"), ("20260922", "2026-09-28")])
def test_invalid_explicit_dates(ctx, start, end):
    with pytest.raises(ValidationError):
        ads_sync.resolve_scope(ctx.mappings[0], {"query": {"mode": "range", "start_at": start, "end_at": end}},
                               now=datetime(2026, 9, 29, tzinfo=dt_timezone.utc))


def test_date_default_uses_advertiser_local_completed_days(ctx):
    ctx.mappings[0].timezone = "America/Los_Angeles"
    result = ads_sync.resolve_scope(ctx.mappings[0], now=datetime(2026, 9, 29, 1, tzinfo=dt_timezone.utc))
    assert result["time_to"] == "2026-09-27" and result["time_from"] == "2026-09-21"


def test_api_default_off_multiaccount_contract(ctx):
    from apps.integrations.views import sync_job_collection
    mapping = ctx.mappings[1]
    response = api(sync_job_collection, ctx, "post", {"integration_config_id": ctx.config.pk,
        "ads_mapping_id": mapping.pk, "resource_type": "advertising_report", "schedule_type": "manual",
        "is_enabled": False, "execution_mode": "live_readonly", "query_mode": "incremental", "lookback_days": 7})
    assert response.status_code == 201, response.data
    job = SyncJob.objects.get(ads_mapping=mapping)
    assert not job.is_enabled and job.status == "disabled" and job.schedule_type == "manual"
    assert job.sync_scope["query"] == {"mode": "incremental", "lookback_days": 7}
    response = api(sync_job_collection, ctx)
    assert response.status_code == 200
    rows = response.data["data"]
    assert len(rows) == 2 and {r["ads_mapping_id"] for r in rows} == {m.pk for m in ctx.mappings[:2]}
    assert rows[0]["subject_key"] == rows[1]["subject_key"] == f"store:{mapping.store_id}"
    assert "tok_" not in str(rows) and "cre_" not in str(rows)


def test_duplicate_mapping_job_is_rejected(ctx):
    serializer = SyncJobSerializer(data={"integration_config_id": ctx.config.pk, "ads_mapping_id": ctx.mappings[0].pk,
        "resource_type": "advertising_report"}, context={"request": SimpleNamespace(user=ctx.actor)})
    assert not serializer.is_valid()
    with pytest.raises(IntegrityError), transaction.atomic():
        SyncJob.objects.create(tenant=ctx.tenant, integration_config=ctx.config, ads_mapping=ctx.mappings[0],
                               resource_type="advertising_report")


def test_new_jobs_cannot_start_enabled_or_scheduled(ctx):
    for values in ({"is_enabled": True}, {"schedule_type": "daily"}):
        serializer = SyncJobSerializer(data={"integration_config_id": ctx.config.pk, "ads_mapping_id": ctx.mappings[1].pk,
            "resource_type": "advertising_report", **values}, context={"request": SimpleNamespace(user=ctx.actor)})
        assert not serializer.is_valid()


@pytest.mark.parametrize("values", [{"ads_mapping_id": None}, {"resource_type": "sales_order"},
    {"ads_mapping_id": -1}, {"ads_mapping_id": True}, {"store_authorization_id": 123}, {"warehouse_authorization_id": 123},
    {"store_id": 123}, {"advertiser_id": "999"}, {"subject_key": "store:999"}])
def test_subject_changes_and_spoofing_rejected(ctx, values):
    serializer = SyncJobSerializer(ctx.job, data=values, partial=True,
                                  context={"request": SimpleNamespace(user=ctx.actor)})
    assert not serializer.is_valid()


def test_cross_tenant_and_other_store_mapping_ids_rejected(ctx, monkeypatch):
    other = Tenant.objects.create(code="ads-synthetic-other", name="Other synthetic")
    other_actor = get_user_model().objects.create_user(username="ads-other", tenant=other, user_type="internal", is_superuser=True)
    serializer = SyncJobSerializer(data={"integration_config_id": ctx.config.pk, "ads_mapping_id": ctx.mappings[1].pk,
        "resource_type": "advertising_report"}, context={"request": SimpleNamespace(user=other_actor)})
    assert not serializer.is_valid()
    monkeypatch.setattr(ads_subject.scopes, "integration_values_allowed",
                        lambda user, code, **kw: kw.get("store_id") == ctx.stores[0].pk)
    serializer = SyncJobSerializer(data={"integration_config_id": ctx.config.pk, "ads_mapping_id": ctx.mappings[2].pk,
        "resource_type": "advertising_report"}, context={"request": SimpleNamespace(user=ctx.actor)})
    assert not serializer.is_valid()
    SyncJob.objects.create(tenant=ctx.tenant, integration_config=ctx.config, ads_mapping=ctx.mappings[2], resource_type="advertising_report")
    assert list(ads_subject.filter_sync_jobs(ctx.actor, SyncJob.objects.all(), "integrations.view")) == [ctx.job]
    assert not ads_subject.filter_sync_jobs(other_actor, SyncJob.objects.all(), "integrations.view").exists()


def test_capability_can_enable_ignores_current_disabled_switch_and_get_has_no_network(ctx):
    mapping = ctx.mappings[0]
    TikTokAdsAdvertiserMapping.objects.filter(pk=mapping.pk).update(enabled=False)
    response = api(ads_capability_api.capabilities, ctx)
    assert response.status_code == 200
    row = next(r for r in response.data["data"]["items"] if r["mapping_id"] == mapping.pk)
    assert row["can_enable_read"] and not row["read_enabled"] and row["verification_state"] == "verified"
    assert row["existing_job_id"] == ctx.job.pk and row["job_enabled"]
    assert "tok_" not in str(response.data) and "cre_" not in str(response.data)
    ctx.custody.retrieve_access_token.assert_not_called()
    response = api(ads_capability_api.capability, ctx, "put", {"read_enabled": True}, pk=mapping.pk)
    assert response.status_code == 200 and response.data["data"]["read_enabled"]
    assert IntegrationAuditLog.objects.filter(action="ads_read_capability").count() == 1


def test_disabling_capability_always_possible_when_config_invalid(ctx):
    PlatformIntegrationConfig.objects.filter(pk=ctx.config.pk).update(sync_read_enabled=False)
    response = api(ads_capability_api.capability, ctx, "put", {"read_enabled": False}, pk=ctx.mappings[0].pk)
    assert response.status_code == 200 and not response.data["data"]["read_enabled"]
    response = api(ads_capability_api.capability, ctx, "put", {"read_enabled": True}, pk=ctx.mappings[0].pk)
    assert response.status_code == 400


@pytest.mark.parametrize("data", [{}, {"read_enabled": 1}, {"read_enabled": "true"},
    {"read_enabled": False, "write_enabled": False}, {"read_enabled": None}])
def test_capability_put_strict_input(ctx, data):
    assert api(ads_capability_api.capability, ctx, "put", data, pk=ctx.mappings[0].pk).status_code == 400


def test_missing_preview_has_one_row_per_account_no_marketplace_spoof(ctx):
    from apps.integrations.missing_jobs import preview_missing_jobs
    rows = preview_missing_jobs(ctx.actor, include_existing=True)["items"]
    assert len(rows) == 4 and {r["ads_mapping_id"] for r in rows} == {m.pk for m in ctx.mappings}
    assert all(r["authorization_id"] is None and r["subject_type"] == "store" and not r["blockers"] for r in rows)
    assert len(preview_missing_jobs(ctx.actor)["items"]) == 3


def test_credential_coordination_never_refreshes_shop_for_ads(ctx, monkeypatch):
    from apps.integrations import credential_coordination
    monkeypatch.setattr(credential_coordination, "credential_refresh_state", Mock(side_effect=AssertionError("Shop refresh forbidden")))
    assert credential_coordination.job_refresh_wait(ctx.job) is None


def test_scheduled_dispatch_scope_is_frozen_before_worker(ctx):
    from apps.integrations.scheduler import dispatch_due_jobs
    now = timezone.now()
    ctx.job.schedule_type = "interval"
    ctx.job.next_run_at = now
    ctx.job.save()
    submitted = []
    result = dispatch_due_jobs(lambda *args: submitted.append(args), now=now)
    assert result["dispatched"] == 1 and len(submitted) == 1
    dispatch = SyncScheduleDispatch.objects.get(sync_job=ctx.job)
    assert dispatch.schedule_snapshot["ads_scope"]["time_from"] == "2026-09-22"
    dispatch.status = "running"
    dispatch.save()
    assert execute(ctx, dispatch=dispatch).status == "success"


def test_ordinary_adapter_and_model_defaults_unchanged(ctx):
    from apps.integrations.adapters import get_adapter_for_config, MockPlatformAdapter
    from apps.integrations.shopee_advertising import ShopeeAdvertisingAdapter
    from apps.integrations.platform_capabilities import supports_resource
    assert SyncJob._meta.get_field("is_enabled").default is True
    assert SyncJob(tenant=ctx.tenant, integration_config=ctx.config, ads_mapping=ctx.mappings[1],
                   resource_type="advertising_report").is_enabled is False
    assert supports_resource("shopee", "advertising_report", "live_readonly")
    assert not supports_resource("lazada", "advertising_report", "live_readonly")
    assert isinstance(get_adapter_for_config(SimpleNamespace(environment="mock", platform="mock"), "mock_record"), MockPlatformAdapter)
    assert isinstance(get_adapter_for_config(SimpleNamespace(environment="pilot", platform="shopee", platform_config={}), "advertising_report"), ShopeeAdvertisingAdapter)


@pytest.mark.parametrize("info", [{"total_page": 1.5}, {"total_page": True}, {"total_page": 1, "page": 2},
    {"total_page": 1, "total_number": 2}, {"total_page": 2}, {"total_page": 1, "total_number": -1}])
def test_malformed_or_incomplete_pagination_is_not_a_complete_day(ctx, monkeypatch, info):
    monkeypatch.setattr(pilot, "_get", lambda *args: {"page_info": info,
        "list": [{"dimensions": {"campaign_id": "1"}, "metrics": {"spend": "0"}}]})
    with pytest.raises((ValidationError, ModelValidationError)):
        ads_sync.collect_day(None, ctx.mappings[0], "SYNTHETIC", datetime(2026, 9, 28).date(), lambda: None)


def test_exhaustive_paginated_day_and_duplicate_rejection(ctx, monkeypatch):
    def response(http, path, params, token):
        page = params["page"]
        ids = range(1, 1001) if page == 1 else [1001]
        return {"page_info": {"total_page": 2, "page": page, "total_number": 1001},
                "list": [{"dimensions": {"campaign_id": str(i)}, "metrics": {"spend": "0"}} for i in ids]}
    monkeypatch.setattr(pilot, "_get", response)
    assert ads_sync.collect_day(None, ctx.mappings[0], "SYNTHETIC", datetime(2026, 9, 28).date(), lambda: None) == Decimal("0")
    def duplicate(*args):
        data = response(*args)
        if args[2]["page"] == 2:
            data["list"][0]["dimensions"]["campaign_id"] = "1"
        return data
    monkeypatch.setattr(pilot, "_get", duplicate)
    with pytest.raises(ValidationError):
        ads_sync.collect_day(None, ctx.mappings[0], "SYNTHETIC", datetime(2026, 9, 28).date(), lambda: None)


def test_lease_expiration_during_upsert_rolls_back_entire_window(ctx, monkeypatch):
    original = TikTokAdsDailySpend.objects.update_or_create
    def expire(*args, **kwargs):
        result = original(*args, **kwargs)
        TikTokAdsSyncLease.objects.filter(tenant=ctx.tenant).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        return result
    monkeypatch.setattr(TikTokAdsDailySpend.objects, "update_or_create", expire)
    assert execute(ctx).status == "failed"
    assert not TikTokAdsDailySpend.objects.exists() and not SyncCheckpoint.objects.exists()


def test_database_subject_check_requires_exclusive_ads_mapping(ctx):
    # The database cannot join the config table to distinguish Shopee from TK.
    # TK's missing mapping is rejected by model and execution validation; the
    # shared nullable constraint must continue accepting existing Shopee jobs.
    with pytest.raises(ModelValidationError, match="Ads mapping"):
        SyncJob(tenant=ctx.tenant, integration_config=ctx.config, resource_type="advertising_report").full_clean()
    with pytest.raises(IntegrityError), transaction.atomic():
        SyncJob.objects.create(tenant=ctx.tenant, integration_config=ctx.config, ads_mapping=ctx.mappings[1], resource_type="sales_order")


@pytest.mark.parametrize("gate", ["mode", "runtime", "platform", "disabled", "unverified"])
def test_failed_preflight_never_resolves_custody_or_calls_network(ctx, monkeypatch, gate):
    if gate == "mode":
        monkeypatch.setattr(ads_sync, "require_live_mode", Mock(side_effect=ValidationError("synthetic live mode disabled")))
    elif gate == "runtime":
        monkeypatch.setattr(ads_sync, "get_runtime_setting", lambda *a, **kw: False)
    elif gate == "platform":
        monkeypatch.setattr(ads_sync, "get_runtime_platform_config", lambda *a: {})
    elif gate == "disabled":
        TikTokAdsAdvertiserMapping.objects.filter(pk=ctx.mappings[0].pk).update(enabled=False)
    else:
        AdsOAuthSession.objects.filter(pk=ctx.session.pk).update(candidates=[])
    with pytest.raises(ValidationError):
        execute(ctx)
    ctx.custody.retrieve_access_token.assert_not_called()
    assert not TikTokAdsDailySpend.objects.exists() and not SyncCheckpoint.objects.exists()


def test_schedule_preview_exposes_local_date_aliases(ctx):
    from apps.integrations.views import preview_sync_schedule
    response = api(preview_sync_schedule, ctx, "post", {"query_mode": "range",
        "range_start_at": "2026-09-22", "range_end_at": "2026-09-28"}, pk=ctx.job.pk)
    assert response.status_code == 200, response.data
    scope = response.data["data"]["collection_range"]
    assert scope["start_date"] == "2026-09-22" and scope["end_date"] == "2026-09-28"
    assert scope["advertiser_timezone"] == "UTC"


def test_second_tenant_has_independent_account_job_and_ads_lease(ctx):
    tenant = Tenant.objects.create(code="ads-second-tenant", name="Second synthetic tenant")
    actor = get_user_model().objects.create_user(username="ads-second-actor", tenant=tenant, user_type="internal", is_superuser=True)
    platform = PlatformMaster.objects.create(tenant=tenant, code="tk-second", name="Second", platform_type="tiktok")
    store = StoreMaster.objects.create(tenant=tenant, platform=platform, code="SECOND", name="Second", country_code="US")
    with authorization_service_write():
        config = PlatformIntegrationConfig.objects.create(tenant=tenant, created_by=actor, platform="tiktok", account_alias="Second Ads",
            environment="pilot", status="verified", network_enabled=True, sync_read_enabled=True, sync_write_enabled=False,
            credential_id="cre_" + "1" * 32, credential_status="configured", contract_version="synthetic",
            platform_config={"api_type": "advertising"})
    mapping = TikTokAdsAdvertiserMapping.objects.create(tenant=tenant, store=store, integration_config=config,
        advertiser_id=ctx.mappings[0].advertiser_id, token_id="tok_" + "2" * 32, currency="USD", timezone="UTC", enabled=True)
    AdsOAuthSession.objects.create(tenant=tenant, store=store, integration_config=config, actor=actor,
        state_hash="3" * 64, status="bound", config_fingerprint=ads_sync.configuration_digest(config),
        credential_id="cre_" + "4" * 32, token_id=mapping.token_id, expires_at=timezone.now(),
        candidates=[{"advertiser_id": mapping.advertiser_id, "currency": "USD", "timezone": "UTC", "verify_state": "verified",
                     "verified_at": timezone.now().isoformat()}], binding_results=[{"mapping_id": mapping.pk, "advertiser_id": mapping.advertiser_id}])
    job = SyncJob.objects.create(tenant=tenant, integration_config=config, ads_mapping=mapping,
        resource_type="advertising_report", is_enabled=True, max_retry_count=0, sync_scope=ctx.job.sync_scope)
    owner, generation = pilot._claim_lease(ctx.tenant.pk)
    ctx.monkeypatch.setattr(pilot, "PlatformHttpClient", lambda: Http())
    run, _ = run_sync_job(job, idempotency_key="tenant-two-synthetic")
    assert run.status == "success" and TikTokAdsDailySpend.objects.filter(tenant=tenant).count() == 7
    assert not TikTokAdsDailySpend.objects.filter(tenant=ctx.tenant).exists()
    assert list(ads_subject.filter_sync_jobs(actor, SyncJob.objects.all(), "integrations.view")) == [job]
    pilot._release_lease(ctx.tenant.pk, owner, generation)


@pytest.mark.parametrize("fault", ["missing_count", "disappearing_count", "wrong_page", "truncated_final"])
def test_rejected_report_keeps_existing_fact_and_entire_window(ctx, monkeypatch, fault):
    old = TikTokAdsDailySpend.objects.create(tenant=ctx.tenant, mapping=ctx.mappings[0],
        date="2026-09-22", spend="99", currency="USD")
    original_get = pilot._get
    monkeypatch.setattr(pilot, "REPORT_PAGE_SIZE", 2)
    def get(http, path, params, token):
        if path != pilot.REPORT_PATH or params["start_date"] != "2026-09-28":
            return original_get(http, path, params, token)
        page = params["page"]
        info = {"page": page, "total_page": 2, "total_number": 4 if fault == "truncated_final" else 3}
        if fault == "missing_count" or fault == "disappearing_count" and page == 2:
            info.pop("total_number")
        if fault == "wrong_page" and page == 2:
            info["page"] = 1
        return {"page_info": info, "list": [
            {"dimensions": {"campaign_id": str(i)}, "metrics": {"spend": "1"}}
            for i in ([1, 2] if page == 1 else [3])]}
    monkeypatch.setattr(pilot, "_get", get)
    run = execute(ctx, Http(spend="12.34"))
    assert run.status == "failed" and run.created_count == run.updated_count == 0
    old.refresh_from_db()
    assert old.spend == Decimal("99") and TikTokAdsDailySpend.objects.count() == 1
    assert not SyncCheckpoint.objects.exists() and not run.raw_envelopes.exists()


@pytest.mark.parametrize("enabled", [False, True])
def test_shopee_advertising_manual_enqueue_and_run_preserve_capability_gate(monkeypatch, enabled):
    from apps.integrations import sync_services
    from apps.integrations.models import ConnectionCapability, ShopeeAdvertisingRecord
    from apps.integrations.shopee_advertising import ShopeeAdvertisingAdapter
    from tests.test_sync_capability_gate import make_job
    from tests.test_shopee_advertising import (
        client, campaign_page, settings_page, performance_page, response,
    )
    job, auth = make_job()
    config = job.integration_config
    config.environment = "production"
    config.platform_config = {"api_type": "advertising"}
    config.save()
    job.resource_type = "advertising_report"
    job.sync_scope = {"query": {"mode": "range", "start_at": "2026-10-01", "end_at": "2026-10-07"}}
    job.save()
    instance = client()
    instance.authorization, instance.preflight = auth, Mock()
    pages = [campaign_page(), settings_page(), performance_page(),
             response([{"date": "01-10-2026", "expense": 12}]),
             response({"data_timestamp": 1790812800, "total_balance": 99})]
    for page in pages[:3]:
        body = page["response"]
        (body if isinstance(body, dict) else body[0])["shop_id"] = auth.platform_store_id
    instance._request.side_effect = pages
    adapter = ShopeeAdvertisingAdapter(config, client=instance)
    monkeypatch.setattr(sync_services, "get_adapter_for_config", lambda *a: adapter)
    if not enabled:
        with pytest.raises(ValidationError, match="CAPABILITY_NOT_ENABLED: ADVERTISING"):
            sync_services.validate_manual_sync_job(job)
        with pytest.raises(ValidationError, match="CAPABILITY_NOT_ENABLED: ADVERTISING"):
            run_sync_job(job, adapter=adapter)
        assert not SyncRun.objects.filter(sync_job=job).exists()
        instance._request.assert_not_called()
        return
    ConnectionCapability.objects.create(authorization=auth, capability_code="ADVERTISING",
        read_enabled=True, write_enabled=False, status="active")
    sync_services.validate_manual_sync_job(job)
    queued, created = enqueue_sync_run(job, "shopee-review-regression")
    assert created and queued.status == "queued"
    run, _ = run_sync_job(job, adapter=adapter, idempotency_key="shopee-review-regression")
    assert run.pk == queued.pk and run.status == "success"
    assert ShopeeAdvertisingRecord.objects.count() == 4
