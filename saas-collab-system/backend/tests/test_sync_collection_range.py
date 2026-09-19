from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from rest_framework.exceptions import ValidationError

from apps.integrations.models import SyncCursor, SyncRun
from apps.integrations.readonly_clients import default_sync_scope
from tests.test_mock_sync_isolation import context


NOW = datetime(2026, 9, 17, 2, tzinfo=UTC)


@pytest.mark.parametrize("days", [1, 7, 15])
def test_rolling_scope_uses_requested_days(days):
    config = SimpleNamespace(platform="shopee", platform_config={})
    with patch("apps.integrations.readonly_clients.timezone.now", return_value=NOW):
        scope = default_sync_scope(
            config,
            {"query": {"lookback_days": days}},
            "refund_return",
        )
    assert scope["time_to"] == int(NOW.timestamp())
    expected_start = datetime(2026, 9, 16, 16, tzinfo=UTC) - timedelta(days=days - 1)
    assert scope["time_from"] == int(expected_start.timestamp())


@pytest.mark.parametrize(
    "now,expected",
    [
        (datetime(2026, 9, 16, 15, 59, tzinfo=UTC), datetime(2026, 9, 15, 16, tzinfo=UTC)),
        (datetime(2026, 9, 16, 16, tzinfo=UTC), datetime(2026, 9, 16, 16, tzinfo=UTC)),
    ],
)
def test_rolling_day_changes_at_beijing_midnight(now, expected):
    with patch("apps.integrations.readonly_clients.timezone.now", return_value=now):
        scope = default_sync_scope(
            SimpleNamespace(platform="shopee", platform_config={}),
            {"query": {"lookback_days": 1}},
            "refund_return",
        )
    assert scope["time_from"] == int(expected.timestamp())
    assert scope["time_to"] == int(now.timestamp())


def test_fixed_scope_honors_offsets_not_current_time():
    config = SimpleNamespace(platform="shopee", platform_config={})
    with patch("apps.integrations.readonly_clients.timezone.now", return_value=NOW):
        scope = default_sync_scope(
            config,
            {
                "query": {
                    "mode": "range",
                    "start_at": "2026-09-10T00:00:00+08:00",
                    "end_at": "2026-09-14T00:00:00+08:00",
                }
            },
            "refund_return",
        )
    assert datetime.fromtimestamp(scope["time_from"], UTC).isoformat() == "2026-09-09T16:00:00+00:00"
    assert scope["time_to"] - scope["time_from"] == 4 * 86400


@pytest.mark.parametrize(
    "query",
    [
        {"lookback_days": 16},
        {"lookback_days": 0},
        {"lookback_days": "invalid"},
        {"lookback_days": True},
        {"lookback_days": "1.0"},
        {"mode": "range", "start_at": "2026-09-18", "end_at": "2026-09-18"},
        {"mode": "range", "start_at": "2026-09-14", "end_at": "2026-09-10"},
        {"mode": "range", "start_at": "2026-09-02", "end_at": "2026-09-17"},
        {"mode": "range", "start_at": "2026-02-30", "end_at": "2026-09-17"},
        {"mode": "range", "start_at": "2026-09-14T00:00:00Z", "end_at": "2026-09-10T00:00:00Z"},
        {"mode": "range", "start_at": "2026-09-01T00:00:00Z", "end_at": "2026-09-17T00:00:00Z"},
        {"mode": "range", "start_at": "2026-09-10T00:00:00Z", "end_at": "2026-09-18T00:00:00Z"},
    ],
)
def test_invalid_range_is_not_silently_clipped(query):
    with patch("apps.integrations.readonly_clients.timezone.now", return_value=NOW), pytest.raises(ValidationError):
        default_sync_scope(
            SimpleNamespace(platform="shopee", platform_config={}),
            {"query": query},
            "refund_return",
        )


@pytest.mark.parametrize(
    "start,end,expected_start,expected_end",
    [
        ("2026-09-10", "2026-09-10", "2026-09-09T16:00:00+00:00", "2026-09-10T15:59:59+00:00"),
        ("2026-09-03", "2026-09-17", "2026-09-02T16:00:00+00:00", NOW.isoformat()),
        ("2026-09-02", "2026-09-16", "2026-09-01T16:00:00+00:00", "2026-09-16T15:59:59+00:00"),
    ],
)
def test_date_range_includes_end_day_and_caps_today(start, end, expected_start, expected_end):
    with patch("apps.integrations.readonly_clients.timezone.now", return_value=NOW):
        scope = default_sync_scope(
            SimpleNamespace(platform="shopee", platform_config={}),
            {"query": {"mode": "range", "start_at": start, "end_at": end}},
            "refund_return",
        )
    assert datetime.fromtimestamp(scope["time_from"], UTC).isoformat() == expected_start
    assert datetime.fromtimestamp(scope["time_to"], UTC).isoformat() == expected_end


@pytest.mark.django_db
def test_save_range_resets_old_page_without_running_or_enabling(context):
    client, job = context
    job.resource_type = "refund_return"
    job.is_enabled = False
    job.status = "disabled"
    job.save()
    SyncCursor.objects.create(
        tenant=job.tenant,
        sync_job=job,
        cursor_key="default",
        cursor_value="8",
    )
    url = f"/api/internal/integrations/sync-jobs/{job.id}/"
    response = client.patch(
        url,
        {"query_mode": "incremental", "lookback_days": 7},
        format="json",
    )
    assert response.status_code == 200, response.data
    job.refresh_from_db()
    assert job.sync_scope["query"]["lookback_days"] == 7
    assert not job.is_enabled
    assert job.cursors.get(cursor_key="default").cursor_value == ""
    assert not SyncRun.objects.filter(sync_job=job).exists()
