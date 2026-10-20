"""Recover through the capability-matrix HTTP action, without token rotation."""
from unittest.mock import Mock

import pytest
from rest_framework.test import APIClient

from apps.integrations import automatic_refresh as service
from apps.integrations.models import (
    AutomaticRefreshAttempt, IntegrationAuditLog, SyncAlertIncident, SyncJob, WarehouseAuthorization,
)
from apps.integrations.oauth_errors import OAUTH_AUTH_REJECTED, OAuthFlowError
from apps.integrations.readonly_clients import JifengWmsReadonlyClient
from tests.test_automatic_credential_refresh import _automatic_warehouse_job


@pytest.mark.django_db
@pytest.mark.parametrize("failure", [TimeoutError(), OAuthFlowError(OAUTH_AUTH_REJECTED, "synthetic rejection")])
def test_capability_matrix_recovers_saved_token_without_refresh(monkeypatch, failure):
    actor, record, job, refresh = _automatic_warehouse_job(monkeypatch)
    monkeypatch.setattr(service, "validate_refreshed_authorization", Mock(side_effect=failure))
    assert service.refresh_due_authorizations()["failed"] == 1
    assert SyncAlertIncident.objects.filter(sync_job=job).count() == 1
    record.refresh_from_db()
    saved_token = record.token_id

    monkeypatch.setattr("apps.integrations.warehouse_credential_views.warehouse_config_blockers", lambda config: [])
    monkeypatch.setattr(JifengWmsReadonlyClient, "preflight", lambda self: None)
    fetch = Mock(return_value={"records": []})
    monkeypatch.setattr(JifengWmsReadonlyClient, "fetch_inventory", fetch)
    client = APIClient()
    client.force_authenticate(actor)
    response = client.post(
        f"/api/internal/integrations/warehouse-authorizations/{record.pk}/readonly-check/", {}, format="json",
    )
    assert response.status_code == 200, response.data
    assert response.data["data"]["connected"] is True
    fetch.assert_called_once()
    refresh.assert_called_once()
    record.refresh_from_db()
    assert record.token_id == saved_token
    assert record.validation_status == "verified"
    assert record.last_error_code == ""
    job.refresh_from_db()
    assert not job.is_enabled  # Explicitly review/re-enable tasks after recovery.


@pytest.mark.django_db
def test_config_change_during_successful_post_refresh_validation_is_fenced(monkeypatch):
    _, record, job, _ = _automatic_warehouse_job(monkeypatch)

    def mutate_config_then_succeed(candidate):
        type(record.integration_config).objects.filter(pk=record.integration_config_id).update(
            config_version=record.integration_config.config_version + 1,
        )
        # Simulate the newer configuration's operator restoring the job while
        # the older network validation is still in flight.
        SyncJob.objects.filter(pk=job.pk).update(is_enabled=True, status=SyncJob.Status.IDLE)
        return {"records": []}

    monkeypatch.setattr(service, "validate_refreshed_authorization", mutate_config_then_succeed)
    assert service.refresh_due_authorizations() == {"attempted": 1, "success": 0, "failed": 1}
    record.refresh_from_db()
    job.refresh_from_db()
    attempt = AutomaticRefreshAttempt.objects.get()
    audit = IntegrationAuditLog.objects.get(action="automatic_refresh")
    assert record.validation_status == WarehouseAuthorization.ValidationStatus.PENDING
    assert record.last_error_code == service.AUTO_REFRESH_VALIDATION_PENDING
    assert job.is_enabled and job.status == SyncJob.Status.IDLE
    assert attempt.status == "token_saved"
    assert audit.masked_detail["error_code"] == "AUTO_REFRESH_VALIDATION_STALE"
    assert not SyncAlertIncident.objects.filter(sync_job=job).exists()


@pytest.mark.django_db
def test_token_rotation_during_failed_validation_does_not_pause_current_generation(monkeypatch):
    _, record, job, _ = _automatic_warehouse_job(monkeypatch)

    def rotate_then_reject(candidate):
        WarehouseAuthorization.objects.filter(pk=record.pk).update(
            token_id="synthetic-newer-generation", validation_status="verified", last_error_code="",
        )
        SyncJob.objects.filter(pk=job.pk).update(is_enabled=True, status=SyncJob.Status.IDLE)
        raise OAuthFlowError(OAUTH_AUTH_REJECTED, "synthetic stale rejection")

    monkeypatch.setattr(service, "validate_refreshed_authorization", rotate_then_reject)
    assert service.refresh_due_authorizations() == {"attempted": 1, "success": 0, "failed": 1}
    record.refresh_from_db()
    job.refresh_from_db()
    attempt = AutomaticRefreshAttempt.objects.get()
    assert record.token_id == "synthetic-newer-generation"
    assert record.validation_status == WarehouseAuthorization.ValidationStatus.VERIFIED
    assert record.last_error_code == ""
    assert job.is_enabled and job.status == SyncJob.Status.IDLE
    assert attempt.status == "token_saved"
    assert not SyncAlertIncident.objects.filter(sync_job=job).exists()
