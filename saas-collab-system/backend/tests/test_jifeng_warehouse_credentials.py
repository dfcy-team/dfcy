from unittest.mock import Mock

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.integrations.models import WarehouseAuthorization
from apps.integrations.custody import CustodyError
from apps.integrations.custody_service import EncryptedFileCustodyBackend
from apps.integrations.oauth_errors import OAuthFlowError
from apps.integrations.platform_schema_service import integration_platform_key
from apps.integrations.serializers import WarehouseAuthorizationSerializer
from apps.integrations.warehouse_authorization_service import bind_warehouse_authorization
from apps.integrations.warehouse_credential_service import jifeng_api_url, save_warehouse_credentials
from tests.test_warehouse_api_binding_closure import _fixture

pytestmark = pytest.mark.django_db


def binding():
    actor, warehouse, config, _ = _fixture()
    record, _, _ = bind_warehouse_authorization(actor=actor, warehouse=warehouse, integration_config=config)
    return actor, record


def test_legacy_binding_is_incomplete_without_changing_shared_references():
    _, record = binding()
    assert record.validation_status == "incomplete"
    assert record.email == ""
    assert record.token_id == record.integration_config.token_id


def test_token_is_stored_as_secret_and_never_serialized():
    actor, record = binding()
    custody = Mock()
    custody.store_secrets.return_value = {"credential_id": "opaque-warehouse-1"}
    updated = save_warehouse_credentials(actor=actor, authorization=record, email="demo@example.test", token="test-bootstrap-token", custody=custody)
    assert custody.store_secrets.call_args.kwargs["secret"] == "test-bootstrap-token"
    assert "access_token" not in custody.store_secrets.call_args.kwargs
    metadata = custody.store_secrets.call_args.kwargs["metadata"]
    assert EncryptedFileCustodyBackend._metadata({"metadata": metadata}) == {
        "tenant_id": actor.tenant_id, "warehouse_binding_id": record.pk,
    }
    assert updated.bootstrap_credential_id == "opaque-warehouse-1"
    assert updated.validation_status == "pending"
    assert updated.token_id == ""
    payload = WarehouseAuthorizationSerializer(updated).data
    assert payload["token_configured"] is True
    assert "test-bootstrap-token" not in str(payload)
    assert "opaque-warehouse-1" not in str(payload)
    updated.integration_config.refresh_from_db()
    assert updated.integration_config.token_id == "synthetic-wms-token"


def test_blank_token_preserves_verified_authorization():
    actor, record = binding()
    record.email = "demo@example.test"
    record.bootstrap_credential_id = "opaque-existing"
    record.validation_status = "verified"
    record.last_verified_at = timezone.now()
    record.save()
    custody = Mock()
    updated = save_warehouse_credentials(actor=actor, authorization=record, email=record.email, token="", custody=custody)
    custody.store_secrets.assert_not_called()
    assert updated.bootstrap_credential_id == "opaque-existing"
    assert updated.validation_status == "verified"
    assert updated.last_verified_at == record.last_verified_at


def test_first_save_requires_token_and_custody_failure_preserves_record():
    actor, record = binding()
    with pytest.raises(ValidationError):
        save_warehouse_credentials(actor=actor, authorization=record, email="demo@example.test")
    custody = Mock()
    custody.store_secrets.side_effect = RuntimeError("custody unavailable")
    with pytest.raises(RuntimeError):
        save_warehouse_credentials(actor=actor, authorization=record, email="demo@example.test", token="test-token", custody=custody)
    record.refresh_from_db()
    assert record.email == ""
    assert record.validation_status == "incomplete"


@pytest.mark.parametrize("name", ["极风平台", "极风", "马来极风", "Jifeng WMS", "jifeng_wms"])
def test_platform_aliases_share_canonical_provider(name):
    assert integration_platform_key(platform_type="warehouse_third_party", code="CUSTOM", name=name) == "jifeng_wms"


def test_api_base_normalization():
    assert jifeng_api_url("https://example.test/api/", "/api/inventory/queryInventory") == "https://example.test/api/inventory/queryInventory"
    with pytest.raises(ValidationError):
        jifeng_api_url("https://example.test/api?token=FAKE", "/api/inventory/queryInventory")


def test_unverified_legacy_binding_cannot_create_live_job():
    from rest_framework.test import APIClient
    actor, record = binding()
    client = APIClient()
    client.force_authenticate(actor)
    response = client.post("/api/internal/integrations/sync-jobs/", {
        "integration_config_id": record.integration_config_id, "warehouse_authorization_id": record.pk,
        "resource_type": "inventory_snapshot", "schedule_type": "manual", "is_enabled": True,
    }, format="json")
    assert response.status_code == 400
    assert "Email" in str(response.data)


