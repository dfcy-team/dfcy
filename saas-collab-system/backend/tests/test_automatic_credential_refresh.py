from datetime import timedelta
from unittest.mock import Mock, call

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.integrations import automatic_refresh as service
from apps.integrations.models import (
    AutomaticRefreshAttempt,
    IntegrationAuditLog,
    SyncAlertIncident,
    SyncJob,
    SyncRun,
)
from apps.integrations.oauth_errors import OAUTH_AUTH_REJECTED, OAUTH_PROVIDER_UNAVAILABLE, OAuthFlowError
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
    result = validate_runtime_config({"platforms": {"lazada": {"auto_refresh_enabled": True}, "shopee": {"auto_refresh_enabled": True}, "tiktok": {"auto_refresh_enabled": True}, "jifeng_wms": {"auto_refresh_enabled": False}}})
    assert result["platforms"]["lazada"]["auto_refresh_enabled"] is True
    assert result["platforms"]["shopee"]["auto_refresh_enabled"] is True
    assert result["platforms"]["tiktok"]["auto_refresh_enabled"] is True
    for platform, value in [("shopee", "true"), ("lazada", "true"), ("tiktok", "true")]:
        with pytest.raises(ValidationError):
            validate_runtime_config({"platforms": {platform: {"auto_refresh_enabled": value}}})
    assert SAFE_DEFAULTS["platforms"]["lazada"]["auto_refresh_enabled"] is False
    assert SAFE_DEFAULTS["platforms"]["shopee"]["auto_refresh_enabled"] is False
    assert SAFE_DEFAULTS["platforms"]["tiktok"]["auto_refresh_enabled"] is False


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
    refresh.side_effect = lambda **kwargs: kwargs["authorization"]
    monkeypatch.setattr(service, "validate_refreshed_authorization", Mock(return_value={"records": []}))
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
    assert refreshed.validation_status == "pending"
    assert refreshed.last_verified_at is None
    assert refreshed.last_error_code == service.AUTO_REFRESH_VALIDATION_PENDING
    assert refreshed.token_id == "synthetic-renewed"
    job.refresh_from_db()
    assert job.is_enabled and job.next_run_at == next_run and job.status == "idle"
    assert http.request.call_count == 1


def _automatic_warehouse_job(monkeypatch):
    actor, record = due_warehouse(monkeypatch)
    job = SyncJob.objects.create(
        tenant=record.tenant,
        integration_config=record.integration_config,
        warehouse_authorization=record,
        resource_type="inventory_snapshot",
        status=SyncJob.Status.IDLE,
        is_enabled=True,
        next_run_at=timezone.now() + timedelta(hours=1),
    )
    refresh = Mock()

    def rotate(*, authorization, **kwargs):
        authorization.token_id = "synthetic-new-token-reference"
        authorization.oauth_expires_at = timezone.now() + timedelta(hours=24)
        authorization.save(update_fields=["token_id", "oauth_expires_at", "updated_at"])
        return authorization

    refresh.side_effect = rotate
    monkeypatch.setattr(
        "apps.integrations.warehouse_credential_service.refresh_warehouse_authorization",
        refresh,
    )
    monkeypatch.setattr(service.time, "sleep", Mock())
    return actor, record, job, refresh


