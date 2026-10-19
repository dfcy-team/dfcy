from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.db import transaction
from django.utils import timezone

from apps.integrations import affiliate_sync as module
from apps.integrations.models import (
    MarketplaceStoreAuthorization, SyncCursor, SyncRawEnvelope, SyncRun, authorization_service_write,
    marketplace_identity_key, marketplace_active_identity_key, marketplace_store_binding_key,
)
from apps.integrations.raw_services import replay_raw_envelope
from apps.integrations.readonly_clients import ReadonlyConfigurationError
from apps.integrations.tasks import refresh_affiliate_ingestion_day
from apps.influencers.models import AffiliateOrderRevision, AffiliateOrderSnapshot
from apps.influencers.tiktok_shop_dataset import TikTokDatasetClient
from tests.test_influencer_fulfillment import store_for
from tests.test_mock_sync_isolation import context  # noqa: F401


pytestmark = pytest.mark.django_db
DAY = date(2026, 8, 16)


@pytest.fixture
def trial(context):
    _, job = context
    store = store_for(job.tenant, "synthetic-affiliate")
    store.timezone = "Asia/Manila"
    store.external_store_id = "synthetic-shop-id"
    store.save(update_fields=["timezone", "external_store_id"])
    config = job.integration_config
    config.platform = "tiktok"
    config.save(update_fields=["platform"])
    with authorization_service_write():
        auth = MarketplaceStoreAuthorization.objects.create(tenant=job.tenant, store=store,
            integration_config=config, platform="tiktok", region="PH", platform_store_id="synthetic-shop-id",
            platform_identity_key=marketplace_identity_key("tiktok", "PH", "synthetic-shop-id"),
            active_platform_identity_key=marketplace_active_identity_key("tiktok", "PH", "synthetic-shop-id"),
            active_store_binding_key=marketplace_store_binding_key(job.tenant_id, "tiktok", store.pk),
            merchant_subject_id="synthetic-merchant",
            shop_cipher="synthetic-cipher", credential_id="placeholder-reference", token_id="placeholder-token",
            scopes=sorted(module.SCOPES), status="active", created_by=config.created_by, updated_by=config.created_by)
    run = SyncRun.objects.create(tenant=job.tenant, sync_job=job, run_id="synthetic-run", idempotency_key="synthetic-key",
                                started_at=timezone.now())
    job.resource_type = "affiliate_order"
    job.status = "running"
    job.lock_token = run.run_id
    job.store_authorization = auth
    job.lock_expires_at = timezone.now() + timedelta(minutes=15)
    job.save()
    adapter = module.TikTokAffiliateOrderAdapter(config)
    adapter.authorization = auth
    adapter.bind_run(run)
    policy = {"historical_start": "2026-08-01", "snapshot_source": "synthetic-source", "site": "PH", "trial_days": [DAY.isoformat()]}
    adapter.scope = {"affiliate_plan": module.build_plan(job, store, policy, datetime(2026, 10, 12, tzinfo=UTC))}
    client = TikTokDatasetClient(config, auth, http_client=Mock(), custody=Mock())
    client.verify_shop = Mock()
    adapter.client = client
    return SimpleNamespace(job=job, run=run, store=store, adapter=adapter, client=client, policy=policy,
                           observed_at=run.started_at + timedelta(seconds=10))


def order(sku="sku-1", **changes):
    value = {"sku_id": sku, "product_id": "product-1", "creator_username": "creator-account", "quantity": 1,
             "fully_return": "No", "settlement_status": "SETTLED",
             "estimated_commission_base": {"amount": "100.1234", "currency": "PHP"},
             "actual_paid_commission": {"amount": "0", "currency": "PHP"},
             "actual_paid_shop_ads_commission": {"amount": "1.2345", "currency": "PHP"}}
    value.update(changes)
    return {"id": "order-1", "create_time": int(datetime(2026, 8, 16, 8, tzinfo=UTC).timestamp()), "skus": [value]}


def detail(sku="sku-1", **changes):
    value = {"id": "order-1", "status": "COMPLETED", "payment": {"total_amount": "999.12", "currency": "PHP"},
             "line_items": [{"id": "synthetic-line-" + sku, "sku_id": sku, "quantity": 1, "sale_price": "999.12"}]}
    value.update(changes)
    return value