@pytest.mark.parametrize("failure", [
    CustodyError("storage failure"),
    OAuthFlowError("OAUTH_PROVIDER_ERROR", "Platform rejected the request. FAKE_SECRET"),
    OAuthFlowError("OAUTH_AUTH_REJECTED", "FAKE_SECRET"),
])
def test_warehouse_and_credentials_save_roll_back_together(monkeypatch, failure):
    from rest_framework.test import APIClient
    from apps.masterdata.models import WarehouseMaster
    from apps.integrations import warehouse_credential_service
    actor, warehouse, config, _ = _fixture()
    custody = Mock()
    custody.store_secrets.side_effect = failure
    monkeypatch.setattr(warehouse_credential_service, "get_custody_backend", lambda: custody)
    client = APIClient()
    client.force_authenticate(actor)
    response = client.post("/api/internal/master-data/warehouses/", {
        "code": "NEW-FAIL", "name": "Rollback warehouse", "country_code": "MY", "warehouse_type": "third_party",
        "status": "active", "service_platform_id": warehouse.service_platform_id,
        "api_integration_config_id": config.pk, "api_email": "demo@example.test", "api_token": "FAKE_TOKEN",
    }, format="json")
    assert response.status_code == 400
    custody.store_secrets.assert_called_once()
    assert "加密保存失败" in str(response.data)
    assert "Platform rejected" not in str(response.data)
    assert "FAKE_SECRET" not in str(response.data)
    assert not WarehouseMaster.objects.filter(code="NEW-FAIL").exists()
    assert not WarehouseAuthorization.objects.exists()


def test_warehouse_edit_custody_http_failure_preserves_warehouse_and_authorization(monkeypatch):
    from rest_framework.test import APIClient
    from apps.integrations import warehouse_credential_service
    actor, record = binding()
    record.email = "before@example.test"
    record.bootstrap_credential_id = "fake-existing-bootstrap"
    record.validation_status = "verified"
    record.last_verified_at = timezone.now()
    record.save()
    warehouse = record.warehouse
    before_name = warehouse.name
    before_authorization = WarehouseAuthorization.objects.filter(pk=record.pk).values().get()
    custody = Mock()
    custody.store_secrets.side_effect = OAuthFlowError("OAUTH_PROVIDER_ERROR", "FAKE_SECRET")
    monkeypatch.setattr(warehouse_credential_service, "get_custody_backend", lambda: custody)
    client = APIClient()
    client.force_authenticate(actor)
    result = client.patch(f"/api/internal/master-data/warehouses/{warehouse.pk}/", {
        "name": "Must roll back", "api_integration_config_id": record.integration_config_id,
        "api_email": "after@example.test", "api_token": "FAKE_NEW_TOKEN",
    }, format="json")
    assert result.status_code == 400
    assert "加密保存失败" in str(result.data)
    assert "FAKE_" not in str(result.data)
    warehouse.refresh_from_db()
    assert warehouse.name == before_name
    assert WarehouseAuthorization.objects.filter(pk=record.pk).values().get() == before_authorization


def test_one_use_token_is_not_retried_after_network_timeout(monkeypatch):
    from apps.integrations.readonly_clients import JifengWmsReadonlyClient
    from apps.integrations.warehouse_credential_service import authorize_warehouse
    actor, record = binding()
    record.email = "demo@example.test"
    record.bootstrap_credential_id = "opaque-bootstrap"
    record.save()
    record.integration_config.platform_config = {"api_host": "https://example.test", "domain": "test", "client_id": "TEST_CLIENT"}
    custody = Mock()
    custody.retrieve_secret.return_value = "FAKE_SECRET"
    http = Mock()
    http.request.side_effect = TimeoutError("FAKE_SECRET must never appear in response")
    monkeypatch.setattr(JifengWmsReadonlyClient, "preflight", lambda self: None)
    with pytest.raises(ValidationError) as error:
        authorize_warehouse(actor=actor, authorization=record, custody=custody, http=http)
    assert "FAKE_SECRET" not in str(error.value)
    record.refresh_from_db()
    assert record.bootstrap_consumed_at is not None
    assert record.validation_status == "failed"
    # Retain the test config without changing the actual DB fixture.
    record.integration_config.platform_config = {"api_host": "https://example.test", "domain": "test", "client_id": "TEST_CLIENT"}
    with pytest.raises(ValidationError):
        authorize_warehouse(actor=actor, authorization=record, custody=custody, http=http)
    assert http.request.call_count == 1


