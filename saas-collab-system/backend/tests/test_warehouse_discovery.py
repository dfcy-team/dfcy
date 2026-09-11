from datetime import timedelta
from unittest.mock import Mock
import hashlib
import hmac

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.common.exceptions import StateConflict
from apps.integrations.models import IntegrationAuditLog, PlatformIntegrationConfig, SyncJob, WarehouseAuthorization
from apps.integrations.readonly_clients import JifengWmsReadonlyClient
from apps.integrations.warehouse_discovery_service import discover_warehouse
from tests.test_jifeng_warehouse_credentials import binding

pytestmark = pytest.mark.django_db


def ready(monkeypatch):
    actor, record = binding()
    record.email = "fake@example.test"
    record.token_id = "FAKE_CUSTODY_REFERENCE"
    record.oauth_user_id = "FAKE_USER"
    record.oauth_expires_at = timezone.now() + timedelta(hours=1)
    record.bootstrap_consumed_at = timezone.now()
    record.external_warehouse_code = ""
    record.validation_status = "pending"
    record.save()
    config = record.integration_config
    config.platform_config = {"api_host": "https://example.test/api", "client_id": "FAKE_CLIENT"}
    config.save(update_fields=["platform_config"])
    monkeypatch.setattr(JifengWmsReadonlyClient, "preflight", lambda self: None)
    custody = Mock()
    custody.retrieve_secret.return_value = "FAKE_SECRET"
    custody.retrieve_access_token.return_value = "FAKE_ACCESS"
    http = Mock()
    http.request.return_value.status_code = 200
    return actor, record, http, custody


def row(code="REMOTE-1", **extra):
    return {"code": code, "name": "Test warehouse", "country": "MY", "isAuth": True, **extra}


def test_signed_list_auto_links_single_warehouse_without_bootstrap_or_inventory(monkeypatch):
    actor, record, http, custody = ready(monkeypatch)
    http.request.return_value.json.return_value = {"code": 0, "data": [row(email="PRIVATE", phone="PRIVATE")]}
    previous_token, consumed, authorized = record.token_id, record.bootstrap_consumed_at, record.authorized_at
    updated, discovery = discover_warehouse(actor=actor, authorization=record, http=http, custody=custody)
    assert updated.pk == record.pk
    assert updated.external_warehouse_code == "REMOTE-1"
    assert updated.token_id == previous_token
    assert updated.bootstrap_consumed_at == consumed and updated.authorized_at == authorized
    assert updated.validation_status == "pending" and updated.last_verified_at is None
    assert discovery["status"] == "linked" and "PRIVATE" not in str(discovery)
    http.request.assert_called_once()
    method, url = http.request.call_args.args
    assert (method, url) == ("POST", "https://example.test/api/warehouse/getList")
    kwargs = http.request.call_args.kwargs
    assert kwargs["json_body"] == {}
    headers = kwargs["headers"]
    values = {key: headers[key] for key in ("accessToken", "clientId", "nonce", "timestamp", "userId")}
    values.update(method="post", url="/api/warehouse/getList")
    expected = hmac.new(b"FAKE_SECRET", "&".join(f"{key}={values[key]}" for key in sorted(values)).encode(), hashlib.sha256).hexdigest()
    assert headers["sign"] == expected
    custody.retrieve_secret.assert_called_once_with(record.integration_config.credential_id)
    custody.retrieve_access_token.assert_called_once_with(previous_token)
    custody.store_secrets.assert_not_called()
    assert IntegrationAuditLog.objects.filter(action="warehouse_identity_resolve", actor=actor).count() == 1
    discover_warehouse(actor=actor, authorization=updated, http=http, custody=custody)
    assert IntegrationAuditLog.objects.filter(action="warehouse_identity_resolve").count() == 1


@pytest.mark.parametrize("rows,state", [
    ([row(), row("REMOTE-2")], "selection_required"),
    ([], "unavailable"), ([row(isAuth=False)], "unavailable"),
    ([row(country="TH")], "unavailable"),
])
def test_no_guessing_for_multiple_empty_denied_or_wrong_country(monkeypatch, rows, state):
    actor, record, http, custody = ready(monkeypatch)
    http.request.return_value.json.return_value = {"code": 0, "data": rows}
    updated, result = discover_warehouse(actor=actor, authorization=record, http=http, custody=custody)
    assert result["status"] == state
    assert updated.external_warehouse_code == "" and updated.token_id == record.token_id


