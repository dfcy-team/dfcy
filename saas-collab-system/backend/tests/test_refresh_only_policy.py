from unittest.mock import Mock

import pytest

from apps.integrations import automatic_refresh as service
from apps.integrations import warehouse_credential_service
from tests.test_automatic_credential_refresh import _automatic_warehouse_job

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("enabled", [True, False])
def test_refresh_only_never_reads_or_changes_job_state(monkeypatch, enabled):
    _, record, job, refresh = _automatic_warehouse_job(monkeypatch)
    job.is_enabled = enabled
    job.status = "idle" if enabled else "disabled"
    job.save()
    check = Mock(side_effect=AssertionError("Refresh must not call readonly API"))
    monkeypatch.setattr(service, "validate_refreshed_authorization", check)
    assert service.refresh_due_authorizations() == {"attempted": 1, "success": 1, "failed": 0}
    assert refresh.call_count == 1
    check.assert_not_called()
    job.refresh_from_db()
    assert job.is_enabled is enabled
    assert job.status == ("idle" if enabled else "disabled")


def test_manual_refresh_does_not_route_old_validation_error_to_validation(monkeypatch):
    from rest_framework.test import APIClient
    _, record, _, refresh = _automatic_warehouse_job(monkeypatch)
    monkeypatch.setattr("apps.integrations.warehouse_credential_views.refresh_warehouse_authorization", refresh)
    record.last_error_code = service.AUTO_REFRESH_VALIDATION_FAILED
    record.save()
    check = Mock(side_effect=AssertionError("No revalidation during refresh"))
    monkeypatch.setattr(service, "revalidate_saved_authorization", check)
    client = APIClient()
    client.force_authenticate(record.updated_by)
    response = client.post(f"/api/internal/integrations/warehouse-authorizations/{record.pk}/refresh/", {}, format="json")
    assert response.status_code == 200
    check.assert_not_called()
    refresh.assert_called_once()


def test_matrix_check_rejects_closed_saved_capability_before_external_call(monkeypatch):
    from rest_framework.test import APIClient
    from tests.test_store_api_merge_closure import _context, _grant_all_integration_access
    context = _context()
    _grant_all_integration_access(context["user"])
    record = context["authorizations"][0]
    record.connection_capabilities.filter(capability_code="ORDER").update(read_enabled=False)
    adapter = Mock()
    monkeypatch.setattr("apps.integrations.views.get_adapter_for_config", adapter)
    client = APIClient()
    client.force_authenticate(context["user"])
    response = client.post(f"/api/internal/integrations/configs/{record.integration_config_id}/readonly-check/",
        {"store_authorization_id": record.pk, "resource_type": "sales_order"}, format="json")
    assert response.status_code == 400
    adapter.assert_not_called()


def test_matrix_check_does_not_fall_back_to_another_resource(monkeypatch):
    from rest_framework.test import APIClient
    from tests.test_store_api_merge_closure import _context, _grant_all_integration_access
    context = _context()
    _grant_all_integration_access(context["user"])
    record = context["authorizations"][0]
    adapter = Mock()
    monkeypatch.setattr("apps.integrations.views.get_adapter_for_config", adapter)
    client = APIClient()
    client.force_authenticate(context["user"])
    response = client.post(f"/api/internal/integrations/configs/{record.integration_config_id}/readonly-check/",
        {"store_authorization_id": record.pk, "resource_type": "settlement_bill"}, format="json")
    assert response.status_code == 400
    adapter.assert_not_called()
