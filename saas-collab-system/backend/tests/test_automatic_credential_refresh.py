from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.integrations import automatic_refresh as service
from apps.integrations.models import AutomaticRefreshAttempt, IntegrationAuditLog, SyncJob, SyncRun
from apps.integrations.production_settings import SAFE_DEFAULTS, validate_runtime_config
from tests.test_jifeng_warehouse_credentials import binding
from tests.test_lazada_store_authorization import lazada_context
from tests.test_marketplace_callback_acceptance import marketplace_callback, MANUAL

pytestmark = pytest.mark.django_db


def due_warehouse(monkeypatch):
    actor, record = binding()
    record.oauth_user_id = "456"
    record.oauth_expires_at = timezone.now() + timedelta(minutes=10)
    record.validation_status = "verified"
    record.last_verified_at = timezone.now()
    record.save()
    monkeypatch.setattr(service, "get_runtime_platform_config", lambda platform: {"auto_refresh_enabled": True})
    return actor, record


def test_only_supported_platforms_accept_strict_boolean_switch():
    result = validate_runtime_config({"platforms": {"lazada": {"auto_refresh_enabled": True}, "shopee": {"auto_refresh_enabled": True}, "jifeng_wms": {"auto_refresh_enabled": False}}})
    assert result["platforms"]["lazada"]["auto_refresh_enabled"] is True
    assert result["platforms"]["shopee"]["auto_refresh_enabled"] is True
    for platform, value in [("shopee", "true"), ("lazada", "true"), ("tiktok", True)]:
        with pytest.raises(ValidationError):
            validate_runtime_config({"platforms": {platform: {"auto_refresh_enabled": value}}})
    assert SAFE_DEFAULTS["platforms"]["lazada"]["auto_refresh_enabled"] is False
    assert SAFE_DEFAULTS["platforms"]["shopee"]["auto_refresh_enabled"] is False


@pytest.mark.parametrize("case", ["disabled", "revoked", "not_due", "no_expiry", "inactive_actor", "wrong_tenant", "mock", "missing_identity"])
def test_ineligible_authorization_never_refreshes(monkeypatch, case):
    actor, record = due_warehouse(monkeypatch)
    if case == "disabled":
        monkeypatch.setattr(service, "get_runtime_platform_config", lambda platform: {})
    elif case == "revoked":
        record.status = "revoked"
    elif case == "not_due":
        record.oauth_expires_at = timezone.now() + timedelta(hours=1)
    elif case == "no_expiry":
        record.oauth_expires_at = None
    elif case == "inactive_actor":
        actor.is_active = False
    elif case == "wrong_tenant":
        actor.tenant_id += 1
    elif case == "mock":
        record.integration_config.environment = "mock"
    elif case == "missing_identity":
        record.oauth_user_id = ""
    record.updated_by = actor
    assert not service.automatic_refresh_allowed(record)


def test_failure_is_durable_deduplicated_and_redacted(monkeypatch):
    from apps.integrations import warehouse_credential_service
    _, record = due_warehouse(monkeypatch)
    refresh = Mock(side_effect=RuntimeError("FAKE_SECRET_DO_NOT_LOG"))
    monkeypatch.setattr(warehouse_credential_service, "refresh_warehouse_authorization", refresh)
    assert service.refresh_due_authorizations() == {"attempted": 1, "success": 0, "failed": 1}
    assert service.refresh_due_authorizations()["attempted"] == 0
    assert refresh.call_count == 1
    attempt = AutomaticRefreshAttempt.objects.get()
    assert attempt.status == "failed" and attempt.finished_at
    audit = IntegrationAuditLog.objects.get(action="automatic_refresh")
    assert audit.tenant_id == record.tenant_id
    assert "FAKE_SECRET" not in str(audit.masked_detail)
    assert record.token_id not in str(audit.masked_detail)


def test_new_reference_can_refresh_after_failed_attempt(monkeypatch):
    from apps.integrations import warehouse_credential_service
    _, record = due_warehouse(monkeypatch)
    refresh = Mock(side_effect=RuntimeError("synthetic failure"))
    monkeypatch.setattr(warehouse_credential_service, "refresh_warehouse_authorization", refresh)
    service.refresh_due_authorizations()
    record.token_id = "synthetic-manually-renewed-reference"
    record.save()
    refresh.side_effect = None
    assert service.refresh_due_authorizations()["success"] == 1
    assert AutomaticRefreshAttempt.objects.count() == 2


