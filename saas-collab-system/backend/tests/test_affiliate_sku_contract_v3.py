"""Synthetic SKU-count and replay proofs; no live or recorded provider payloads."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import pytest

from apps.integrations import affiliate_sync as module
from apps.integrations.models import SyncCursor, SyncRawEnvelope
from apps.integrations.raw_services import payload_digest
from apps.integrations.readonly_clients import ReadonlyConfigurationError
from apps.influencers.models import AffiliateOrderRevision, AffiliateOrderSnapshot
from tests.test_affiliate_daily_ingestion import DAY, context, detail, fetch, order, trial, write  # noqa: F401


pytestmark = pytest.mark.django_db


def collect(trial, responses, checkpoint=None, max_pages=100):
    trial.adapter._client()
    trial.client._transport_request = Mock(side_effect=responses)
    original = trial.client.collect_pages
    with patch.object(trial.client, "collect_pages", side_effect=lambda *args, **kwargs:
                      original(*args, **{**kwargs, "max_pages": max_pages})):
        return trial.client.affiliate_orders(DAY, DAY, module.ZoneInfo("Asia/Manila"), staging=True, checkpoint=checkpoint)


def assert_no_formal_writes(trial):
    assert not AffiliateOrderSnapshot.objects.exists()
    assert not AffiliateOrderRevision.objects.exists()
    assert not SyncCursor.objects.filter(sync_job=trial.job).exists()
    trial.run.refresh_from_db()
    assert not trial.run.masked_log.get("affiliate_refresh_pending")


@pytest.mark.parametrize("sku_count,parent_count", [(59, 46), (327, 296)])
def test_synthetic_oct8_cardinalities_are_sku_not_parent_totals(trial, sku_count, parent_count):
    day = "2026-10-08"
    trial.adapter.scope["affiliate_plan"]["days"] = [day]
    created = int(datetime(2026, 10, 8, 8, tzinfo=UTC).timestamp())
    values = [{**order(sku=f"synthetic-sku-{i}"), "id": f"synthetic-parent-{i % parent_count}",
               "create_time": created} for i in range(sku_count)]
    pages = [{"data": {"orders": values[offset:offset + 50], "total_count": sku_count,
                       "next_page_token": f"synthetic-page-{offset + 50}" if offset + 50 < sku_count else ""}}
             for offset in range(0, sku_count, 50)]
    ids = sorted({value["id"] for value in values})
    details = [{"data": {"orders": [detail(id=oid, line_items=[]) for oid in ids[offset:offset + 50]]}}
               for offset in range(0, len(ids), 50)]
    trial.client._transport_request = Mock(side_effect=[*pages, *details])
    page = trial.adapter.fetch_page(trial.job, "")
    summary = trial.client.last_page_summary
    assert summary["version"] == "affiliate-daily-v3" and summary["count_unit"] == "sku_row"
    assert summary["expected_count"] == summary["observed_count"] == summary["unique_sku_count"] == sku_count
    assert summary["parent_count"] == parent_count
    assert len(write(trial, page)) == sku_count
    assert AffiliateOrderSnapshot.objects.count() == sku_count
    assert not AffiliateOrderSnapshot.objects.filter(payment_amount__isnull=False).exists()
    trial.client._transport_request = Mock(side_effect=AssertionError("replay must not call a provider"))
    replay = trial.adapter.fetch_page(trial.job, "")
    assert all(result["action"] == "skipped" for result in write(trial, replay))
    assert AffiliateOrderSnapshot.objects.count() == sku_count
    assert not AffiliateOrderRevision.objects.exists()
    assert not SyncCursor.objects.filter(sync_job=trial.job).exists()


@pytest.mark.parametrize("total", [None, True, False, -1, "1", 1.0, 2**63])
def test_total_must_be_explicit_nonnegative_integer_on_every_page(trial, total):
    with pytest.raises(module.DatasetError, match="total_count_required"):
        collect(trial, [{"data": {"orders": [order()], "total_count": total}}])
    assert_no_formal_writes(trial)


@pytest.mark.parametrize("total,code", [(None, "total_count_required"), ("2", "total_count_required"),
                                      (True, "total_count_required"), (3, "page_total_changed")])
def test_later_page_total_cannot_be_missing_or_changed(trial, total, code):
    with pytest.raises(module.DatasetError, match=code):
        collect(trial, [{"data": {"orders": [order()], "total_count": 2, "next_page_token": "next"}},
                        {"data": {"orders": [order(sku="sku-2")], "total_count": total}}])
    assert_no_formal_writes(trial)


@pytest.mark.parametrize("cross_page", [False, True])
@pytest.mark.parametrize("changes", [{}, {"product_id": "other-product"}, {"creator_username": "other-creator"},
                                    {"content_id": "other-content"}, {"commission_model": "other-model"}])
def test_duplicate_canonical_pair_never_increases_unique_count(trial, cross_page, changes):
    duplicate = order(**changes)
    responses = ([{"data": {"orders": [order()], "total_count": 2, "next_page_token": "next"}},
                  {"data": {"orders": [duplicate], "total_count": 2}}] if cross_page else
                 [{"data": {"orders": [order(), duplicate], "total_count": 2}}])
    with pytest.raises(module.DatasetError, match="duplicate_order_sku"):
        collect(trial, responses)
    assert_no_formal_writes(trial)


@pytest.mark.parametrize("cross_page", [False, True])
def test_repeated_parent_requires_consistent_normalized_create_time(trial, cross_page):
    second = order(sku="sku-2")
    second["create_time"] += 1
    responses = ([{"data": {"orders": [order()], "total_count": 2, "next_page_token": "next"}},
                  {"data": {"orders": [second], "total_count": 2}}] if cross_page else
                 [{"data": {"orders": [order(), second], "total_count": 2}}])
    with pytest.raises(module.DatasetError, match="parent_header_conflict"):
        collect(trial, responses)
    assert_no_formal_writes(trial)


def test_equivalent_normalized_parent_times_and_ids_are_accepted(trial):
    first, second = order(), order(sku="sku-2")
    second.update(id=" order-1 ", create_time=str(first["create_time"]))
    rows, _ = collect(trial, [{"data": {"orders": [first, second], "total_count": 2}}])
    assert len(rows) == 2 and trial.client.last_page_summary["parent_count"] == 1


@pytest.mark.parametrize("responses,max_pages,code", [
    ([{"data": {"orders": [], "total_count": 1}}], 100, "total_mismatch"),
    ([{"data": {"orders": [], "total_count": 0, "next_page_token": "next"}}], 100, "not_advancing"),
    ([{"data": {"orders": [order()], "total_count": 2, "next_page_token": "next"}},
      {"data": {"orders": [order(sku="sku-2")], "total_count": 2, "next_page_token": "next"}}],
     100, "not_advancing"),
    ([{"data": {"orders": [order()], "total_count": 2, "next_page_token": "next"}}], 1, "limit_exceeded"),
    ([{"data": {"orders": [order(sku="")], "total_count": 1}}], 100, "identity_missing"),
    ([{"data": {"orders": [{**order(), "skus": []}], "total_count": 0}}], 100, "skus_missing"),
])
def test_pagination_and_identity_fail_closed(trial, responses, max_pages, code):
    with pytest.raises(module.DatasetError, match=code):
        collect(trial, responses, max_pages=max_pages)
    assert_no_formal_writes(trial)


def test_empty_day_still_requires_total_on_wire(trial):
    with pytest.raises(module.DatasetError, match="total_count_required"):
        collect(trial, [{"data": {"orders": []}}])
    assert_no_formal_writes(trial)


@pytest.mark.parametrize("mutation", ["version", "count_unit", "headers", "header_time", "header_skus", "source_count",
                                    "sku_count", "unique_count", "observation", "naive_observation", "missing_observation",
                                    "row_time", "duplicate_pair", "total", "cursor"])
def test_cached_proof_is_reconstructed_not_trusted(trial, mutation):
    fetch(trial)
    saved = deepcopy(SyncRawEnvelope.objects.order_by("sequence").first().payload["result"])
    if mutation == "version":
        saved["version"] = "affiliate-daily-v2"
    elif mutation == "count_unit":
        saved["count_unit"] = "parent_order"
    elif mutation == "headers":
        saved["parent_headers"] = []
    elif mutation == "header_time":
        saved["parent_headers"][0]["create_time"] += 1
    elif mutation == "header_skus":
        saved["parent_headers"][0]["sku_count"] += 1
    elif mutation == "source_count":
        saved["source_count"] = True
    elif mutation == "sku_count":
        saved["sku_row_count"] = 2
    elif mutation == "unique_count":
        saved["unique_sku_count"] = True
    elif mutation == "observation":
        saved["rows"][0]["affiliate_observed_at"] = (trial.observed_at + timedelta(days=1)).isoformat()
    elif mutation == "naive_observation":
        saved["observed_at"] = saved["rows"][0]["affiliate_observed_at"] = "2026-10-08T01:00:00"
    elif mutation == "missing_observation":
        saved["rows"][0].pop("affiliate_observed_at")
    elif mutation == "row_time":
        saved["rows"][0]["create_time"] = str(saved["rows"][0]["create_time"])
    elif mutation == "duplicate_pair":
        saved["rows"].append(deepcopy(saved["rows"][0]))
        saved["sku_row_count"] = saved["unique_sku_count"] = saved["total"] = 2
        saved["parent_headers"][0]["sku_count"] = 2
    elif mutation == "total":
        saved["total"] = "1"
    elif mutation == "cursor":
        saved["input_token"] = "wrong"
    checkpoint = Mock()
    checkpoint.load.return_value = saved
    with pytest.raises(module.DatasetError):
        collect(trial, [], checkpoint=checkpoint)
    trial.client._transport_request.assert_not_called()
    assert_no_formal_writes(trial)


@pytest.mark.parametrize("mutation", ["schema", "version", "count_unit", "scope", "digest"])
def test_journal_load_requires_schema_payload_contract_scope_and_digest(trial, mutation):
    fetch(trial)
    entry = SyncRawEnvelope.objects.order_by("sequence").first()
    payload = deepcopy(entry.payload)
    changes = {}
    if mutation == "schema":
        changes["schema_version"] = "affiliate-daily-v2"
    elif mutation == "version":
        payload["version"] = "affiliate-daily-v2"
    elif mutation == "count_unit":
        payload["count_unit"] = "parent_order"
    elif mutation == "scope":
        payload["scope"]["day"] = "2026-10-09"
    else:
        payload["result"]["total"] = 2
    changes.update(payload=payload, payload_hash=entry.payload_hash if mutation == "digest" else payload_digest(payload))
    for key, value in changes.items():
        setattr(entry, key, value)
    trial.client._transport_request = Mock(side_effect=AssertionError("invalid cache must fail before provider call"))
    with patch.object(module.SyncRawEnvelope.objects, "filter", return_value=Mock(first=Mock(return_value=entry))), \
            pytest.raises(ReadonlyConfigurationError, match="checkpoint"):
        trial.adapter.fetch_page(trial.job, "")
    trial.client._transport_request.assert_not_called()
    assert_no_formal_writes(trial)


def test_v2_journal_namespace_is_not_reused_or_rewritten(trial):
    fetch(trial)
    entry = SyncRawEnvelope.objects.order_by("sequence").first()
    scope = entry.payload["scope"]
    descriptor = {"store_id": trial.store.pk, "path": "/affiliate_seller/202410/orders/search", "field": "orders",
                  "query": {}, "body": {"create_time_ge": int(datetime(2026, 8, 16, tzinfo=module.ZoneInfo("Asia/Manila")).timestamp()),
                                          "create_time_lt": int(datetime(2026, 8, 17, tzinfo=module.ZoneInfo("Asia/Manila")).timestamp())},
                  "page": 1, "version": module.VERSION, "count_unit": "sku_row"}
    assert module.DatabasePageJournal(trial.job, trial.run, scope).load(descriptor) is not None
    scope = deepcopy(scope)
    scope["plan"]["snapshot_source"] += "-isolated"
    journal = module.DatabasePageJournal(trial.job, trial.run, scope)
    old_scope = deepcopy(scope)
    old_scope["plan"]["version"] = "affiliate-daily-v2"
    old_scope["plan"].pop("count_unit")
    old_descriptor = {key: value for key, value in descriptor.items() if key not in {"version", "count_unit"}}
    old_endpoint = "checkpoint://affiliate/" + module.digest_bytes(module.canonical_bytes({"scope": old_scope, "query": old_descriptor}))
    old_payload = {"version": "affiliate-daily-v2", "scope": old_scope, "result": entry.payload["result"]}
    old_entry = SyncRawEnvelope.objects.create(tenant_id=trial.job.tenant_id, sync_run=trial.run, store=trial.store,
        platform="tiktok", sequence=trial.run.raw_envelopes.count() + 1, endpoint=old_endpoint,
        schema_version="affiliate-daily-v2", payload=old_payload, payload_hash=payload_digest(old_payload))
    assert journal.load(descriptor) is None
    old_entry.refresh_from_db()
    assert old_entry.endpoint == old_endpoint and old_entry.payload == old_payload


def test_adapter_rechecks_sku_count_proof_before_order_details(trial):
    trial.adapter._client()
    trial.client.affiliate_orders = Mock(return_value=([], 1))
    trial.client.last_page_summary = {"status": "complete", "pagination_exhausted": True,
        "version": module.VERSION, "count_unit": "sku_row", "expected_count": 1,
        "observed_count": 1, "sku_row_count": 1, "unique_sku_count": 1}
    trial.client._transport_request = Mock(side_effect=AssertionError("unproven day"))
    with pytest.raises(ReadonlyConfigurationError, match="sku_count_proof_required"):
        trial.adapter.fetch_page(trial.job, "")
    trial.client._transport_request.assert_not_called()
    assert_no_formal_writes(trial)


@pytest.mark.parametrize("mutation", ["v2", "missing_count_unit", "parent_count_unit"])
def test_frozen_old_or_unproven_plan_fails_before_provider_calls(trial, mutation):
    plan = trial.adapter.scope["affiliate_plan"]
    if mutation == "v2":
        plan["version"] = "affiliate-daily-v2"
    elif mutation == "missing_count_unit":
        plan.pop("count_unit")
    else:
        plan["count_unit"] = "parent_order"
    with pytest.raises(ReadonlyConfigurationError, match="FROZEN_SCOPE_MISMATCH"):
        trial.adapter.fetch_page(trial.job, "")
    trial.client.verify_shop.assert_not_called()
    assert_no_formal_writes(trial)


@pytest.mark.parametrize("cursor", ["a1:synthetic-run:0", "a3:other-run:0", "a3:synthetic-run:00",
                                  "a3:synthetic-run:x", "a3:synthetic-run:-1", "a3:synthetic-run:1"])
def test_old_wrong_or_out_of_range_cursor_fails_closed(trial, cursor):
    with pytest.raises(ReadonlyConfigurationError, match="INVALID_DAY_CURSOR"):
        trial.adapter.fetch_page(trial.job, cursor)
    trial.client.verify_shop.assert_not_called()
    assert_no_formal_writes(trial)


def test_a3_continuation_uses_frozen_next_day_and_does_not_move_trial_progress(trial):
    trial.adapter.scope["affiliate_plan"]["days"].append((DAY + timedelta(days=1)).isoformat())
    first = fetch(trial)
    assert first["next_cursor"] == "a3:synthetic-run:1"
    second = order()
    second["create_time"] += 86400
    trial.client._transport_request = Mock(side_effect=[{"data": {"orders": [second], "total_count": 1}},
                                                       {"data": {"orders": [detail()]}}])
    page = trial.adapter.fetch_page(trial.job, first["next_cursor"])
    assert page["day"] == "2026-08-17" and page["next_cursor"] == ""
    assert not SyncCursor.objects.filter(sync_job=trial.job).exists()


@pytest.mark.parametrize("mode", ["consistent", "header_conflict", "duplicate", "missing_total"])
def test_timeout_cached_page_then_live_page_preserves_each_observation(trial, mode):
    first_time, second_time = trial.observed_at, trial.observed_at + timedelta(minutes=10)
    trial.client._transport_request = Mock(side_effect=[
        {"data": {"orders": [order()], "total_count": 2, "next_page_token": "next"}}, TimeoutError("synthetic")])
    with patch("django.utils.timezone.now", return_value=first_time), pytest.raises(TimeoutError):
        trial.adapter.fetch_page(trial.job, "")
    second = order(sku="sku-2")
    if mode == "header_conflict":
        second["create_time"] += 1
    elif mode == "duplicate":
        second = order()
    data = {"orders": [second], "total_count": 2}
    if mode == "missing_total":
        data.pop("total_count")
    trial.client._transport_request = Mock(side_effect=[{"data": data}, {"data": {"orders": [detail(line_items=[])]}}])
    with patch("django.utils.timezone.now", return_value=second_time):
        if mode != "consistent":
            with pytest.raises(ReadonlyConfigurationError):
                trial.adapter.fetch_page(trial.job, "")
            assert_no_formal_writes(trial)
            return
        page = trial.adapter.fetch_page(trial.job, "")
    assert [row["affiliate_observed_at"] for row in page["records"]] == [first_time.isoformat(), second_time.isoformat()]
    assert [trial.adapter.normalize_record(row)["source_updated_at"] for row in page["records"]] == [first_time, second_time]
    trial.client._transport_request = Mock(side_effect=AssertionError("cached replay only"))
    with patch("django.utils.timezone.now", return_value=second_time + timedelta(days=1)):
        replay = trial.adapter.fetch_page(trial.job, "")
    assert replay["records"] == page["records"]
    assert_no_formal_writes(trial)