def fetch(trial, values=None, details=None, total=1):
    trial.client._transport_request = Mock(side_effect=[{"data": {"orders": [order()] if values is None else values, "total_count": total}},
                                              {"data": {"orders": [detail()] if details is None else details}}])
    with patch("django.utils.timezone.now", return_value=trial.observed_at):
        page = trial.adapter.fetch_page(trial.job, "")
    trial.observed_at += timedelta(seconds=1)
    return page


def write(trial, page):
    with transaction.atomic():
        values = [trial.adapter.normalize_record(row) for row in page["records"]]
        results = trial.adapter.persist_records(trial.job, values)
        trial.adapter.after_page_persist(trial.job, page, results)
    return results


def test_complete_day_writes_three_independent_amounts_and_repeat_is_noop(trial):
    page = fetch(trial)
    assert not AffiliateOrderSnapshot.objects.exists()
    assert write(trial, page)[0]["action"] == "created"
    row = AffiliateOrderSnapshot.objects.get()
    assert row.data_time == datetime(2026, 8, 16, tzinfo=UTC)
    assert row.estimated_commission_base == Decimal("100.1234")
    assert row.actual_paid_commission == Decimal("0")
    assert row.actual_paid_shop_ads_commission == Decimal("1.2345")
    assert row.payment_amount == Decimal("999.12") and row.quantity == 1
    assert row.settlement_status == "\u5df2\u7ed3\u7b97" and row.fully_returned == "\u5426"
    trial.run.started_at += timedelta(days=1)
    assert write(trial, fetch(trial))[0]["action"] == "skipped"
    assert not AffiliateOrderRevision.objects.exists()


@pytest.mark.parametrize("changes", [
    {"quantity": None}, {"settlement_status": "UNKNOWN"}, {"fully_return": "ambiguous"},
    {"creator_username": ""}, {"actual_paid_commission": {"amount": 1.2, "currency": "PHP"}},
    {"actual_paid_shop_ads_commission": {"amount": "1.23456", "currency": "PHP"}},
    {"estimated_commission_base": {"amount": "100", "currency": "THB"}},
])
def test_invalid_day_keeps_only_journal_and_zero_canonical_writes(trial, changes):
    with pytest.raises(ReadonlyConfigurationError):
        fetch(trial, [order(**changes)])
    assert not AffiliateOrderSnapshot.objects.exists()
    assert not SyncCursor.objects.filter(sync_job=trial.job).exists()


@pytest.mark.parametrize("details", [[], [detail(id="wrong")], [detail(status="")]])
def test_no_invented_new_payment_or_status(trial, details):
    with pytest.raises(ReadonlyConfigurationError):
        fetch(trial, details=details)
    assert not AffiliateOrderSnapshot.objects.exists()


def test_missing_total_and_mismatched_total_block_formal_day(trial):
    for total in (None, 2):
        # Use a separate scope to avoid trusting an earlier cached response.
        trial.adapter.scope["affiliate_plan"]["snapshot_source"] += "x"
        with pytest.raises(ReadonlyConfigurationError):
            fetch(trial, total=total)
    assert not AffiliateOrderSnapshot.objects.exists()


def test_page_two_network_failure_resumes_projected_page_one_without_fact_writes(trial):
    trial.client._transport_request = Mock(side_effect=[{"data": {"orders": [order()], "total_count": 2, "next_page_token": "next"}},
                                             TimeoutError("synthetic timeout")])
    with pytest.raises(TimeoutError):
        trial.adapter.fetch_page(trial.job, "")
    assert SyncRawEnvelope.objects.count() == 1 and not AffiliateOrderSnapshot.objects.exists()
    second = {**order(sku="sku-2"), "id": "order-2"}
    trial.client._transport_request = Mock(side_effect=[{"data": {"orders": [second], "total_count": 2}},
                                             {"data": {"orders": [detail(), detail(sku="sku-2", id="order-2")]}}])
    page = trial.adapter.fetch_page(trial.job, "")
    assert len(page["records"]) == 2
    assert trial.client._transport_request.call_args_list[0].kwargs["query"]["page_token"] == "next"
    assert len(write(trial, page)) == 2 and AffiliateOrderSnapshot.objects.count() == 2