@pytest.mark.parametrize("payload", [{"code": 10050}, {"code": 0, "data": {}},
    {"code": 0, "data": [row(), row()]}, {"code": 0, "data": [{"code": "INCOMPLETE"}]}])
def test_invalid_or_denied_response_preserves_authorization(monkeypatch, payload):
    actor, record, http, custody = ready(monkeypatch)
    before = WarehouseAuthorization.objects.filter(pk=record.pk).values().get()
    http.request.return_value.json.return_value = payload
    with pytest.raises(ValidationError):
        discover_warehouse(actor=actor, authorization=record, http=http, custody=custody)
    assert WarehouseAuthorization.objects.filter(pk=record.pk).values().get() == before


def test_selection_rechecks_provider_membership_and_disables_jobs_without_reauthorization(monkeypatch):
    actor, record, http, custody = ready(monkeypatch)
    http.request.return_value.json.return_value = {"code": 0, "data": [row(), row("REMOTE-2")]}
    job = SyncJob.objects.create(tenant=actor.tenant, integration_config=record.integration_config,
        warehouse_authorization=record, resource_type="inventory_snapshot", is_enabled=True)
    with pytest.raises(ValidationError):
        discover_warehouse(actor=actor, authorization=record, external_warehouse_code="FORGED", http=http, custody=custody)
    updated, result = discover_warehouse(actor=actor, authorization=record, external_warehouse_code="REMOTE-2", http=http, custody=custody)
    assert result["status"] == "linked" and updated.external_warehouse_code == "REMOTE-2"
    assert updated.token_id == record.token_id
    job.refresh_from_db()
    assert not job.is_enabled and job.status == "disabled"


@pytest.mark.parametrize("change", ["config", "token", "revoke"])
def test_concurrent_change_cannot_associate_stale_warehouse_result(monkeypatch, change):
    actor, record, http, custody = ready(monkeypatch)
    def respond(*args, **kwargs):
        if change == "config":
            PlatformIntegrationConfig.objects.filter(pk=record.integration_config_id).update(config_version=99)
        else:
            values = {"token_id": "NEW_REFERENCE"} if change == "token" else {"status": "revoked"}
            WarehouseAuthorization.objects.filter(pk=record.pk).update(**values)
        return Mock(json=lambda: {"code": 0, "data": [row()]}, status_code=200)
    http.request.side_effect = respond
    with pytest.raises(StateConflict):
        discover_warehouse(actor=actor, authorization=record, http=http, custody=custody)
    record.refresh_from_db()
    assert record.external_warehouse_code == ""


def test_existing_mapping_is_not_silently_replaced(monkeypatch):
    actor, record, http, custody = ready(monkeypatch)
    record.external_warehouse_code = "EXISTING"
    record.save()
    http.request.return_value.json.return_value = {"code": 0, "data": [row()]}
    updated, result = discover_warehouse(actor=actor, authorization=record, http=http, custody=custody)
    assert updated.external_warehouse_code == "EXISTING"
    assert result["status"] == "selection_required"


def test_post_authorization_discovery_timeout_is_partial_not_oauth_failure(monkeypatch):
    from apps.integrations import warehouse_credential_views as views
    actor, record, _, _ = ready(monkeypatch)
    exchange = Mock(return_value=record)
    monkeypatch.setattr(views, "authorize_warehouse", exchange)
    monkeypatch.setattr(views, "discover_warehouse", Mock(side_effect=TimeoutError("FAKE_SECRET")))
    client = APIClient()
    client.force_authenticate(actor)
    response = client.post(f"/api/internal/integrations/warehouse-authorizations/{record.pk}/authorize/", {"confirmed": True}, format="json")
    assert response.status_code == 200
    assert response.data["data"]["warehouse_discovery"]["status"] == "failed"
    assert response.data["data"]["connected"] is False and "FAKE_SECRET" not in str(response.data)
    exchange.assert_called_once()
    record.refresh_from_db()
    assert record.token_id and record.status == "active"


def test_discovery_endpoint_denies_cross_tenant_and_missing_permission_before_network(monkeypatch):
    from apps.accounts.models import CustomUser
    from apps.tenants.models import Tenant
    from apps.integrations import warehouse_credential_views as views
    actor, record, _, _ = ready(monkeypatch)
    fetch = Mock()
    monkeypatch.setattr(views, "discover_warehouse", fetch)
    client = APIClient()
    url = f"/api/internal/integrations/warehouse-authorizations/{record.pk}/warehouses/"
    stranger = CustomUser.objects.create(username="stranger-discovery", tenant=Tenant.objects.create(code="other-discovery", name="Other"), is_superuser=True)
    client.force_authenticate(stranger)
    assert client.post(url, {}, format="json").status_code in (403, 404)
    ordinary = CustomUser.objects.create(username="no-discovery", tenant=actor.tenant)
    client.force_authenticate(ordinary)
    assert client.post(url, {}, format="json").status_code == 403
    fetch.assert_not_called()


