from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.utils import timezone

from apps.integrations import automatic_refresh as service
from apps.integrations.models import (
    AutomaticRefreshAttempt,
    SyncJob,
    SyncRun,
    SyncSchedulerHeartbeat,
)
from apps.integrations.oauth_errors import OAUTH_PROVIDER_UNAVAILABLE, OAUTH_RATE_LIMITED, OAuthFlowError
from tests.test_automatic_credential_refresh import due_warehouse

pytestmark = pytest.mark.django_db


def _error(stage, category=None, code=OAUTH_PROVIDER_UNAVAILABLE, status=503, message="FAKE_RAW_SECRET"):
    exc = OAuthFlowError(code, message)
    exc.stage = stage
    exc.category = category
    exc.http_status = status
    return exc


def _refresh(monkeypatch, mock):
    monkeypatch.setattr("apps.integrations.warehouse_credential_service.refresh_warehouse_authorization", mock)


def test_safe_pre_request_failures_wait_backoff_and_succeed_with_three_claims(monkeypatch):
    _, record = due_warehouse(monkeypatch)
    now = [timezone.now()]
    monkeypatch.setattr(service.timezone, "now", lambda: now[0])
    refresh = Mock(side_effect=[
        _error("read_developer_secret", "timeout_uncertain"),
        _error("read_developer_secret", "network_uncertain"),
        record,
    ])
    _refresh(monkeypatch, refresh)

    assert service.refresh_due_authorizations() == {"attempted": 1, "success": 0, "failed": 1}
    attempt = AutomaticRefreshAttempt.objects.get()
    assert attempt.attempt_count == 1
    assert attempt.next_retry_at == now[0] + timedelta(seconds=60)
    assert service.refresh_due_authorizations()["attempted"] == 0
    now[0] += timedelta(seconds=60)
    assert service.refresh_due_authorizations()["failed"] == 1
    attempt.refresh_from_db()
    assert attempt.attempt_count == 2
    assert attempt.next_retry_at == now[0] + timedelta(seconds=120)
    now[0] += timedelta(seconds=120)
    assert service.refresh_due_authorizations() == {"attempted": 1, "success": 1, "failed": 0}
    attempt.refresh_from_db()
    assert attempt.status == "success" and attempt.attempt_count == 3
    assert attempt.failure_category == "" and attempt.next_retry_at is None
    assert refresh.call_count == 3


@pytest.mark.parametrize("exc,expected", [
    (_error("exchange_token", None, OAUTH_RATE_LIMITED, 429), "rate_limited"),
    (_error("read_developer_secret", "service_uncertain"), "pre_request_transient"),
])
def test_only_closed_safe_classifications_schedule_retries(monkeypatch, exc, expected):
    _, _record = due_warehouse(monkeypatch)
    refresh = Mock(side_effect=exc)
    _refresh(monkeypatch, refresh)
    service.refresh_due_authorizations()
    attempt = AutomaticRefreshAttempt.objects.get()
    assert attempt.failure_category == expected and attempt.next_retry_at


@pytest.mark.parametrize("exc", [
    RuntimeError("legacy failed FAKE_RAW_SECRET"),
    _error("exchange_token", "timeout_uncertain"),
    _error("save_token", "database_failure"),
    _error("read_developer_secret", "tls_failure", status=429),
])
def test_ambiguous_and_legacy_failures_never_replay(monkeypatch, exc):
    _, record = due_warehouse(monkeypatch)
    refresh = Mock(side_effect=exc)
    _refresh(monkeypatch, refresh)
    service.refresh_due_authorizations()
    attempt = AutomaticRefreshAttempt.objects.get()
    assert attempt.status == "failed" and attempt.next_retry_at is None
    assert service.refresh_due_authorizations()["attempted"] == 0
    assert refresh.call_count == 1
    assert service.credential_refresh_state(record)["state"] == "manual_recovery"


@pytest.mark.parametrize("gate", ["disabled", "active_run"])
def test_retry_scan_rechecks_runtime_and_active_run_gates(monkeypatch, gate):
    _, record = due_warehouse(monkeypatch)
    attempt = AutomaticRefreshAttempt.objects.create(
        request_key=service._attempt_key(record), tenant=record.tenant, status="failed",
        attempt_count=1, failure_category="pre_request_transient", next_retry_at=timezone.now() - timedelta(seconds=1),
    )
    refresh = Mock()
    _refresh(monkeypatch, refresh)
    if gate == "disabled":
        monkeypatch.setattr(service, "get_runtime_platform_config", lambda platform: {})
    else:
        job = SyncJob.objects.create(tenant=record.tenant, integration_config=record.integration_config,
                                     warehouse_authorization=record, resource_type="inventory_snapshot")
        SyncRun.objects.create(tenant=record.tenant, sync_job=job, status="running")
    assert service.refresh_due_authorizations()["attempted"] == 0
    attempt.refresh_from_db()
    assert attempt.status == "failed" and attempt.attempt_count == 1
    refresh.assert_not_called()


def test_refresh_metadata_is_closed_and_heartbeat_age_is_reported(monkeypatch):
    _, record = due_warehouse(monkeypatch)
    exc = _error("exchange_token", "timeout_uncertain")
    refresh = Mock(side_effect=exc)
    _refresh(monkeypatch, refresh)
    service.refresh_due_authorizations()
    state = service.credential_refresh_state(record)
    serialized = str(state)
    assert "FAKE_RAW_SECRET" not in serialized
    assert record.token_id not in serialized
    assert state["failure_category"] == "rotation_uncertain"

    assert service.credential_scheduler_health()["heartbeat_state"] == "recent"
    SyncSchedulerHeartbeat.objects.filter(key="credential-refresh").update(
        last_seen_at=timezone.now() - timedelta(minutes=4),
    )
    assert service.credential_scheduler_health()["heartbeat_state"] == "stale"
    SyncSchedulerHeartbeat.objects.filter(key="credential-refresh").delete()
    assert service.credential_scheduler_health()["heartbeat_state"] == "unknown"