def test_takeover_rejects_day_write_and_journal_append(trial):
    page = fetch(trial)
    trial.job.lock_token = "test-replacement-worker"
    trial.job.save(update_fields=["lock_token"])
    with pytest.raises(ReadonlyConfigurationError, match="LEASE_LOST"):
        write(trial, page)
    assert not AffiliateOrderSnapshot.objects.exists()
    with pytest.raises(ReadonlyConfigurationError, match="LEASE_LOST"):
        module.DatabasePageJournal(trial.job, trial.run, {}).save({"synthetic": "page"}, {})


def test_newer_unknown_amounts_do_not_erase_known_and_late_refund_creates_revision(trial):
    write(trial, fetch(trial))
    trial.run.started_at += timedelta(days=2)
    trial.adapter.scope["affiliate_plan"]["snapshot_source"] = "new-observation"
    page = fetch(trial, [order(actual_paid_commission=None, actual_paid_shop_ads_commission=None,
                             fully_return="Yes", settlement_status="INELIGIBLE")])
    assert write(trial, page)[0]["action"] == "updated"
    row = AffiliateOrderSnapshot.objects.get()
    assert row.actual_paid_commission == 0 and row.actual_paid_shop_ads_commission == Decimal("1.2345")
    assert row.source == "synthetic-source" and row.fully_returned == "\u662f"
    assert row.settlement_status == "\u4e0d\u7b26\u5408\u6761\u4ef6" and AffiliateOrderRevision.objects.count() == 1


def test_ambiguous_or_changed_creator_cannot_reassociate(trial):
    write(trial, fetch(trial))
    trial.adapter.scope["affiliate_plan"]["snapshot_source"] = "changed-source"
    page = fetch(trial, [order(creator_username="different-creator")])
    with pytest.raises(ReadonlyConfigurationError, match="PROTECTED_IDENTITY"):
        write(trial, page)
    assert AffiliateOrderSnapshot.objects.get().creator_username == "creator-account"
    assert not AffiliateOrderRevision.objects.exists()


def test_raw_envelope_cannot_bypass_complete_day_proof(trial):
    fetch(trial)
    with pytest.raises(Exception, match="complete-day"):
        replay_raw_envelope(SyncRawEnvelope.objects.first(), trial.adapter)
    with pytest.raises(ReadonlyConfigurationError, match="COMPLETE_DAY_REQUIRED"):
        trial.adapter.persist_records(trial.job, [])
    assert not AffiliateOrderSnapshot.objects.exists()


def test_revision_failure_rolls_back_all_facts_and_progress(trial):
    write(trial, fetch(trial))
    trial.run.started_at += timedelta(days=1)
    trial.adapter.scope["affiliate_plan"]["snapshot_source"] = "revision-failure"
    page = fetch(trial, [order(actual_paid_shop_ads_commission={"amount": "2", "currency": "PHP"})])
    with patch("apps.influencers.models.AffiliateOrderRevision.objects.create", side_effect=RuntimeError("synthetic fault")):
        with pytest.raises(RuntimeError):
            write(trial, page)
    assert AffiliateOrderSnapshot.objects.get().actual_paid_shop_ads_commission == Decimal("1.2345")


def test_post_commit_refresh_outbox_retries_broker_and_marks_only_after_task_completion(trial):
    write(trial, fetch(trial))
    trial.run.refresh_from_db()
    assert trial.run.masked_log["affiliate_refresh_pending"]
    with patch("apps.integrations.tasks.refresh_affiliate_ingestion_day.delay", side_effect=RuntimeError("synthetic broker")):
        assert module.dispatch_pending_affiliate_refreshes() == 0
    with patch("apps.integrations.tasks.refresh_affiliate_ingestion_day.delay") as submit:
        assert module.dispatch_pending_affiliate_refreshes() == 1
        submit.assert_called_once_with(trial.run.pk, DAY.isoformat(), 1)
        assert module.dispatch_pending_affiliate_refreshes() == 0
    with patch("apps.influencers.tasks.refresh_affiliate_order_attributions_task.run", return_value={"status": "completed"}) as refresh:
        assert refresh_affiliate_ingestion_day.run(trial.run.pk, DAY.isoformat())["status"] == "completed"
        refresh.assert_called_once_with(tenant_id=trial.job.tenant_id, order_ids=[AffiliateOrderSnapshot.objects.get().pk])
    trial.run.refresh_from_db()
    assert not trial.run.masked_log["affiliate_refresh_pending"]
    assert refresh_affiliate_ingestion_day.run(trial.run.pk, DAY.isoformat()) == {"status": "not_pending"}