def test_refresh_success_but_readonly_401_fails_and_pauses_jobs(monkeypatch):
    _, record, job, refresh = _automatic_warehouse_job(monkeypatch)
    rejected = OAuthFlowError(OAUTH_AUTH_REJECTED, "FAKE_TOKEN_MUST_NOT_BE_LOGGED")
    validate = Mock(side_effect=rejected)
    monkeypatch.setattr(service, "validate_refreshed_authorization", validate)

    assert service.refresh_due_authorizations() == {"attempted": 1, "success": 0, "failed": 1}
    assert refresh.call_count == 1
    assert validate.call_count == 1
    record.refresh_from_db()
    job.refresh_from_db()
    assert record.validation_status == "failed"
    assert record.last_error_code == service.AUTO_REFRESH_VALIDATION_FAILED
    assert not job.is_enabled and job.status == SyncJob.Status.DISABLED and job.next_run_at is None
    attempt = AutomaticRefreshAttempt.objects.get()
    assert attempt.status == "failed"
    audit = IntegrationAuditLog.objects.get(action="automatic_refresh")
    assert audit.result == "failed"
    assert audit.masked_detail["error_code"] == service.AUTO_REFRESH_VALIDATION_FAILED
    assert "FAKE_TOKEN" not in str(audit.masked_detail)
    incident = SyncAlertIncident.objects.get(sync_job=job)
    assert incident.last_error_code == service.AUTO_REFRESH_VALIDATION_FAILED
    assert "新令牌只读校验失败" in incident.masked_message


def test_refresh_and_readonly_validation_success_preserve_enabled_job(monkeypatch):
    _, record, job, refresh = _automatic_warehouse_job(monkeypatch)
    validate = Mock(return_value={"records": []})
    monkeypatch.setattr(service, "validate_refreshed_authorization", validate)

    assert service.refresh_due_authorizations() == {"attempted": 1, "success": 1, "failed": 0}
    assert refresh.call_count == 1
    assert validate.call_count == 1
    record.refresh_from_db()
    job.refresh_from_db()
    assert record.validation_status == "verified"
    assert record.last_verified_at is not None
    assert record.last_error_code == ""
    assert job.is_enabled and job.status == SyncJob.Status.IDLE and job.next_run_at is not None
    assert AutomaticRefreshAttempt.objects.get().status == "success"


def test_validation_timeout_retries_only_new_token_validation(monkeypatch):
    _, _, _, refresh = _automatic_warehouse_job(monkeypatch)
    timeout = OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, "synthetic timeout")
    timeout.category = "timeout_uncertain"
    validate = Mock(side_effect=[timeout, timeout, timeout, {"records": []}])
    monkeypatch.setattr(service, "validate_refreshed_authorization", validate)

    assert service.refresh_due_authorizations()["success"] == 1
    assert refresh.call_count == 1
    assert validate.call_count == 4
    assert service.time.sleep.call_args_list == [call(2), call(5), call(15)]


def test_validation_business_error_does_not_retry(monkeypatch):
    _, record, job, refresh = _automatic_warehouse_job(monkeypatch)
    validate = Mock(side_effect=ValidationError("invalid readonly response"))
    monkeypatch.setattr(service, "validate_refreshed_authorization", validate)

    assert service.refresh_due_authorizations()["failed"] == 1
    refresh.assert_called_once()
    validate.assert_called_once()
    service.time.sleep.assert_not_called()
    record.refresh_from_db()
    job.refresh_from_db()
    assert record.last_error_code == service.AUTO_REFRESH_VALIDATION_FAILED
    assert not job.is_enabled


def test_exhausted_network_validation_remains_pending_and_retries_without_rotation(monkeypatch):
    _, record, job, refresh = _automatic_warehouse_job(monkeypatch)
    validate = Mock(side_effect=TimeoutError("FAKE_SECRET_DO_NOT_LOG"))
    monkeypatch.setattr(service, "validate_refreshed_authorization", validate)
    assert service.refresh_due_authorizations()["failed"] == 1
    record.refresh_from_db()
    job.refresh_from_db()
    assert record.last_error_code == service.AUTO_REFRESH_VALIDATION_PENDING
    assert record.validation_status == "pending"
    assert not job.is_enabled
    assert AutomaticRefreshAttempt.objects.get().status == "token_saved"
    audit = IntegrationAuditLog.objects.get(action="automatic_refresh")
    assert audit.masked_detail["reauthorization_required"] is False
    assert "FAKE_SECRET" not in str(audit.masked_detail)
    validate.side_effect = None
    validate.return_value = {"records": []}
    assert service.refresh_due_authorizations()["success"] == 1
    assert refresh.call_count == 1
    job.refresh_from_db()
    assert not job.is_enabled


