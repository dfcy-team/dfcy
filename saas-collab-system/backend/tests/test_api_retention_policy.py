from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from rest_framework.exceptions import ValidationError

from apps.integrations.adapters import MarketplaceOrderAdapter
from apps.integrations.history_sync import _history_range
from apps.integrations.retention_policy import (
    RETENTION_START_UTC,
    bounded_range,
    is_legacy_fact,
    is_skipped_fact,
)
from apps.integrations.sync_policy import resolve_job_scope
from apps.integrations.models import SyncCursor
from apps.integrations.sync_services import run_sync_job
from tests.test_mock_sync_isolation import context

pytestmark = pytest.mark.django_db


def test_fact_dates_use_utc_and_store_timezone_boundaries():
    assert is_legacy_fact("sales_order", {"create_time": "2024-12-31T23:59:59Z"})
    assert not is_legacy_fact("sales_order", {"create_time": "2025-01-01T00:00:00Z"})
    assert is_legacy_fact("refund_return", {"requested_at_utc": "2024-12-31T23:59:59Z"})
    assert not is_legacy_fact("refund_return", {"requested_at_utc": "2025-01-01T00:00:00Z"})

    store = SimpleNamespace(timezone="Asia/Shanghai")
    assert is_legacy_fact("settlement_bill", {"occurred_at": "2024-12-31T15:59:59Z"}, store)
    assert not is_legacy_fact("settlement_bill", {"occurred_at": "2024-12-31T16:00:00Z"}, store)
    manila = SimpleNamespace(timezone="Asia/Manila")
    assert is_legacy_fact("settlement_bill", {"occurred_at": "2024-12-31T15:59:59Z"}, manila)
    assert not is_legacy_fact("settlement_bill", {"occurred_at": "2024-12-31T16:00:00Z"}, manila)
    assert is_legacy_fact("inventory_snapshot", {"_snapshot_at_utc": "2024-12-31T23:59:59Z"})


@pytest.mark.parametrize("stamp", [1735689599000, "1735689599000", 1735689599, "1735689599"])
def test_numeric_and_string_timestamps_share_the_same_retention_boundary(stamp):
    assert is_legacy_fact("sales_order", {"create_time": stamp})
    assert is_legacy_fact("refund_return", {"create_time": stamp})
    assert is_legacy_fact("settlement_bill", {"occurred_at": stamp}, SimpleNamespace(timezone="UTC"))


def test_query_floor_rejects_all_old_and_clips_crossing_ranges():
    floor = int(RETENTION_START_UTC.timestamp())
    assert bounded_range(floor - 3600, floor + 1, "sales_order") == (floor, floor + 1)
    with pytest.raises(ValidationError, match="不能早于 2025-01-01"):
        bounded_range(floor - 7200, floor - 1, "refund_return")

    local_floor = int(datetime(2025, 1, 1, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp())
    assert bounded_range(0, local_floor + 1, "settlement_bill", SimpleNamespace(timezone="Asia/Shanghai")) == (
        local_floor, local_floor + 1,
    )
    # Product catalogue time ranges describe refreshes, not historical business facts.
    assert bounded_range(1, 2, "platform_product") == (1, 2)


def test_old_fact_at_adapter_boundary_is_valid_skipped_and_never_persisted():
    adapter = MarketplaceOrderAdapter(SimpleNamespace(platform_config={}))
    adapter.resource_type = "sales_order"
    adapter.source_run = SimpleNamespace(masked_log={})
    marker = adapter.normalize_record({"create_time": "2024-12-31T23:59:59Z", "item_list": [{"item_id": "x"}]})
    assert is_skipped_fact(marker)
    assert adapter.validate_record(marker)
    assert adapter.source_run.masked_log["retention_skipped_count"] == 1

    job = SimpleNamespace(id=17)
    result = adapter.persist_records(job, [marker])
    assert result == [{"action": "skipped", "idempotency_key": "17:retention-floor"}]
    assert adapter.persist_record(job, marker)["action"] == "skipped"


def test_old_fact_advances_real_adapter_pagination_without_failure(context):
    _, job = context
    job.resource_type = "sales_order"
    job.save(update_fields=["resource_type"])
    adapter = MarketplaceOrderAdapter(job.integration_config)
    adapter.execution_mode = "mock"
    adapter.validate_configuration = lambda candidate: setattr(adapter, "resource_type", candidate.resource_type)
    pages = [
        {"records": [{"create_time": "2024-12-31T23:59:59Z", "item_list": [{"item_id": "old"}]}],
         "next_cursor": "page-2"},
        {"records": [], "next_cursor": ""},
    ]
    calls = []

    def fetch_page(_job, cursor):
        calls.append(cursor)
        return pages.pop(0)

    adapter.fetch_page = fetch_page
    with patch("apps.integrations.sync_services.require_sync_read_capability"), \
            patch("apps.integrations.sync_services.record_sync_source_decision"):
        run, _ = run_sync_job(job, adapter=adapter, idempotency_key="retention-pagination")

    assert calls == ["", "page-2"]
    assert run.status == "success"
    assert run.fetched_count == 1 and run.skipped_count == 1 and run.failed_count == 0
    assert run.masked_log["retention_skipped_count"] == 1
    assert SyncCursor.objects.get(sync_job=job).cursor_value == ""


def test_checkpoint_frozen_scope_is_clamped_after_continuation_restore(context):
    _, job = context
    job.resource_type = "sales_order"
    job._frozen_sync_scope = {"time_from": 1, "time_to": int(RETENTION_START_UTC.timestamp()) + 10, "page_size": 100}
    resolved = resolve_job_scope(job)
    assert resolved["time_from"] == int(RETENTION_START_UTC.timestamp())
    assert resolved["time_to"] == int(RETENTION_START_UTC.timestamp()) + 10

    job._frozen_sync_scope["time_to"] = int(RETENTION_START_UTC.timestamp()) - 1
    with pytest.raises(ValidationError, match="不能早于 2025-01-01"):
        resolve_job_scope(job)


def test_history_scope_clips_crossing_date_and_rejects_fully_old():
    now = datetime(2026, 10, 15, 12, tzinfo=UTC)
    bounded = _history_range({"start_date": "2024-12-20", "end_date": "2025-01-05"}, now)
    assert bounded[0] == date(2025, 1, 1)
    with pytest.raises(ValidationError, match="不能早于 2025-01-01"):
        _history_range({"start_date": "2024-12-01", "end_date": "2024-12-31"}, now)