@pytest.mark.parametrize("zone,country,currency,site", [("Asia/Manila", "PH", "PHP", "PH"),
    ("Asia/Kuala_Lumpur", "MY", "MYR", "MY"), ("Asia/Bangkok", "TH", "THB", "TH")])
def test_plan_uses_completed_store_natural_days_and_rotates_old_history(trial, zone, country, currency, site):
    trial.store.timezone, trial.store.country_code, trial.store.currency = zone, country, currency
    policy = {"historical_start": "2026-08-01", "snapshot_source": "synthetic", "site": site}
    now = datetime(2026, 10, 11, 16, 30, tzinfo=UTC)
    plan = module.build_plan(trial.job, trial.store, policy, now)
    assert len(plan["days"]) <= 14 and plan["days"][0] == "2026-08-01"
    expected_last = "2026-10-10" if country == "TH" else "2026-10-11"
    assert max(plan["days"]) == expected_last
    SyncCursor.objects.create(tenant=trial.job.tenant, sync_job=trial.job, cursor_key="affiliate-history-day", cursor_value="2026-08-20")
    later = module.build_plan(trial.job, trial.store, policy, now)
    assert "2026-08-20" in later["days"] and later["archive_next"] == "2026-08-22"


def test_no_accidental_full_history_or_scope_expansion(trial):
    with pytest.raises(ReadonlyConfigurationError):
        module.build_plan(trial.job, trial.store, {"snapshot_source": "synthetic", "site": "PH"})
    with pytest.raises(ReadonlyConfigurationError):
        module.build_plan(trial.job, trial.store, {**trial.policy, "site": "TH"})


@pytest.mark.parametrize("cross_page", [False, True])
def test_repeated_parent_with_disjoint_skus_proves_sku_total(trial, cross_page):
    first, second = order(), order(sku="sku-2")
    responses = ([{"data": {"orders": [first], "total_count": 2, "next_page_token": "next"}},
                  {"data": {"orders": [second], "total_count": 2}}] if cross_page else
                 [{"data": {"orders": [first, second], "total_count": 2}}])
    trial.client._transport_request = Mock(side_effect=[*responses, {"data": {"orders": [detail(line_items=[])]}}])
    page = trial.adapter.fetch_page(trial.job, "")
    assert len(page["records"]) == 2
    assert trial.client.last_page_summary["parent_count"] == 1
    assert trial.client.last_page_summary["count_unit"] == "sku_row"
    assert len(write(trial, page)) == 2
    assert not AffiliateOrderSnapshot.objects.filter(payment_amount__isnull=False).exists()


@pytest.mark.parametrize("total,accepted", [(1, False), (2, True)])
def test_total_count_contract_is_sku_rows_not_parent_orders(trial, total, accepted):
    parent = order()
    parent["skus"].extend(order(sku="sku-2")["skus"])
    if accepted:
        trial.adapter._client()
        trial.client._transport_request = Mock(return_value={"data": {"orders": [parent], "total_count": total}})
        rows, _ = trial.client.affiliate_orders(DAY, DAY, module.ZoneInfo("Asia/Manila"), staging=True)
        assert len(rows) == 2
        assert trial.client.last_page_summary["parent_count"] == 1
        assert trial.client.last_page_summary["count_unit"] == "sku_row"
        assert trial.client.last_page_summary["unique_sku_count"] == total
    else:
        with pytest.raises(ReadonlyConfigurationError, match="total_mismatch"):
            fetch(trial, [parent], total=total)
        assert not AffiliateOrderSnapshot.objects.exists()


def test_empty_complete_day_has_explicit_zero_sku_total(trial):
    page = fetch(trial, [], total=0)
    assert page["records"] == [] and write(trial, page) == []
    assert not AffiliateOrderSnapshot.objects.exists()
    trial.run.refresh_from_db()
    assert not trial.run.masked_log.get("affiliate_refresh_pending")


def test_cached_parent_evidence_accepts_disjoint_sku_after_timeout(trial):
    trial.client._transport_request = Mock(side_effect=[
        {"data": {"orders": [order()], "total_count": 2, "next_page_token": "next"}},
        TimeoutError("synthetic interruption")])
    with pytest.raises(TimeoutError):
        trial.adapter.fetch_page(trial.job, "")
    trial.client._transport_request = Mock(side_effect=[
        {"data": {"orders": [order(sku="sku-2")], "total_count": 2}},
        {"data": {"orders": [detail(line_items=[])]}}])
    page = trial.adapter.fetch_page(trial.job, "")
    assert len(page["records"]) == 2 and len(write(trial, page)) == 2
    assert trial.client.last_page_summary["parent_count"] == 1