def test_read_client_uses_warehouse_oauth_identity_and_token(monkeypatch):
    from datetime import timedelta
    from apps.integrations.readonly_clients import JifengWmsReadonlyClient
    actor, record = binding()
    record.email = "demo@example.test"
    record.oauth_user_id = "456"
    record.oauth_expires_at = timezone.now() + timedelta(hours=1)
    record.token_id = "warehouse-token-only"
    record.external_warehouse_region = "MY"
    record.external_warehouse_code = "UPSTREAM-1"
    record.integration_config.platform_config = {"api_host": "https://example.test/api", "client_id": "TEST", "user_id": "WRONG_SHARED_USER"}
    custody = Mock()
    custody.retrieve_secret.return_value = "FAKE_SHARED_SECRET"
    custody.retrieve_access_token.return_value = "FAKE_WAREHOUSE_ACCESS"
    http = Mock()
    http.request.return_value.json.return_value = {"code": 0, "data": {"page": {"rows": [], "totalPage": 1}}}
    http.request.return_value.status_code = 200
    monkeypatch.setattr(JifengWmsReadonlyClient, "preflight", lambda self: None)
    client = JifengWmsReadonlyClient(record.integration_config, record, http_client=http, custody=custody)
    result = client.fetch_inventory(None, {"page_size": 1})
    assert result["records"] == []
    custody.retrieve_access_token.assert_called_once_with("warehouse-token-only")
    assert http.request.call_args.kwargs["headers"]["userId"] == "456"
    assert http.request.call_args.kwargs["json_body"]["warehouse"] == "UPSTREAM-1"
    assert "/api/api/" not in http.request.call_args.args[1]


def test_custody_update_is_tenant_scoped():
    from apps.accounts.models import CustomUser
    from apps.tenants.models import Tenant
    actor, record = binding()
    other = Tenant.objects.create(code="other-jifeng", name="Other")
    stranger = CustomUser.objects.create(username="stranger", tenant=other)
    custody = Mock()
    with pytest.raises(WarehouseAuthorization.DoesNotExist):
        save_warehouse_credentials(actor=stranger, authorization=record, email="demo@example.test", token="test-token", custody=custody)
    custody.store_secrets.assert_not_called()


def test_api_dialog_accepts_credentials_and_blank_preserves_token(monkeypatch):
    from rest_framework.test import APIClient
    from apps.integrations import warehouse_credential_service
    actor, warehouse, config, _ = _fixture()
    config.environment = "production"
    config.platform_config = {"api_type": "inventory", "contract_approved": True}
    config.save(update_fields=["environment", "platform_config"])
    custody = Mock()
    custody.store_secrets.return_value = {"credential_id": "opaque-warehouse"}
    monkeypatch.setattr(warehouse_credential_service, "get_custody_backend", lambda: custody)
    client = APIClient()
    client.force_authenticate(actor)
    payload = {"warehouse_id": warehouse.pk, "integration_config_id": config.pk,
               "email": "demo@example.test", "token": "FAKE_TOKEN", "external_warehouse_code": ""}
    response = client.post("/api/internal/integrations/warehouse-authorizations/", payload, format="json")
    assert response.status_code == 201, response.data
    assert "FAKE_TOKEN" not in str(response.data)
    payload["token"] = ""
    response = client.post("/api/internal/integrations/warehouse-authorizations/", payload, format="json")
    assert response.status_code == 200, response.data
    custody.store_secrets.assert_called_once()
    assert WarehouseAuthorization.objects.get().bootstrap_credential_id == "opaque-warehouse"
    assert WarehouseAuthorization.objects.get().external_warehouse_code == ""


def test_archive_creation_without_api_fields_does_not_create_authorization():
    from rest_framework.test import APIClient
    actor, warehouse, _, _ = _fixture()
    client = APIClient()
    client.force_authenticate(actor)
    result = client.post("/api/internal/master-data/warehouses/", {
        "code": "ARCHIVE-ONLY", "name": "Archive only", "country_code": "MY",
        "warehouse_type": "third_party", "status": "active", "service_platform_id": warehouse.service_platform_id,
    }, format="json")
    assert result.status_code == 201
    assert not WarehouseAuthorization.objects.exists()