def test_manual_revalidation_uses_saved_token_and_does_not_enable_tasks(monkeypatch):
    actor, record, job, refresh = _automatic_warehouse_job(monkeypatch)
    monkeypatch.setattr(service, "validate_refreshed_authorization", Mock(side_effect=TimeoutError()))
    service.refresh_due_authorizations()
    record.refresh_from_db()
    saved_token = record.token_id
    validate = Mock(return_value={"records": []})
    monkeypatch.setattr(service, "validate_refreshed_authorization", validate)
    result = service.revalidate_saved_authorization(record, actor=actor)
    assert result.token_id == saved_token
    assert result.last_error_code == ""
    assert result.validation_status == "verified"
    assert refresh.call_count == 1
    validate.assert_called_once()
    job.refresh_from_db()
    assert not job.is_enabled


def test_failed_store_validation_can_recover_without_refreshing(marketplace_callback, monkeypatch):
    from apps.integrations.models import MarketplaceStoreAuthorization, authorization_service_write
    client, store, _, _, payload = marketplace_callback
    assert client.post(MANUAL, payload, format="json").status_code == 200
    record = MarketplaceStoreAuthorization.objects.get(store=store)
    token_id = record.token_id
    record.status = "error"
    record.last_error_code = service.AUTO_REFRESH_VALIDATION_FAILED
    with authorization_service_write():
        record.save()
    validate = Mock(return_value=[{"platform_store_id": record.platform_store_id}])
    monkeypatch.setattr(service, "validate_refreshed_authorization", validate)
    refresh = Mock()
    monkeypatch.setattr("apps.integrations.marketplace_oauth_service.refresh_marketplace_authorization", refresh)
    result = service.revalidate_saved_authorization(record, actor=record.updated_by)
    assert result.status == "active" and result.last_error_code == ""
    assert result.token_id == token_id
    assert validate.call_args.args[0].status == "active"
    refresh.assert_not_called()
    audit = IntegrationAuditLog.objects.get(action="revalidate_saved_token")
    assert audit.result == "success" and audit.masked_detail["token_refreshed"] is False


def test_store_refresh_endpoint_revalidates_failed_saved_token(marketplace_callback, monkeypatch):
    from apps.integrations.models import MarketplaceStoreAuthorization, authorization_service_write
    client, store, _, _, payload = marketplace_callback
    assert client.post(MANUAL, payload, format="json").status_code == 200
    record = MarketplaceStoreAuthorization.objects.get(store=store)
    record.status = "error"
    record.last_error_code = service.AUTO_REFRESH_VALIDATION_FAILED
    with authorization_service_write():
        record.save()
    validate = Mock(return_value=[])
    monkeypatch.setattr(service, "validate_refreshed_authorization", validate)
    refresh = Mock()
    monkeypatch.setattr("apps.integrations.views.refresh_marketplace_authorization", refresh)
    response = client.post(f"/api/internal/integrations/store-authorizations/{record.pk}/refresh/", {"confirmed": True}, format="json")
    assert response.status_code == 200
    assert response.data["data"]["last_error_code"] == ""
    validate.assert_called_once()
    refresh.assert_not_called()


def test_revoked_saved_reference_cannot_be_revalidated(monkeypatch):
    from rest_framework.exceptions import ValidationError as APIValidationError
    actor, record = due_warehouse(monkeypatch)
    record.status = "revoked"
    record.last_error_code = service.AUTO_REFRESH_VALIDATION_FAILED
    record.save()
    validate = Mock()
    monkeypatch.setattr(service, "validate_refreshed_authorization", validate)
    with pytest.raises(APIValidationError, match="没有待验证"):
        service.revalidate_saved_authorization(record, actor=actor)
    validate.assert_not_called()