def test_observation_survives_cache_replay_and_is_not_run_start(trial):
    observed = trial.observed_at
    page = fetch(trial)
    value = trial.adapter.normalize_record(page["records"][0])
    assert value["source_updated_at"] == observed
    assert value["source_updated_at"] != trial.run.started_at
    trial.run.started_at += timedelta(days=10)
    replayed = fetch(trial)
    trial.client._transport_request.assert_not_called()
    assert trial.adapter.normalize_record(replayed["records"][0])["source_updated_at"] == observed


def test_mixed_component_observation_uses_earliest_and_blocks_stale_commission(trial):
    page = fetch(trial)
    original = trial.adapter.normalize_record(page["records"][0])["source_updated_at"]
    write(trial, page)
    row = AffiliateOrderSnapshot.objects.get()
    row.source_updated_at = original + timedelta(seconds=5)
    row.save(update_fields=["source_updated_at"])
    trial.adapter.scope["affiliate_plan"]["snapshot_source"] = "mixed-components"
    times = iter([original + timedelta(seconds=1), original + timedelta(seconds=20)])

    def response(*args, **kwargs):
        trial.observed_at = next(times)
        if kwargs.get("method") == "POST":
            return {"data": {"orders": [order(actual_paid_commission={"amount": "9", "currency": "PHP"})], "total_count": 1}}
        return {"data": {"orders": [detail()]}}

    trial.client._transport_request = Mock(side_effect=response)
    with patch("django.utils.timezone.now", side_effect=lambda: trial.observed_at):
        mixed = trial.adapter.fetch_page(trial.job, "")
    assert trial.adapter.normalize_record(mixed["records"][0])["source_updated_at"] == original + timedelta(seconds=1)
    with pytest.raises(ReadonlyConfigurationError, match="STALE_OBSERVATION"):
        write(trial, mixed)
    assert AffiliateOrderSnapshot.objects.get().actual_paid_commission == 0
    assert not AffiliateOrderRevision.objects.exists()


@pytest.mark.parametrize("field", ["affiliate_observed_at", "detail_observed_at"])
def test_missing_observation_is_not_replaced_by_run_time(trial, field):
    row = dict(fetch(trial)["records"][0])
    row.pop(field)
    with pytest.raises(module.DatasetError, match="observation_required"):
        trial.adapter.normalize_record(row)


def test_new_unknown_commissions_remain_null(trial):
    write(trial, fetch(trial, [order(actual_paid_commission=None, actual_paid_shop_ads_commission=None)]))
    row = AffiliateOrderSnapshot.objects.get()
    assert row.actual_paid_commission is None and row.actual_paid_shop_ads_commission is None


def seed_outbox(trial, ids, generation=1):
    trial.run.masked_log = {"unrelated": "preserved", "affiliate_refresh_pending": True,
                           "affiliate_refresh": {DAY.isoformat(): {"ids": ids, "generation": generation, "pending": True}}}
    trial.run.save(update_fields=["masked_log"])


@pytest.mark.parametrize("count", [0, 1, 5000, 5001, 10001])
def test_outbox_chunks_at_most_5000_then_acks(trial, count):
    ids = list(range(1, count + 1))
    seed_outbox(trial, ids)
    with patch("apps.influencers.tasks.refresh_affiliate_order_attributions_task.run", return_value={"status": "completed"}) as refresh:
        result = refresh_affiliate_ingestion_day.run(trial.run.pk, DAY.isoformat(), 1)
    assert result == {"status": "completed", "snapshot_count": count}
    assert [call.kwargs["order_ids"] for call in refresh.call_args_list] == [ids[i:i + 5000] for i in range(0, count, 5000)]
    assert all(call.kwargs["tenant_id"] == trial.job.tenant_id for call in refresh.call_args_list)
    trial.run.refresh_from_db()
    assert not trial.run.masked_log["affiliate_refresh_pending"]
    assert trial.run.masked_log["unrelated"] == "preserved"


