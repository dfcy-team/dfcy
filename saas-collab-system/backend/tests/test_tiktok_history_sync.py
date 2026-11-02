from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from rest_framework.exceptions import ValidationError
from apps.integrations.history_sync import create_history_batch
from apps.integrations.models import HistorySyncBatch, SyncJob, TikTokAdsAdvertiserMapping
from apps.permissions.models import Permission, Role, UserRole, DataScope
from tests.test_shopee_tiktok_finance_ingestion import _finance_scope
from tests.test_history_sync_batches import ctx, payload
from tests import test_history_sync_batches as existing
from tests.test_sync_runtime_budget import empty_delivery_broker
from tests.test_phase2_sync_framework import authenticated_client

pytestmark = pytest.mark.django_db

@pytest.fixture
def tkctx():
    tenant, store, config, auth, job, run = _finance_scope("tiktok")
    run.delete()
    config.platform_config = {**(config.platform_config or {}), "api_type": "advertising"}
    config.save(update_fields=["platform_config"])
    user = config.created_by
    role = Role.objects.create(tenant=tenant, code="integration_admin", name="history-admin")
    role.permissions.add(*Permission.objects.filter(code__in=["integrations.history.view", "integrations.history.manage", "integrations.run_live_readonly"]))
    UserRole.objects.create(tenant=tenant, role=role, user=user)
    DataScope.objects.create(tenant=tenant, role=role, scope_type="all", config={})
    job.sync_scope = {"schedule": {"execution_budget_seconds": 480}, "query": {"mode": "incremental", "lookback_days": 1}}
    job.is_enabled = True
    job.status = "idle"
    job.save(update_fields=["sync_scope", "is_enabled", "status"])
    return user, job, role

@pytest.mark.parametrize('resource', ['sales_order','refund_return','settlement_bill'])
def test_tiktok_contiguous_bounded_frozen_scope_and_idempotency(tkctx, resource):
    user,job,_=tkctx
    job.resource_type=resource;job.save(update_fields=['resource_type'])
    original=job.sync_scope.copy()
    data=payload([job]);data.update(start_date='2026-09-01',end_date='2026-09-15')
    with patch('apps.integrations.history_sync.validate_manual_sync_job'):
        batch=create_history_batch(user,data)
        assert create_history_batch(user,data).pk==batch.pk
    segs=list(batch.segments.order_by('sequence'))
    assert len(segs)==3
    assert all(s.scope['page_size']==50 and s.scope['time_basis']=='created' for s in segs)
    assert sum(s.scope['time_to']-s.scope['time_from']+1 for s in segs)==15*86400
    assert all(s.scope['time_to']-s.scope['time_from']+1<=7*86400 for s in segs)
    assert all(b.scope['time_from']==a.scope['time_to']+1 for a,b in zip(segs,segs[1:]))
    job.refresh_from_db();assert job.sync_scope==original
    with pytest.raises(ValidationError):
        create_history_batch(user,{**data,'idempotency_key':'different'})

@pytest.mark.parametrize('resource',['advertising_report','platform_product','affiliate_order'])
def test_tiktok_unsupported_resource_atomic(tkctx,resource):
    user,job,_=tkctx;job.resource_type=resource;job.save(update_fields=['resource_type'])
    with patch('apps.integrations.history_sync.validate_manual_sync_job'),pytest.raises(ValidationError):
        create_history_batch(user,payload([job]))
    assert not HistorySyncBatch.objects.exists()

def test_tiktok_api_capability_and_job_option(tkctx):
    user,job,_=tkctx
    response=authenticated_client(user).get('/api/internal/integrations/history-batches/')
    assert response.status_code==200
    assert 'tiktok_backfill' in response.data['data']['features']
    assert any(j['id']==job.pk for j in response.data['data']['jobs'])

def test_tiktok_outbox_pause_resume(tkctx):
    existing.test_outbox_resubmits_same_key_and_pause_blocks_worker(tkctx)

def test_tiktok_permission_revocation(tkctx):
    existing.test_permission_revocation_blocks_queued_background_execution(tkctx)

def test_tiktok_history_cursor_kept_when_daily_changes(tkctx):
    existing.test_paused_history_preserves_cursor_when_editing_or_disabling_daily_job(tkctx)


def test_tiktok_budget_resume_and_daily_checkpoint_isolation(tkctx):
    existing.test_history_budget_resume_scope_and_default_checkpoint_isolation(tkctx)


