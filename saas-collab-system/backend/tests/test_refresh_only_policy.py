from unittest.mock import Mock
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

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


@pytest.mark.parametrize("status", ["pending", "failed", "verified"])
def test_warehouse_sync_rejects_unverified_current_token(status):
    from tests.test_jifeng_warehouse_credentials import binding
    from tests.test_warehouse_api_binding_closure import _mark_verified
    _, record = binding()
    _mark_verified(record.pk)
    record.refresh_from_db()
    record.validation_status = status
    record.last_verified_at = None
    record.last_error_code = ""
    with pytest.raises(ValidationError, match="能力矩阵"):
        warehouse_credential_service.require_verified_warehouse(record)


def _ready_warehouse_check(monkeypatch, settings):
    from apps.integrations import warehouse_readiness
    from apps.integrations.models import authorization_service_write
    from tests.test_jifeng_warehouse_credentials import binding
    from tests.test_warehouse_api_binding_closure import _mark_verified
    actor, record = binding()
    _mark_verified(record.pk)
    record.refresh_from_db()
    record.validation_status = "pending"
    record.last_verified_at = None
    record.oauth_expires_at = timezone.now() + timedelta(hours=1)
    record.save()
    config = record.integration_config
    config.network_enabled = True
    config.sync_read_enabled = True
    config.sync_write_enabled = False
    config.platform_config = {"api_host": "https://example.test/api", "domain": "TEST", "client_id": "TEST_CLIENT"}
    with authorization_service_write():
        config.save()
    runtime = {"mode": "approved-live-test", "security_approved": True,
        "readonly_sync_enabled": True, "allowed_hosts": ["example.test"]}
    platform = {"contract_approved": True}
    settings.DEBUG = False
    monkeypatch.setattr(warehouse_readiness, "is_module_enabled", lambda *args: True)
    monkeypatch.setattr(warehouse_readiness, "approved_custody_configured", lambda: True)
    monkeypatch.setattr(warehouse_readiness, "get_runtime_setting", lambda section, key, default=None: runtime.get(key, default))
    monkeypatch.setattr(warehouse_readiness, "get_runtime_platform_config", lambda *args: platform)
    client = APIClient()
    client.force_authenticate(actor)
    return client, record, config, runtime, platform


@pytest.mark.parametrize("gate", ["read", "network", "mode", "readonly_sync", "host", "contract", "write"])
def test_direct_warehouse_check_enforces_existing_gates_before_client_construction(monkeypatch, settings, gate):
    from apps.integrations.models import authorization_service_write
    client, record, config, runtime, platform = _ready_warehouse_check(monkeypatch, settings)
    if gate in {"read", "network", "write"}:
        setattr(config, {"read": "sync_read_enabled", "network": "network_enabled", "write": "sync_write_enabled"}[gate], gate == "write")
        with authorization_service_write():
            config.save()
    elif gate == "mode":
        runtime["mode"] = "mock"
    elif gate == "readonly_sync":
        runtime["readonly_sync_enabled"] = False
    elif gate == "host":
        runtime["allowed_hosts"] = []
    else:
        platform["contract_approved"] = False
    constructor = Mock(side_effect=AssertionError("No client or external call before gates pass"))
    monkeypatch.setattr("apps.integrations.warehouse_credential_views.JifengWmsReadonlyClient", constructor)
    response = client.post(f"/api/internal/integrations/warehouse-authorizations/{record.pk}/readonly-check/", {}, format="json")
    assert response.status_code == 400
    constructor.assert_not_called()
    record.refresh_from_db()
    assert record.validation_status == "pending"
    assert record.last_verified_at is None


def test_explicit_warehouse_check_requires_no_separate_approval_or_job(monkeypatch, settings):
    client, record, _, _, _ = _ready_warehouse_check(monkeypatch, settings)
    readonly = Mock()
    readonly.fetch_inventory.return_value = {"records": []}
    constructor = Mock(return_value=readonly)
    monkeypatch.setattr("apps.integrations.warehouse_credential_views.JifengWmsReadonlyClient", constructor)
    response = client.post(f"/api/internal/integrations/warehouse-authorizations/{record.pk}/readonly-check/", {}, format="json")
    assert response.status_code == 200
    readonly.preflight.assert_called_once()
    readonly.fetch_inventory.assert_called_once_with(None, {"page_size": 1})
    record.refresh_from_db()
    assert record.validation_status == "verified"
    warehouse_credential_service.require_verified_warehouse(record)


def test_warehouse_check_cannot_bypass_warehouse_scope(monkeypatch, settings):
    client, record, _, _, _ = _ready_warehouse_check(monkeypatch, settings)
    monkeypatch.setattr("apps.integrations.warehouse_credential_views.integration_values_allowed", lambda *args, **kwargs: False)
    constructor = Mock()
    monkeypatch.setattr("apps.integrations.warehouse_credential_views.JifengWmsReadonlyClient", constructor)
    response = client.post(f"/api/internal/integrations/warehouse-authorizations/{record.pk}/readonly-check/", {}, format="json")
    assert response.status_code == 403
    constructor.assert_not_called()


def test_warehouse_matrix_check_recovers_saved_token_without_refresh(monkeypatch, settings):
    client, record, _, _, _ = _ready_warehouse_check(monkeypatch, settings)
    record.validation_status = "failed"
    record.last_error_code = "AUTO_REFRESH_VALIDATION_FAILED"
    record.save()
    original_token = record.token_id
    readonly = Mock()
    readonly.fetch_inventory.return_value = {"records": []}
    constructor = Mock(return_value=readonly)
    monkeypatch.setattr("apps.integrations.warehouse_credential_views.JifengWmsReadonlyClient", constructor)
    refresh = Mock()
    monkeypatch.setattr("apps.integrations.warehouse_credential_views.refresh_warehouse_authorization", refresh)
    response = client.post(f"/api/internal/integrations/warehouse-authorizations/{record.pk}/readonly-check/", {}, format="json")
    assert response.status_code == 200
    assert constructor.call_args.args[1].last_error_code == ""
    refresh.assert_not_called()
    record.refresh_from_db()
    assert record.token_id == original_token
    assert record.validation_status == "verified"
    assert record.last_error_code == ""
    warehouse_credential_service.require_verified_warehouse(record)