def test_middle_chunk_failure_leaves_pending_and_retries_all_chunks(trial):
    seed_outbox(trial, list(range(1, 10002)))
    with patch("apps.influencers.tasks.refresh_affiliate_order_attributions_task.run", side_effect=[{"status": "completed"}, RuntimeError("synthetic chunk")]):
        with pytest.raises(RuntimeError):
            refresh_affiliate_ingestion_day.run(trial.run.pk, DAY.isoformat(), 1)
    trial.run.refresh_from_db()
    assert trial.run.masked_log["affiliate_refresh_pending"]
    with patch("apps.influencers.tasks.refresh_affiliate_order_attributions_task.run", return_value={"status": "completed"}) as refresh:
        assert refresh_affiliate_ingestion_day.run(trial.run.pk, DAY.isoformat(), 1)["status"] == "completed"
        assert refresh.call_count == 3


def test_old_generation_delivery_never_refreshes_new_entry(trial):
    seed_outbox(trial, [1, 2], generation=2)
    with patch("apps.influencers.tasks.refresh_affiliate_order_attributions_task.run") as refresh:
        assert refresh_affiliate_ingestion_day.run(trial.run.pk, DAY.isoformat(), 1) == {"status": "superseded"}
        refresh.assert_not_called()


def test_generation_changed_during_refresh_cannot_be_acked(trial):
    seed_outbox(trial, [1])

    def replace_entry(**kwargs):
        seed_outbox(trial, [1, 2], generation=2)
        return {"status": "completed"}

    with patch("apps.influencers.tasks.refresh_affiliate_order_attributions_task.run", side_effect=replace_entry):
        assert refresh_affiliate_ingestion_day.run(trial.run.pk, DAY.isoformat(), 1) == {"status": "superseded"}
    trial.run.refresh_from_db()
    assert trial.run.masked_log["affiliate_refresh"][DAY.isoformat()]["pending"]
    assert trial.run.masked_log["affiliate_refresh_pending"]


def test_broker_receipt_cannot_throttle_replacement_generation(trial):
    seed_outbox(trial, [1])
    with patch("apps.integrations.tasks.refresh_affiliate_ingestion_day.delay",
               side_effect=lambda *args: seed_outbox(trial, [1, 2], generation=2)):
        assert module.dispatch_pending_affiliate_refreshes() == 1
    trial.run.refresh_from_db()
    assert "submitted_at" not in trial.run.masked_log["affiliate_refresh"][DAY.isoformat()]


@pytest.mark.parametrize("status,fields", [("completed", None), ("failed", None),
    ("running", ["masked_log"]), ("queued", ["status", "masked_log"])])
def test_framework_stale_log_never_resurrects_ack_or_drops_other_fields(trial, status, fields):
    from apps.integrations.sync_services import _save_run
    seed_outbox(trial, [1])
    stale = SyncRun.objects.get(pk=trial.run.pk)
    with patch("apps.influencers.tasks.refresh_affiliate_order_attributions_task.run", return_value={"status": "completed"}):
        refresh_affiliate_ingestion_day.run(trial.run.pk, DAY.isoformat(), 1)
    stale.status = status
    stale.masked_log["framework_result"] = status
    _save_run(stale, update_fields=fields)
    stale.refresh_from_db()
    assert not stale.masked_log["affiliate_refresh_pending"]
    assert not stale.masked_log["affiliate_refresh"][DAY.isoformat()]["pending"]
    assert stale.masked_log["unrelated"] == "preserved"
    assert stale.masked_log["framework_result"] == status


def test_next_page_merges_latest_acked_day_and_pending_ids(trial):
    seed_outbox(trial, [1])
    with patch("apps.influencers.tasks.refresh_affiliate_order_attributions_task.run", return_value={"status": "completed"}):
        refresh_affiliate_ingestion_day.run(trial.run.pk, DAY.isoformat(), 1)
    with transaction.atomic():
        trial.adapter.after_page_persist(trial.job, {"day": "2026-08-17"},
                                        [{"action": "updated", "order_snapshot_id": 2}])
        trial.adapter.after_page_persist(trial.job, {"day": "2026-08-17"},
                                        [{"action": "updated", "order_snapshot_id": 3}])
    trial.run.refresh_from_db()
    progress = trial.run.masked_log["affiliate_refresh"]
    assert not progress[DAY.isoformat()]["pending"]
    assert progress["2026-08-17"] == {"ids": [2, 3], "generation": 2, "pending": True}