def test_full_authorization_endpoint_exchanges_once_then_fetches_and_links(monkeypatch):
    from apps.integrations import readonly_clients, warehouse_credential_service, warehouse_discovery_service
    actor, record, http, custody = ready(monkeypatch)
    record.bootstrap_credential_id = "FAKE_BOOTSTRAP_REFERENCE"
    record.bootstrap_consumed_at = None
    record.save()
    config = record.integration_config
    config.platform_config["domain"] = "test"
    config.save(update_fields=["platform_config"])
    custody.store_secrets.return_value = {"token_id": "FAKE_NEW_REFERENCE"}
    payloads = [{"code": 0, "data": "FAKE_KEY"}, {"code": 0, "data": {
        "accessToken": "FAKE_NEW_ACCESS", "refreshToken": "FAKE_REFRESH", "userId": "FAKE_USER",
    }}, {"code": 0, "data": [row()]}]
    http.request.side_effect = [Mock(status_code=200, json=lambda payload=payload: payload) for payload in payloads]
    monkeypatch.setattr(warehouse_credential_service, "get_custody_backend", lambda: custody)
    monkeypatch.setattr(readonly_clients, "get_custody_backend", lambda: custody)
    monkeypatch.setattr(warehouse_credential_service, "PlatformHttpClient", lambda **kwargs: http)
    monkeypatch.setattr(warehouse_discovery_service, "PlatformHttpClient", lambda **kwargs: http)
    client = APIClient()
    client.force_authenticate(actor)
    response = client.post(f"/api/internal/integrations/warehouse-authorizations/{record.pk}/authorize/", {"confirmed": True}, format="json")
    assert response.status_code == 200 and response.data["data"]["warehouse_discovery"]["status"] == "linked"
    assert http.request.call_count == 3
    assert http.request.call_args_list[-1].args == ("POST", "https://example.test/api/warehouse/getList")
    assert "FAKE_" not in str(response.data)
    record.refresh_from_db()
    assert record.external_warehouse_code == "REMOTE-1" and record.token_id == "FAKE_NEW_REFERENCE"
    assert record.bootstrap_consumed_at and record.validation_status == "pending"


def test_duplicate_upstream_binding_rolls_back_without_clearing_oauth(monkeypatch):
    from apps.masterdata.models import WarehouseMaster
    from apps.integrations.warehouse_authorization_service import bind_warehouse_authorization
    actor, record, http, custody = ready(monkeypatch)
    other = WarehouseMaster.objects.create(tenant=actor.tenant, code="OTHER", name="Other", country_code="MY",
        warehouse_type="third_party", status="active", service_platform=record.warehouse.service_platform)
    bind_warehouse_authorization(actor=actor, warehouse=other, integration_config=record.integration_config,
        external_warehouse_code="REMOTE-1")
    http.request.return_value.json.return_value = {"code": 0, "data": [row()]}
    before = WarehouseAuthorization.objects.filter(pk=record.pk).values().get()
    with pytest.raises(StateConflict):
        discover_warehouse(actor=actor, authorization=record, http=http, custody=custody)
    assert WarehouseAuthorization.objects.filter(pk=record.pk).values().get() == before


def test_expired_oauth_does_not_read_or_exchange_bootstrap(monkeypatch):
    actor, record, http, custody = ready(monkeypatch)
    record.oauth_expires_at = timezone.now() - timedelta(seconds=1)
    record.save()
    with pytest.raises(ValidationError, match="已过期"):
        discover_warehouse(actor=actor, authorization=record, http=http, custody=custody)
    http.request.assert_not_called()
    custody.retrieve_secret.assert_not_called()


def test_running_inventory_job_prevents_identity_change(monkeypatch):
    actor, record, http, custody = ready(monkeypatch)
    SyncJob.objects.create(tenant=actor.tenant, integration_config=record.integration_config,
        warehouse_authorization=record, resource_type="inventory_snapshot", is_enabled=True, status="running")
    http.request.return_value.json.return_value = {"code": 0, "data": [row()]}
    with pytest.raises(StateConflict, match="运行中"):
        discover_warehouse(actor=actor, authorization=record, http=http, custody=custody)
    record.refresh_from_db()
    assert record.external_warehouse_code == ""