def test_automatic_warehouse_refresh_preserves_verification_and_schedule(monkeypatch):
    from apps.integrations.readonly_clients import JifengWmsReadonlyClient
    from apps.integrations.warehouse_credential_service import refresh_warehouse_authorization
    actor, record = due_warehouse(monkeypatch)
    config = record.integration_config
    config.platform_config = {"api_host": "https://example.test/api", "client_id": "TEST_CLIENT"}
    config.save(update_fields=["platform_config"])
    next_run = timezone.now() + timedelta(hours=1)
    job = SyncJob.objects.create(tenant=record.tenant, integration_config=config,
        warehouse_authorization=record, resource_type="inventory_snapshot", next_run_at=next_run)
    custody, http = Mock(), Mock()
    custody.retrieve_secret.return_value = "FAKE_SECRET"
    custody.retrieve_refresh_token.return_value = "FAKE_REFRESH"
    custody.store_secrets.return_value = {"token_id": "synthetic-renewed"}
    http.request.return_value.status_code = 200
    http.request.return_value.json.return_value = {"code": 0, "data": {
        "accessToken": "FAKE_ACCESS", "refreshToken": "FAKE_NEW", "userId": 456}}
    monkeypatch.setattr(JifengWmsReadonlyClient, "preflight", lambda self: None)
    refreshed = refresh_warehouse_authorization(actor=actor, authorization=record,
        http=http, custody=custody, automatic=True, expected_token_id=record.token_id)
    assert refreshed.validation_status == "verified"
    assert refreshed.last_verified_at == record.last_verified_at
    assert refreshed.token_id == "synthetic-renewed"
    job.refresh_from_db()
    assert job.is_enabled and job.next_run_at == next_run and job.status == "idle"
    assert http.request.call_count == 1


def test_changed_reference_blocks_before_provider_call(monkeypatch):
    from rest_framework.exceptions import ValidationError as APIValidationError
    from apps.integrations.warehouse_credential_service import refresh_warehouse_authorization
    actor, record = due_warehouse(monkeypatch)
    http = Mock()
    with pytest.raises(APIValidationError, match="CONDITIONS_CHANGED"):
        refresh_warehouse_authorization(actor=actor, authorization=record,
            automatic=True, expected_token_id="synthetic-old-reference", http=http)
    http.request.assert_not_called()


def test_running_sync_delays_refresh(monkeypatch):
    _, record = due_warehouse(monkeypatch)
    job = SyncJob.objects.create(tenant=record.tenant, integration_config=record.integration_config,
        warehouse_authorization=record, resource_type="inventory_snapshot")
    SyncRun.objects.create(tenant=record.tenant, sync_job=job, status="running")
    assert not service.automatic_refresh_allowed(record)


def test_permission_and_scope_are_rechecked(monkeypatch):
    _, record = due_warehouse(monkeypatch)
    monkeypatch.setattr(service, "user_has_integration_permission", lambda *args: False)
    assert not service.automatic_refresh_allowed(record)
    monkeypatch.setattr(service, "user_has_integration_permission", lambda *args: True)
    monkeypatch.setattr(service, "integration_values_allowed", lambda *args, **kwargs: False)
    assert not service.automatic_refresh_allowed(record)


def test_only_shopee_rotates_and_duplicate_scan_does_not_repeat(marketplace_callback, monkeypatch):
    from apps.integrations import marketplace_oauth_service
    from apps.integrations.models import MarketplaceStoreAuthorization, authorization_service_write
    client, store, config, _, payload = marketplace_callback
    assert client.post(MANUAL, payload, format="json").status_code == 200
    record = MarketplaceStoreAuthorization.objects.get(store=store)
    record.expires_at = timezone.now() + timedelta(minutes=5)
    with authorization_service_write():
        record.save()
    monkeypatch.setattr(service, "get_runtime_platform_config", lambda platform: {"auto_refresh_enabled": True})
    provider = Mock()
    provider.refresh_authorization.return_value = {
        "credential_id": "cred_fake_renewed", "token_id": "tok_fake_renewed",
        "reference_kind": "custody", "reference_version": record.credential_reference_version + 1,
        "expires_at": timezone.now() + timedelta(hours=4),
        "previous_reference_revoker": Mock(return_value={"status": "revoked"}),
        "new_reference_revoker": Mock(return_value={"status": "revoked"}),
    }
    monkeypatch.setattr(marketplace_oauth_service, "resolve_oauth_provider", lambda *args: provider)
    outcome = service.refresh_due_authorizations()
    record.refresh_from_db()
    if config.platform == "shopee":
        assert outcome["success"] == 1
        assert record.token_id == "tok_fake_renewed"
        assert record.expires_at > timezone.now() + timedelta(hours=3)
        assert record.status == "active"
        assert service.refresh_due_authorizations()["attempted"] == 0
        assert provider.refresh_authorization.call_count == 1
    else:
        assert outcome["attempted"] == 0
        provider.refresh_authorization.assert_not_called()
