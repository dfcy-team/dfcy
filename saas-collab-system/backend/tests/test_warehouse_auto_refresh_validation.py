"""Recover through the capability-matrix HTTP action, without token rotation."""
from unittest.mock import Mock

import pytest
from rest_framework.test import APIClient

from apps.integrations import automatic_refresh as service
from apps.integrations.oauth_errors import OAUTH_AUTH_REJECTED, OAuthFlowError
from apps.integrations.readonly_clients import JifengWmsReadonlyClient
from tests.test_automatic_credential_refresh import _automatic_warehouse_job


@pytest.mark.django_db
@pytest.mark.parametrize("failure", [TimeoutError(), OAuthFlowError(OAUTH_AUTH_REJECTED, "synthetic rejection")])
def test_capability_matrix_recovers_saved_token_without_refresh(monkeypatch, failure):
    actor, record, job, refresh = _automatic_warehouse_job(monkeypatch)
    monkeypatch.setattr(service, "validate_refreshed_authorization", Mock(side_effect=failure))
    assert service.refresh_due_authorizations()["failed"] == 1
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