@pytest.mark.parametrize("validation_failure", [False, True])
def test_expired_saved_token_is_refreshed_then_validated(monkeypatch, validation_failure):
    actor, record = due_warehouse(monkeypatch)
    record.oauth_expires_at = timezone.now() - timedelta(seconds=1)
    record.last_error_code = service.AUTO_REFRESH_VALIDATION_FAILED
    record.save()
    old_token_id = record.token_id
    job = SyncJob.objects.create(tenant=record.tenant, integration_config=record.integration_config,
        warehouse_authorization=record, resource_type="inventory_snapshot", is_enabled=False,
        status=SyncJob.Status.DISABLED)

    def renew(**kwargs):
        current = kwargs["authorization"]
        current.token_id = "synthetic-renewed-reference"
        current.oauth_expires_at = timezone.now() + timedelta(hours=24)
        current.save()
        return current

    refresh = Mock(side_effect=renew)
    monkeypatch.setattr("apps.integrations.warehouse_credential_service.refresh_warehouse_authorization", refresh)
    validate = Mock(side_effect=OAuthFlowError(OAUTH_AUTH_REJECTED, "synthetic rejected")
                    if validation_failure else None)
    monkeypatch.setattr(service, "validate_refreshed_authorization", validate)
    service.revalidate_saved_authorization(record, actor=actor)
    record.refresh_from_db()
    job.refresh_from_db()
    assert record.token_id != old_token_id
    assert record.token_id == "synthetic-renewed-reference"
    refresh.assert_called_once()
    validate.assert_called_once()
    assert validate.call_args.args[0].token_id == record.token_id
    assert not job.is_enabled
    audit = IntegrationAuditLog.objects.get(action="revalidate_saved_token")
    assert audit.masked_detail["token_refreshed"] is True
    assert audit.result == ("failed" if validation_failure else "success")


def _real_warehouse_refresh_context(monkeypatch, error_code, *, expired=True):
    from apps.integrations import readonly_clients, warehouse_credential_service
    from apps.integrations.models import authorization_service_write

    actor, record = due_warehouse(monkeypatch)
    config = record.integration_config
    config.platform_config = {"api_host": "https://example.test", "client_id": "TEST_CLIENT"}
    with authorization_service_write():
        config.save()
    record.oauth_expires_at = timezone.now() + timedelta(seconds=-1 if expired else 3600)
    record.last_error_code = error_code
    record.save()
    monkeypatch.setattr(readonly_clients, "is_module_enabled", lambda name: True)
    monkeypatch.setattr(readonly_clients, "require_live_mode", lambda reason: None)
    monkeypatch.setattr(readonly_clients, "get_runtime_setting", lambda *args, **kwargs: True)
    monkeypatch.setattr("apps.integrations.warehouse_readiness.warehouse_config_blockers", lambda config: [])
    custody = Mock()
    custody.retrieve_secret.return_value = "test-client-secret"
    custody.retrieve_refresh_token.return_value = "test-refresh-token"
    custody.store_secrets.return_value = {"token_id": "synthetic-renewed-reference"}
    http = Mock()
    http.request.return_value.status_code = 200
    http.request.return_value.json.return_value = {"code": "0", "data": {
        "accessToken": "test-access-token", "refreshToken": "test-new-refresh-token", "userId": record.oauth_user_id,
    }}
    monkeypatch.setattr(warehouse_credential_service, "get_custody_backend", lambda: custody)
    monkeypatch.setattr(warehouse_credential_service, "PlatformHttpClient", lambda **kwargs: http)
    return actor, record, http, custody