def test_refresh_uses_only_warehouse_refresh_token_and_requires_recheck(monkeypatch):
    from apps.integrations.readonly_clients import JifengWmsReadonlyClient
    from apps.integrations.warehouse_credential_service import refresh_warehouse_authorization
    actor, record = binding()
    record.email = "demo@example.test"
    record.oauth_user_id = "456"
    record.token_id = "warehouse-oauth"
    record.validation_status = "verified"
    record.last_verified_at = timezone.now()
    record.save()
    config = record.integration_config
    config.platform_config = {"api_host": "https://example.test/api", "client_id": "TEST_CLIENT"}
    config.save(update_fields=["platform_config"])
    custody = Mock()
    custody.retrieve_secret.return_value = "FAKE_SECRET"
    custody.retrieve_refresh_token.return_value = "FAKE_REFRESH"
    custody.store_secrets.return_value = {"token_id": "new-warehouse-oauth"}
    http = Mock()
    http.request.return_value.status_code = 200
    http.request.return_value.json.return_value = {"code": 0, "data": {
        "accessToken": "FAKE_ACCESS", "refreshToken": "FAKE_NEW_REFRESH", "userId": 456}}
    monkeypatch.setattr(JifengWmsReadonlyClient, "preflight", lambda self: None)
    refreshed = refresh_warehouse_authorization(actor=actor, authorization=record, http=http, custody=custody)
    custody.retrieve_refresh_token.assert_called_once_with("warehouse-oauth")
    assert refreshed.token_id == "new-warehouse-oauth"
    assert refreshed.validation_status == "pending"
    assert refreshed.last_verified_at is None
    assert "/api/oauth/refreshToken?" in http.request.call_args.args[1]
    assert "email=" not in http.request.call_args.args[1]
    metadata = custody.store_secrets.call_args.kwargs["metadata"]
    assert EncryptedFileCustodyBackend._metadata({"metadata": metadata}) == {
        "tenant_id": actor.tenant_id, "warehouse_binding_id": record.pk,
    }


def test_failed_readonly_check_never_marks_connected(monkeypatch):
    from rest_framework.test import APIClient
    from apps.integrations.readonly_clients import JifengWmsReadonlyClient
    actor, record = binding()
    monkeypatch.setattr("apps.integrations.readonly_clients.get_custody_backend", lambda: Mock())
    def rejected(*args, **kwargs):
        raise ValidationError("极风认证失败。")
    monkeypatch.setattr(JifengWmsReadonlyClient, "fetch_inventory", rejected)
    client = APIClient()
    client.force_authenticate(actor)
    response = client.post(f"/api/internal/integrations/warehouse-authorizations/{record.pk}/readonly-check/", {}, format="json")
    assert response.status_code == 400, response.data
    record.refresh_from_db()
    assert record.validation_status == "failed"
    assert record.last_verified_at is None


def test_first_authorization_uses_no_retry_transport_and_stores_distinct_oauth(monkeypatch):
    from apps.integrations import warehouse_credential_service as service
    from apps.integrations.readonly_clients import JifengWmsReadonlyClient
    actor, record = binding()
    record.email = "demo@example.test"
    record.bootstrap_credential_id = "opaque-bootstrap"
    record.save()
    record.integration_config.platform_config = {"api_host": "https://example.test/api", "domain": "TEST", "client_id": "CLIENT"}
    custody = Mock()
    custody.retrieve_secret.return_value = "FAKE_SECRET"
    custody.store_secrets.return_value = {"token_id": "opaque-oauth"}
    first, second = Mock(status_code=200), Mock(status_code=200)
    first.json.return_value = {"code": 0, "data": "FAKE_CODE"}
    second.json.return_value = {"code": 0, "data": {"accessToken": "FAKE_ACCESS", "refreshToken": "FAKE_REFRESH", "userId": 789}}
    http = Mock()
    http.request.side_effect = [first, second]
    factory = Mock(return_value=http)
    monkeypatch.setattr(service, "PlatformHttpClient", factory)
    monkeypatch.setattr(JifengWmsReadonlyClient, "preflight", lambda self: None)
    authorized = service.authorize_warehouse(actor=actor, authorization=record, custody=custody)
    factory.assert_called_once_with(max_retries=0)
    assert http.request.call_count == 2
    assert authorized.oauth_user_id == "789"
    assert authorized.bootstrap_credential_id == "opaque-bootstrap"
    assert authorized.token_id == "opaque-oauth"
    assert authorized.bootstrap_consumed_at is not None
    assert authorized.validation_status == "pending"
    assert authorized.last_verified_at is None
    metadata = custody.store_secrets.call_args.kwargs["metadata"]
    assert EncryptedFileCustodyBackend._metadata({"metadata": metadata}) == {
        "tenant_id": actor.tenant_id, "warehouse_binding_id": record.pk,
    }


def test_legacy_warehouse_metadata_edit_keeps_missing_credentials():
    from rest_framework.test import APIClient
    actor, record = binding()
    client = APIClient()
    client.force_authenticate(actor)
    response = client.patch(f"/api/internal/master-data/warehouses/{record.warehouse_id}/", {
        "name": "Updated warehouse", "api_integration_config_id": record.integration_config_id, "api_token": "",
    }, format="json")
    assert response.status_code == 200, response.data
    record.refresh_from_db()
    assert record.email == ""
    assert record.bootstrap_credential_id == ""
    assert record.validation_status == "incomplete"