def _tiktok_ads_job(tkctx, advertiser_id="123456"):
    user, job, _ = tkctx
    store = job.store_authorization.store
    mapping = TikTokAdsAdvertiserMapping.objects.create(tenant=job.tenant, store=job.store_authorization.store,
        integration_config=job.integration_config, advertiser_id=advertiser_id,
        token_id="tok_" + "1" * 32, currency="PHP", timezone="Asia/Manila")
    job.store_authorization = None
    job.resource_type = "advertising_report"
    job.ads_mapping = mapping
    job.sync_scope = {"schedule": {"execution_budget_seconds": 900},
        "query": {"mode": "range", "start_at": "2026-09-01", "end_at": "2026-09-02"}}
    job.save(update_fields=["store_authorization", "resource_type", "ads_mapping", "sync_scope"])
    return user, job, mapping


def test_tiktok_ads_history_mapping_scope_splits_completed_account_days(tkctx):
    from apps.integrations.history_sync import history_validation_job

    user, first, mapping = _tiktok_ads_job(tkctx)
    second_mapping = TikTokAdsAdvertiserMapping.objects.create(tenant=first.tenant, store=mapping.store,
        integration_config=first.integration_config, advertiser_id="654321",
        token_id="tok_" + "2" * 32, currency="PHP", timezone="Asia/Manila")
    second = SyncJob.objects.create(tenant=first.tenant, integration_config=first.integration_config,
        resource_type="advertising_report", ads_mapping=second_mapping, sync_scope=first.sync_scope.copy(),
        is_enabled=True, status="idle")
    data = {"name": "TK Ads October", "job_ids": [first.pk, second.pk], "start_date": "2026-10-01",
        "end_date": "2026-10-24", "idempotency_key": "tk-ads-history-202610"}
    now = datetime(2026, 10, 25, 12, tzinfo=UTC)
    with patch("apps.integrations.history_sync.timezone.now", return_value=now), \
         patch("apps.integrations.history_sync.validate_manual_sync_job"):
        batch = create_history_batch(user, data)
    segments = list(batch.segments.select_related("sync_job").order_by("sync_job_id", "sequence"))
    assert len(segments) == 8
    assert all(segment.sync_job.ads_mapping_id for segment in segments)
    assert all(segment.scope["report_scope"] == "AUCTION_CAMPAIGN" for segment in segments)
    for selected in (first, second):
        rows = [segment for segment in segments if segment.sync_job_id == selected.pk]
        assert len(rows) == 4
        assert all((row.scope["time_to"] - row.scope["time_from"]) < 7 * 86400 for row in rows)
        assert sum((date.fromisoformat(row.scope["history_query"]["end_at"])
                    - date.fromisoformat(row.scope["history_query"]["start_at"])).days + 1 for row in rows) == 24
        assert all(row.scope["history_query"]["end_at"] < "2026-10-25" for row in rows)
        effective = history_validation_job(selected, rows[0])
        assert effective.sync_scope["query"] == rows[0].scope["history_query"]
    first.refresh_from_db()
    assert first.sync_scope["query"]["start_at"] == "2026-09-01"


def test_tiktok_ads_history_rejects_account_local_today(tkctx):
    user, job, _ = _tiktok_ads_job(tkctx)
    data = {"name": "TK Ads today", "job_ids": [job.pk], "start_date": "2026-10-25",
        "end_date": "2026-10-25", "idempotency_key": "tk-ads-today"}
    with patch("apps.integrations.history_sync.timezone.now", return_value=datetime(2026, 10, 25, 12, tzinfo=UTC)), \
         patch("apps.integrations.history_sync.validate_manual_sync_job"), pytest.raises(ValidationError, match="已完成日期"):
        create_history_batch(user, data)
    assert not HistorySyncBatch.objects.exists()


@pytest.mark.parametrize("field,value", [("timezone", "Asia/Tokyo"), ("advertiser_id", "999999")])
def test_tiktok_ads_history_rejects_changed_frozen_mapping(tkctx, field, value):
    from apps.integrations.history_sync import history_validation_job
    user, job, mapping = _tiktok_ads_job(tkctx)
    data = {"name": "TK Ads frozen", "job_ids": [job.pk], "start_date": "2026-10-01",
        "end_date": "2026-10-02", "idempotency_key": "tk-ads-frozen"}
    now = datetime(2026, 10, 3, 12, tzinfo=UTC)
    with patch("apps.integrations.history_sync.timezone.now", return_value=now), \
         patch("apps.integrations.history_sync.validate_manual_sync_job"):
        batch = create_history_batch(user, data)
    segment = batch.segments.get()
    setattr(mapping, field, value)
    mapping.save(update_fields=[field])
    with pytest.raises(ValidationError, match="映射或时区已变化"):
        history_validation_job(job, segment)