@pytest.mark.parametrize("mode", ["manual_pending", "manual_failed", "scheduled_pending"])
@pytest.mark.parametrize("validation_failure", [False, True])
def test_expired_warehouse_recovery_uses_real_refresh_service(monkeypatch, mode, validation_failure):
    error_code = (service.AUTO_REFRESH_VALIDATION_FAILED if mode == "manual_failed"
                  else service.AUTO_REFRESH_VALIDATION_PENDING)
    actor, record, http, custody = _real_warehouse_refresh_context(monkeypatch, error_code)
    old_token_id = record.token_id
    job = SyncJob.objects.create(tenant=record.tenant, integration_config=record.integration_config,
        warehouse_authorization=record, resource_type="inventory_snapshot", is_enabled=False,
        status=SyncJob.Status.DISABLED)
    validate = Mock(side_effect=OAuthFlowError(OAUTH_AUTH_REJECTED, "synthetic rejected")
                    if validation_failure else None)
    monkeypatch.setattr(service, "validate_refreshed_authorization", validate)
    if mode == "scheduled_pending":
        key = service.sha256(f"jifeng_wms:{record.tenant_id}:{record.pk}:{record.token_id}".encode()).hexdigest()
        AutomaticRefreshAttempt.objects.create(request_key=key, tenant=record.tenant, status="token_saved")
        counts = service.refresh_due_authorizations()
        assert counts["attempted"] == 1
        assert counts["failed" if validation_failure else "success"] == 1
    else:
        service.revalidate_saved_authorization(record, actor=actor)
    record.refresh_from_db()
    job.refresh_from_db()
    http.request.assert_called_once()
    custody.retrieve_refresh_token.assert_called_once_with(old_token_id)
    assert record.token_id == "synthetic-renewed-reference"
    validate.assert_called_once()
    assert validate.call_args.args[0].token_id == record.token_id
    assert not job.is_enabled and job.status == SyncJob.Status.DISABLED
    assert record.last_error_code == (service.AUTO_REFRESH_VALIDATION_FAILED if validation_failure else "")


@pytest.mark.parametrize("error_code", [service.AUTO_REFRESH_VALIDATION_PENDING, service.AUTO_REFRESH_VALIDATION_FAILED])
def test_warehouse_recovery_keeps_ordinary_read_guard(monkeypatch, error_code):
    from apps.integrations.readonly_clients import JifengWmsReadonlyClient
    from rest_framework.exceptions import ValidationError as APIValidationError

    _, record, http, custody = _real_warehouse_refresh_context(monkeypatch, error_code)
    with pytest.raises(APIValidationError, match="尚未通过只读验证"):
        JifengWmsReadonlyClient(record.integration_config, record, http_client=http, custody=custody).preflight()
    http.request.assert_not_called()


def test_unexpired_warehouse_recovery_never_rotates(monkeypatch):
    actor, record, http, custody = _real_warehouse_refresh_context(
        monkeypatch, service.AUTO_REFRESH_VALIDATION_PENDING, expired=False)
    old_token_id = record.token_id
    monkeypatch.setattr(service, "validate_refreshed_authorization", Mock())
    service.revalidate_saved_authorization(record, actor=actor)
    record.refresh_from_db()
    assert record.token_id == old_token_id
    http.request.assert_not_called()
    custody.retrieve_refresh_token.assert_not_called()


def test_expired_warehouse_recovery_preserves_network_approval_gate(monkeypatch):
    from rest_framework.exceptions import ValidationError as APIValidationError

    actor, record, http, custody = _real_warehouse_refresh_context(monkeypatch, service.AUTO_REFRESH_VALIDATION_FAILED)
    old_token_id = record.token_id
    monkeypatch.setattr("apps.integrations.warehouse_readiness.warehouse_config_blockers",
                        lambda config: ["network_not_approved"])
    with pytest.raises(APIValidationError, match="网络访问未审批"):
        service.revalidate_saved_authorization(record, actor=actor)
    record.refresh_from_db()
    assert record.token_id == old_token_id and record.last_error_code == service.AUTO_REFRESH_VALIDATION_FAILED
    http.request.assert_not_called()
    custody.retrieve_refresh_token.assert_not_called()


