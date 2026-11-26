from datetime import UTC, date, datetime, timedelta

import pytest
from django.utils import timezone

from apps.integrations import affiliate_sync as module
from apps.integrations.models import SyncCheckpoint, SyncCursor
from apps.integrations.raw_services import archive_raw_page, load_raw_payload
from tests.test_affiliate_daily_ingestion import DAY, detail, fetch, order, trial, write
from tests.test_mock_sync_isolation import context  # noqa: F401

pytestmark = pytest.mark.django_db


def test_mixed_missing_identity_is_quarantined_while_valid_order_persists(trial):
    missing = order(sku="sku-missing", creator_username="")
    missing["id"] = "order-missing"
    valid = order(sku="sku-valid")
    valid["id"] = "order-valid"
    page = fetch(trial, [missing, valid], details=[
        detail(id="order-missing", line_items=[{"id": "line-missing", "sku_id": "sku-missing", "quantity": 1, "sale_price": "10"}]),
        detail(id="order-valid", line_items=[{"id": "line-valid", "sku_id": "sku-valid", "quantity": 1, "sale_price": "10"}]),
    ], total=2)
    # The production sync service archives raw_records, not the filtered records.
    raw_page = {**page, "records": page["raw_records"]}
    envelope = archive_raw_page(trial.job, trial.run, trial.adapter, "", raw_page)
    trial.adapter.page_raw_ref = envelope.raw_ref
    trial.adapter.page_raw_envelope_id = envelope.pk

    assert len(page["records"]) == 1
    assert page["records"][0]["order_id"] == "order-valid"
    assert write(trial, page)[0]["action"] == "created"
    assert trial.adapter.has_pending_identity
    assert trial.adapter.scope_pending_identity
    pending = SyncCursor.objects.get(sync_job=trial.job, cursor_key="affiliate-identity-pending")
    assert DAY.isoformat() in pending.detail_state
    evidence = next(iter(pending.detail_state[DAY.isoformat()].values()))
    assert evidence["reason"] == "affiliate_creator_identity_missing"
    assert evidence["raw_envelope_id"] is not None
    assert evidence["raw_ref"]
    archived = load_raw_payload(envelope)["records"]
    assert archived == page["raw_records"]
    assert evidence["index"] == 0
    assert archived[evidence["index"]]["order_id"] == "order-missing"
    assert archived[evidence["index"]]["creator_username"] == ""
    assert evidence["row_hash"] == module.digest_bytes(module.canonical_bytes(page["raw_records"][0]))


def test_permanent_out_of_floor_pending_does_not_stall_new_or_archive_traversal(trial):
    trial.policy.pop("trial_days", None)
    floor = date(2026, 8, 1)
    trial.policy.update(historical_start=floor.isoformat(), new_days_per_run=2,
                        archive_days_per_run=2, recent_days=2)
    binding = f"{trial.store.pk}:PH"
    outside = date(2026, 7, 31).isoformat()
    SyncCursor.objects.create(tenant=trial.job.tenant, sync_job=trial.job,
        cursor_key="affiliate-identity-pending", cursor_value=binding,
        detail_state={outside: {"opaque": {"reason": "missing"}}})
    # Start archive traversal well before the recent window, while the permanent
    # pending date remains outside the approved floor.
    SyncCursor.objects.create(tenant=trial.job.tenant, sync_job=trial.job,
        cursor_key="affiliate-history-day", cursor_value=floor.isoformat())

    successful_checkpoint = SyncCheckpoint.objects.create(tenant=trial.job.tenant, sync_job=trial.job,
        cursor_json={"default": "successful-page-token"}, watermark_utc=datetime(2026, 7, 30, tzinfo=UTC))
    visited_new = []
    for _ in range(2):
        plan = module.build_plan(trial.job, trial.store, trial.policy,
                                 datetime(2026, 8, 10, tzinfo=UTC))
        trial.adapter.scope["affiliate_plan"] = plan
        assert outside not in plan["days"]
        assert plan["pending_outside_approved_range_count"] == 1
        trial.adapter.page_quarantine = []
        trial.adapter.page_valid_keys = []
        for new_day in plan["new_days"]:
            visited_new.append(new_day)
            trial.adapter.after_page_persist(trial.job, {"day": new_day}, [])
        trial.adapter.finalize_run(trial.job)

    assert len(set(visited_new)) == 4
    assert SyncCursor.objects.get(sync_job=trial.job, cursor_key="affiliate-next-new-day").cursor_value == (date.fromisoformat(visited_new[-1]) + timedelta(days=1)).isoformat()
    assert SyncCursor.objects.get(sync_job=trial.job, cursor_key="affiliate-history-day").cursor_value == "2026-08-05"
    pending = SyncCursor.objects.get(sync_job=trial.job, cursor_key="affiliate-identity-pending")
    assert outside in pending.detail_state
    successful_checkpoint.refresh_from_db()
    assert successful_checkpoint.cursor_json == {"default": "successful-page-token"}
    assert successful_checkpoint.watermark_utc == datetime(2026, 7, 30, tzinfo=UTC)


def test_pending_retry_rotates_four_days_and_clamps_floor_without_dropping_old_pending(trial):
    trial.policy.pop("trial_days", None)
    floor = date(2026, 8, 10)
    trial.policy["historical_start"] = floor.isoformat()
    approved = [date(2026, 8, day).isoformat() for day in range(11, 17)]
    outside = date(2026, 8, 9).isoformat()
    binding = f"{trial.store.pk}:PH"
    SyncCursor.objects.create(tenant=trial.job.tenant, sync_job=trial.job,
        cursor_key="affiliate-identity-pending", cursor_value=binding,
        detail_state={day: {"opaque": {"reason": "missing"}} for day in [*approved, outside]})
    SyncCursor.objects.create(tenant=trial.job.tenant, sync_job=trial.job,
        cursor_key="affiliate-identity-retry-offset", cursor_value=binding,
        detail_state={"offset": 0})
    now = datetime(2026, 8, 17, tzinfo=UTC)

    first = module.build_plan(trial.job, trial.store, trial.policy, now)
    assert set(approved[:4]).issubset(first["days"])
    assert first["identity_retry_next"] == 4
    assert first["pending_outside_approved_range_count"] == 1
    assert first["historical_start"] == floor.isoformat()

    SyncCursor.objects.filter(sync_job=trial.job, cursor_key="affiliate-identity-retry-offset").update(detail_state={"offset": first["identity_retry_next"]})
    second = module.build_plan(trial.job, trial.store, trial.policy, now)
    assert set([*approved[4:], *approved[:2]]).issubset(second["days"])
    assert second["identity_retry_next"] == 2
    assert outside not in second["days"]
    assert SyncCursor.objects.get(sync_job=trial.job, cursor_key="affiliate-identity-pending").detail_state.keys() >= {outside}