def test_all_framework_run_saves_use_locked_log_merge():
    import ast
    import inspect
    from apps.integrations import sync_services
    tree = ast.parse(inspect.getsource(sync_services))
    for function in tree.body:
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)) and function.name != "_save_run":
            assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                           and isinstance(node.func.value, ast.Name) and node.func.value.id == "run"
                           and node.func.attr == "save" for node in ast.walk(function)), function.name


@pytest.mark.parametrize("missing", ["version", "count_unit", "parent_headers", "observed_at", "source_count",
                                     "sku_row_count", "unique_sku_count", "total", "input_token", "next_token", "rows"])
def test_checkpoint_without_v3_proof_fails_closed(trial, missing):
    fetch(trial)
    saved = dict(SyncRawEnvelope.objects.order_by("sequence").first().payload["result"])
    saved.pop(missing)
    checkpoint = Mock()
    checkpoint.load.return_value = saved
    with pytest.raises(module.DatasetError):
        trial.client.affiliate_orders(DAY, DAY, module.ZoneInfo("Asia/Manila"), staging=True, checkpoint=checkpoint)
    assert not AffiliateOrderSnapshot.objects.exists()


def test_expired_lease_recovery_preserves_ack(trial):
    from apps.integrations.sync_services import _recover_expired_lease
    trial.run.status = SyncRun.Status.RUNNING
    trial.run.save(update_fields=["status"])
    seed_outbox(trial, [1])
    with patch("apps.influencers.tasks.refresh_affiliate_order_attributions_task.run", return_value={"status": "completed"}):
        refresh_affiliate_ingestion_day.run(trial.run.pk, DAY.isoformat(), 1)
    _recover_expired_lease(trial.job, timezone.now())
    trial.run.refresh_from_db()
    assert trial.run.status == SyncRun.Status.FAILED
    assert not trial.run.masked_log["affiliate_refresh_pending"]


@pytest.mark.parametrize("lines", [None, [],
    [{"sku_id": "sku-1", "sale_price": "999.12"}],
    [{"sku_id": "sku-1", "quantity": 2, "sale_price": "999.12"}],
    [{"sku_id": "sku-1", "quantity": 1, "sale_price": "2"}],
    [{"sku_id": "other-sku", "quantity": 1, "sale_price": "999.12"}],
    [{"sku_id": "sku-1", "quantity": 1, "sale_price": "400"},
     {"sku_id": "sku-2", "quantity": 1, "sale_price": "599.12"}],
    [{"sku_id": "sku-1", "quantity": 1, "sale_price": "400"},
     {"sku_id": "sku-1", "quantity": 1, "sale_price": "599.12"}],
])
def test_unverified_or_multiline_payment_is_unknown_not_repeated(trial, lines):
    page = fetch(trial, details=[detail(line_items=lines)])
    assert write(trial, page)[0]["action"] == "created"
    row = AffiliateOrderSnapshot.objects.get()
    assert row.payment_amount is None
    assert row.actual_paid_shop_ads_commission == Decimal("1.2345")
    assert not AffiliateOrderRevision.objects.exists()


def test_multisku_order_total_cannot_be_assigned_to_each_sku(trial):
    parent = order()
    parent["skus"].extend(order(sku="sku-2")["skus"])
    page = fetch(trial, [parent], total=2, details=[detail(line_items=[
            {"sku_id": "sku-1", "quantity": 1, "sale_price": "400"},
            {"sku_id": "sku-2", "quantity": 1, "sale_price": "599.12"}])])
    projected = SyncRawEnvelope.objects.order_by("sequence").last().payload["result"]["order-1"]
    assert projected["payment"]["amount"] is None
    assert projected["payment_status"] == "unknown"
    write(trial, page)
    assert AffiliateOrderSnapshot.objects.count() == 2
    assert not AffiliateOrderSnapshot.objects.filter(payment_amount__isnull=False).exists()


def test_multiunit_affiliate_line_cannot_reuse_single_unit_payment(trial):
    write(trial, fetch(trial, [order(quantity=2)]))
    row = AffiliateOrderSnapshot.objects.get()
    assert row.quantity == 2 and row.payment_amount is None