def test_validation_audit_records_only_closed_schema_diagnostics(monkeypatch):
    actor, record = due_warehouse(monkeypatch)
    record.last_error_code = service.AUTO_REFRESH_VALIDATION_FAILED
    record.save()
    exc = OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, "synthetic-sensitive-payload")
    exc.stage = "verify_store"
    exc.http_status = 400
    exc.identity_evidence = "shop_id_missing"
    exc.platform_error_code = "synthetic-sensitive-payload"
    monkeypatch.setattr(service, "validate_refreshed_authorization", Mock(side_effect=exc))
    service.revalidate_saved_authorization(record, actor=actor)
    detail = IntegrationAuditLog.objects.get(action="revalidate_saved_token").masked_detail
    assert detail["stage"] == "verify_store" and detail["http_status"] == 400
    assert detail["identity_evidence"] == "shop_id_missing"
    assert "synthetic-sensitive-payload" not in str(detail)


def test_expired_store_recovery_refreshes_once_before_read(marketplace_callback, monkeypatch):
    from apps.integrations import marketplace_oauth_service
    from apps.integrations.models import MarketplaceStoreAuthorization, authorization_service_write
    client, store, _, _, payload = marketplace_callback
    assert client.post(MANUAL, payload, format="json").status_code == 200
    record = MarketplaceStoreAuthorization.objects.get(store=store)
    record.expires_at = timezone.now() - timedelta(seconds=1)
    record.status = "error"
    record.last_error_code = service.AUTO_REFRESH_VALIDATION_FAILED
    with authorization_service_write():
        record.save()
    provider = Mock()
    provider.refresh_authorization.return_value = {
        "credential_id": "cred_fake_recovered", "token_id": "tok_fake_recovered",
        "reference_kind": "custody", "reference_version": record.credential_reference_version + 1,
        "expires_at": timezone.now() + timedelta(hours=4),
        "previous_reference_revoker": Mock(return_value={"status": "revoked"}),
        "new_reference_revoker": Mock(return_value={"status": "revoked"}),
    }
    provider.fetch_authorized_stores.return_value = [{"platform_store_id": record.platform_store_id}]
    monkeypatch.setattr(marketplace_oauth_service, "resolve_oauth_provider", lambda *args: provider)
    response = client.post(f"/api/internal/integrations/store-authorizations/{record.pk}/refresh/",
                           {"confirmed": True}, format="json")
    assert response.status_code == 200
    record.refresh_from_db()
    assert record.token_id == "tok_fake_recovered" and record.status == "active"
    provider.refresh_authorization.assert_called_once()
    provider.fetch_authorized_stores.assert_called_once()
    audit = IntegrationAuditLog.objects.get(action="revalidate_saved_token")
    assert audit.result == "success" and audit.masked_detail["token_refreshed"] is True


def test_stale_recovery_reference_does_not_refresh_or_validate(monkeypatch):
    from rest_framework.exceptions import ValidationError as APIValidationError
    actor, record = due_warehouse(monkeypatch)
    record.last_error_code = service.AUTO_REFRESH_VALIDATION_FAILED
    record.save()
    type(record).objects.filter(pk=record.pk).update(token_id="synthetic-changed-reference")
    validate = Mock()
    monkeypatch.setattr(service, "validate_refreshed_authorization", validate)
    with pytest.raises(APIValidationError, match="已变化"):
        service.revalidate_saved_authorization(record, actor=actor)
    validate.assert_not_called()


def test_pending_new_token_resumes_validation_without_refreshing_again(monkeypatch):
    _, record, _, refresh = _automatic_warehouse_job(monkeypatch)
    record.token_id = "synthetic-already-saved-token-reference"
    record.oauth_expires_at = timezone.now() + timedelta(hours=24)
    record.last_error_code = service.AUTO_REFRESH_VALIDATION_PENDING
    record.validation_status = "pending"
    record.save()
    key = service.sha256(
        f"jifeng_wms:{record.tenant_id}:{record.pk}:{record.token_id}".encode()
    ).hexdigest()
    AutomaticRefreshAttempt.objects.create(
        request_key=key,
        tenant=record.tenant,
        status="token_saved",
    )
    validate = Mock(return_value={"records": []})
    monkeypatch.setattr(service, "validate_refreshed_authorization", validate)

    assert service.refresh_due_authorizations()["success"] == 1
    refresh.assert_not_called()
    validate.assert_called_once()