def test_tiktok_ads_history_rejects_invalid_mapping_timezone(tkctx):
    user, job, mapping = _tiktok_ads_job(tkctx)
    mapping.timezone = "Invalid/Timezone"
    mapping.save(update_fields=["timezone"])
    data = {"name": "TK Ads invalid zone", "job_ids": [job.pk], "start_date": "2026-10-01",
        "end_date": "2026-10-02", "idempotency_key": "tk-ads-invalid-zone"}
    now = datetime(2026, 10, 3, 12, tzinfo=UTC)
    with patch("apps.integrations.history_sync.timezone.now", return_value=now), \
         patch("apps.integrations.history_sync.validate_manual_sync_job"), pytest.raises(ValidationError, match="时区无效"):
        create_history_batch(user, data)


def test_tiktok_ads_history_request_stops_after_permission_revocation(tkctx, monkeypatch):
    from apps.integrations import ads_sync
    _, job, _ = tkctx
    adapter = ads_sync.AdsSpendAdapter(job.integration_config)
    adapter.source_run = SimpleNamespace(history_segment_id=101, run_id="history-run")
    monkeypatch.setattr("apps.integrations.history_sync.history_execution_allowed", lambda segment: False)
    with pytest.raises(ads_sync.AdsExecutionStopped, match="History authorization was revoked"):
        adapter.before_request(job)


def test_tiktok_ads_history_adapter_fetches_frozen_days_not_daily_query(tkctx):
    from decimal import Decimal
    from apps.integrations import ads_sync
    from apps.integrations.history_sync import history_validation_job
    from apps.integrations.history_tiktok_ads import tiktok_ads_history_scopes
    _, job, mapping = _tiktok_ads_job(tkctx)
    scope = tiktok_ads_history_scopes(job, {"start_date": "2026-10-01", "end_date": "2026-10-02"})[0]
    effective = history_validation_job(job, SimpleNamespace(scope=scope))
    adapter = ads_sync.AdsSpendAdapter(job.integration_config)
    with patch.object(ads_sync, "validate_mapping", return_value=SimpleNamespace(pk=1)), \
         patch.object(ads_sync, "snapshot", return_value="approved"), \
         patch.object(ads_sync.pilot, "_claim_lease", return_value=("lease", 1)), \
         patch.object(ads_sync.pilot, "get_custody_backend"), \
         patch.object(ads_sync.pilot, "PlatformHttpClient"), \
         patch.object(ads_sync.pilot, "_get", return_value={"list": [{"advertiser_id": mapping.advertiser_id, "currency": "PHP", "timezone": "Asia/Manila"}]}), \
         patch("apps.integrations.tiktok_ads_oauth.account_timezone", return_value="Asia/Manila"), \
         patch.object(adapter, "before_request"), \
         patch.object(ads_sync, "collect_day", return_value=Decimal("1")) as collect:
        adapter.validate_configuration(effective)
        adapter.source_run = SimpleNamespace(masked_log={})
        page = adapter.fetch_page(job)
    assert [call.args[3].isoformat() for call in collect.call_args_list] == ["2026-10-01", "2026-10-02"]
    assert [row["date"] for row in page["records"]] == ["2026-10-01", "2026-10-02"]
    job.refresh_from_db()
    assert job.sync_scope["query"]["start_at"] == "2026-09-01"


def test_tiktok_ads_history_commit_stops_when_history_authority_missing(tkctx):
    from datetime import timedelta
    from django.utils import timezone
    from apps.integrations import ads_sync
    _, job, mapping = _tiktok_ads_job(tkctx)
    job.status = "running"
    job.lock_token = "test-run"
    job.lock_expires_at = timezone.now() + timedelta(minutes=5)
    job.save(update_fields=["status", "lock_token", "lock_expires_at"])
    adapter = ads_sync.AdsSpendAdapter(job.integration_config)
    adapter.mapping = mapping
    adapter.scope = ads_sync.resolve_scope(mapping, {"query": {"mode": "range", "start_at": "2026-10-01", "end_at": "2026-10-01"}})
    adapter.source_run = SimpleNamespace(history_segment_id=999999, run_id="test-run")
    with pytest.raises(ads_sync.AdsExecutionStopped, match="History authorization was revoked before commit"):
        adapter.persist_records(job, [{"date": "2026-10-01", "spend": "1", "currency": "PHP"}])