def test_unknown_sku_payment_never_clears_previous_verified_value(trial):
    write(trial, fetch(trial))
    trial.adapter.scope["affiliate_plan"]["snapshot_source"] = "new-payment-observation"
    changed = order(actual_paid_commission={"amount": "2", "currency": "PHP"})
    write(trial, fetch(trial, [changed], details=[detail(line_items=[])]))
    row = AffiliateOrderSnapshot.objects.get()
    assert row.payment_amount == Decimal("999.12")
    assert row.actual_paid_commission == Decimal("2")


def test_absent_order_payment_is_null_not_zero(trial):
    write(trial, fetch(trial, details=[detail(payment={})]))
    assert AffiliateOrderSnapshot.objects.get().payment_amount is None


def test_noop_advances_watermark_and_blocks_intermediate_stale_snapshot(trial):
    write(trial, fetch(trial))
    observed = AffiliateOrderSnapshot.objects.get().source_updated_at
    trial.observed_at = observed + timedelta(minutes=10)
    trial.adapter.scope["affiliate_plan"]["snapshot_source"] = "fresh-noop-observation"
    assert write(trial, fetch(trial))[0]["action"] == "skipped"
    current = AffiliateOrderSnapshot.objects.get()
    assert current.source_updated_at == observed + timedelta(minutes=10)
    assert not AffiliateOrderRevision.objects.exists()
    trial.observed_at = observed + timedelta(minutes=5)
    trial.adapter.scope["affiliate_plan"]["snapshot_source"] = "intermediate-stale"
    page = fetch(trial, [order(actual_paid_commission={"amount": "2", "currency": "PHP"})])
    with pytest.raises(ReadonlyConfigurationError, match="STALE_OBSERVATION"):
        write(trial, page)
    assert AffiliateOrderSnapshot.objects.get().actual_paid_commission == Decimal("0")


def test_dispatch_rotation_reaches_new_run_after_throttled_prefix(trial):
    log = {"affiliate_refresh_pending": True, "affiliate_refresh": {
        DAY.isoformat(): {"ids": [1], "generation": 1, "pending": True,
                          "submitted_at": timezone.now().isoformat()}}}
    for number in range(24):
        SyncRun.objects.create(tenant=trial.job.tenant, sync_job=trial.job,
            run_id="throttled-" + str(number), idempotency_key="throttled-" + str(number), masked_log=log)
    later = SyncRun.objects.create(tenant=trial.job.tenant, sync_job=trial.job,
        run_id="later-ready", idempotency_key="later-ready", masked_log={
            "affiliate_refresh_pending": True,
            "affiliate_refresh": {DAY.isoformat(): {"ids": [2], "generation": 1, "pending": True}}})
    with patch("apps.integrations.tasks.refresh_affiliate_ingestion_day.delay") as submit:
        assert module.dispatch_pending_affiliate_refreshes(limit=1) == 0
        assert module.dispatch_pending_affiliate_refreshes(limit=1) == 1
        submit.assert_called_once_with(later.pk, DAY.isoformat(), 1)


def test_dispatch_rotation_and_clock_survive_broker_failure_and_stale_framework(trial):
    from apps.integrations.sync_services import _save_run
    seed_outbox(trial, [1])
    stale = SyncRun.objects.get(pk=trial.run.pk)
    with patch("apps.integrations.tasks.refresh_affiliate_ingestion_day.delay", side_effect=RuntimeError("synthetic broker")):
        assert module.dispatch_pending_affiliate_refreshes(limit=1) == 0
    trial.run.refresh_from_db()
    clock = trial.run.masked_log["affiliate_dispatch_attempt_at"]
    stale.masked_log["affiliate_dispatch_attempt_at"] = "2000-01-01T00:00:00+00:00"
    _save_run(stale, update_fields=["masked_log"])
    stale.refresh_from_db()
    assert stale.masked_log["affiliate_dispatch_attempt_at"] == clock
    assert stale.masked_log["affiliate_refresh_pending"]


def test_noncompleted_refresh_result_leaves_outbox_pending(trial):
    seed_outbox(trial, [1])
    with patch("apps.influencers.tasks.refresh_affiliate_order_attributions_task.run", return_value={"status": "tenant_not_found"}):
        with pytest.raises(RuntimeError, match="NOT_COMPLETED"):
            refresh_affiliate_ingestion_day.run(trial.run.pk, DAY.isoformat(), 1)
    trial.run.refresh_from_db()
    assert trial.run.masked_log["affiliate_refresh_pending"]