def test_pending_validation_that_expires_renews_instead_of_repeating_old_read(monkeypatch):
    _, record, _, refresh = _automatic_warehouse_job(monkeypatch)
    record.oauth_expires_at = timezone.now() - timedelta(seconds=1)
    record.last_error_code = service.AUTO_REFRESH_VALIDATION_PENDING
    record.save()
    key = service.sha256(f"jifeng_wms:{record.tenant_id}:{record.pk}:{record.token_id}".encode()).hexdigest()
    AutomaticRefreshAttempt.objects.create(request_key=key, tenant=record.tenant, status="token_saved")
    validate = Mock(return_value={"records": []})
    monkeypatch.setattr(service, "validate_refreshed_authorization", validate)
    assert service.refresh_due_authorizations()["success"] == 1
    refresh.assert_called_once()
    validate.assert_called_once()
    assert validate.call_args.args[0].token_id == "synthetic-new-token-reference"
    assert service.refresh_due_authorizations()["attempted"] == 0


def test_jifeng_validation_uses_bound_inventory_with_page_size_one(monkeypatch):
    from apps.integrations.readonly_clients import JifengWmsReadonlyClient

    _, record = due_warehouse(monkeypatch)
    fetch = Mock(return_value={"records": []})
    monkeypatch.setattr("apps.integrations.readonly_clients.get_custody_backend", Mock())
    monkeypatch.setattr(JifengWmsReadonlyClient, "fetch_inventory", fetch)

    service.validate_refreshed_authorization(record)
    assert fetch.call_args.args == (None, {"page_size": 1})


def test_failed_validation_allows_manual_warehouse_reauthorization(monkeypatch):
    from apps.integrations.warehouse_credential_service import save_warehouse_credentials

    actor, record, _, _ = _automatic_warehouse_job(monkeypatch)
    monkeypatch.setattr(
        service,
        "validate_refreshed_authorization",
        Mock(side_effect=OAuthFlowError(OAUTH_AUTH_REJECTED, "authorization rejected")),
    )
    service.refresh_due_authorizations()
    record.refresh_from_db()

    custody = Mock()
    custody.store_secrets.return_value = {"credential_id": "synthetic-reauthorization-reference"}
    recovered = save_warehouse_credentials(
        actor=actor,
        authorization=record,
        email=record.email or "demo@example.test",
        token="test-new-bootstrap-token",
        custody=custody,
    )
    assert recovered.status == "active"
    assert recovered.validation_status == "pending"
    assert recovered.last_error_code == ""
    assert recovered.token_id == ""


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


def test_shopee_and_tiktok_rotate_and_duplicate_scan_does_not_repeat(marketplace_callback, monkeypatch):
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
    provider.fetch_authorized_stores.return_value = [{"platform_store_id": record.platform_store_id}]
    monkeypatch.setattr(marketplace_oauth_service, "resolve_oauth_provider", lambda *args: provider)
    outcome = service.refresh_due_authorizations()
    record.refresh_from_db()
    if config.platform in {"shopee", "tiktok"}:
        assert outcome["success"] == 1
        assert record.token_id == "tok_fake_renewed"
        assert record.expires_at > timezone.now() + timedelta(hours=3)
        assert record.status == "active"
        provider.fetch_authorized_stores.assert_called_once()
        assert service.refresh_due_authorizations()["attempted"] == 0
        assert provider.refresh_authorization.call_count == 1
    else:
        assert outcome["attempted"] == 0
        provider.refresh_authorization.assert_not_called()
