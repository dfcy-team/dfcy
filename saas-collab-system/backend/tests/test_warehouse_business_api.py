"""Offline contract/security tests. All credentials and responses are synthetic."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch
import hashlib
import hmac

import pytest
from django.db import transaction
from django.test import override_settings
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.test import APIClient

from apps.common.exceptions import StateConflict
from apps.integrations.models import WarehouseApiAttempt
from apps.integrations.readonly_clients import JifengWmsReadonlyClient
from apps.integrations.warehouse_api_contract import OPERATIONS, prepare_operation
from apps.integrations.warehouse_api_service import execute_operation


def payload_for(name):
    if name == "order_get":
        return {"platformOrderNo": "OFFLINE-ORDER-001"}
    if name == "return_get":
        return {"returnNo": "OFFLINE-RETURN-001"}
    return {"erpNo": "OFFLINE-ERP-001"}


def transport_client():
    now = timezone.now()
    config = SimpleNamespace(platform="jifeng_wms", platform_config={
        "api_host": "https://warehouse.example.test/api", "client_id": "FAKE_CLIENT_ID", "site_code": "PH"},
        credential_id="fake-secret-ref", connect_timeout_seconds=3, read_timeout_seconds=5)
    authorization = SimpleNamespace(status="active", Status=SimpleNamespace(ACTIVE="active"),
        external_warehouse_region="PH", oauth_user_id="FAKE_USER", email="fixture@example.test",
        oauth_expires_at=now + timedelta(hours=1), token_id="fake-token-ref")
    custody = Mock()
    custody.retrieve_secret.return_value = "FAKE_CLIENT_SECRET"
    custody.retrieve_access_token.return_value = "FAKE_ACCESS_TOKEN"
    http = Mock()
    http.request.return_value.json.return_value = {"code": 0, "data": {"offline": True}}
    client = JifengWmsReadonlyClient(config, authorization, custody=custody, http_client=http, now=lambda: now)
    client.preflight = Mock()
    return client, http


def test_catalog_has_39_unique_business_contracts_and_no_arbitrary_url():
    assert len(OPERATIONS) == len({op.path for op in OPERATIONS}) == len({op.name for op in OPERATIONS}) == 39
    assert {op.method for op in OPERATIONS} == {"GET", "POST"}
    with pytest.raises(ValidationError):
        prepare_operation("https://example.test/api/order/create", {})


@pytest.mark.parametrize("operation", OPERATIONS, ids=lambda op: op.name)
def test_every_contract_uses_correct_path_method_and_signature(operation):
    prepared = prepare_operation(operation.name, payload_for(operation.name))
    assert prepared["execution_enabled"] is False
    assert prepared["requires_confirmation"] is operation.write
    client, http = transport_client()
    result = client._signed_request(operation.method, operation.path, prepared["payload"])
    assert result["code"] == 0
    args, kwargs = http.request.call_args
    assert args[0] == operation.method
    assert args[1].split("?")[0] == "https://warehouse.example.test" + operation.path
    headers = kwargs["headers"]
    sign_values = {k: headers[k] for k in ["accessToken", "clientId", "nonce", "timestamp", "userId"]}
    sign_values.update(method=operation.method.lower(), url=operation.path)
    data = "&".join(f"{key}={sign_values[key]}" for key in sorted(sign_values))
    assert headers["sign"] == hmac.new(b"FAKE_CLIENT_SECRET", data.encode(), hashlib.sha256).hexdigest()
    assert kwargs["json_body"] == (prepared["payload"] if operation.method == "POST" else None)
    if operation.method == "GET":
        assert "erpNo=OFFLINE-ERP-001" in args[1]


@pytest.mark.parametrize("payload", [None, "text", {"accessToken": "FAKE"}, {"list": [{"client_secret": "FAKE"}]}, {"amount": float("nan")}])
def test_unsafe_payloads_fail_before_network(payload):
    with pytest.raises(ValidationError):
        prepare_operation("order_create", payload)


@pytest.mark.parametrize("payload", [{}, {"erpNo": "A", "platformOrderNo": "B"}, {"erpNo": ""}, {"erpNo": "A\nB"}])
def test_order_selector_is_exactly_one_nonempty_identifier(payload):
    with pytest.raises(ValidationError):
        prepare_operation("order_get", payload)


@override_settings(WAREHOUSE_BUSINESS_API_ENABLED=False, WAREHOUSE_BUSINESS_WRITE_ENABLED=False)
@pytest.mark.parametrize("operation", OPERATIONS, ids=lambda op: op.name)
def test_disabled_gate_never_touches_custody_network_or_database(operation):
    client = Mock()
    with pytest.raises(PermissionDenied):
        execute_operation(actor=None, authorization=None, name=operation.name,
            payload=payload_for(operation.name), client=client)
    assert not client.mock_calls


@pytest.fixture
def authorized_record():
    from tests.test_warehouse_api_binding_closure import _fixture
    from apps.integrations.warehouse_authorization_service import bind_warehouse_authorization
    actor, warehouse, config, _ = _fixture()
    record, _, _ = bind_warehouse_authorization(actor=actor, warehouse=warehouse, integration_config=config)
    record.email = "fixture@example.test"
    record.bootstrap_credential_id = "fake-bootstrap"
    record.oauth_user_id = "FAKE_USER"
    record.token_id = "fake-access-ref"
    record.oauth_expires_at = timezone.now() + timedelta(hours=1)
    record.external_warehouse_code = "TEST-WAREHOUSE"
    record.external_warehouse_region = "MY"
    record.validation_status = "verified"
    record.last_verified_at = timezone.now()
    record.save()
    return actor, record


@pytest.mark.django_db(transaction=True)
@override_settings(WAREHOUSE_BUSINESS_API_ENABLED=True, WAREHOUSE_BUSINESS_WRITE_ENABLED=True)
def test_manual_write_has_durable_fence_and_timeout_cannot_replay(authorized_record):
    actor, record = authorized_record
    client = Mock()
    client._signed_request.side_effect = TimeoutError("synthetic timeout")
    with patch("apps.integrations.warehouse_api_service.check_user_permission", return_value=True), \
            patch("apps.integrations.warehouse_api_service.integration_values_allowed", return_value=True):
        with pytest.raises(ValidationError):
            execute_operation(actor=actor, authorization=record, name="order_cancel", payload={"erpNo": "OFFLINE-1"},
                confirmed=True, idempotency_key="offline-attempt-001", client=client)
        assert WarehouseApiAttempt.objects.get().status == "unknown"
        with pytest.raises(StateConflict):
            execute_operation(actor=actor, authorization=record, name="order_cancel", payload={"erpNo": "OFFLINE-1"},
                confirmed=True, idempotency_key="offline-attempt-001", client=client)
    assert client._signed_request.call_count == 1


@pytest.mark.django_db(transaction=True)
@override_settings(WAREHOUSE_BUSINESS_API_ENABLED=True, WAREHOUSE_BUSINESS_WRITE_ENABLED=True)
def test_write_confirmation_warehouse_scope_and_secret_redaction(authorized_record):
    actor, record = authorized_record
    client = Mock()
    client._signed_request.return_value = {"code": 0, "data": {"orderNo": "OFFLINE-1", "invoiceSecretKey": "FAKE"}}
    with patch("apps.integrations.warehouse_api_service.check_user_permission", return_value=True), \
            patch("apps.integrations.warehouse_api_service.integration_values_allowed", return_value=True):
        with pytest.raises(PermissionDenied):
            execute_operation(actor=actor, authorization=record, name="order_create", payload={"warehouse": "OTHER"},
                confirmed=True, idempotency_key="offline-attempt-002", client=client)
        with pytest.raises(ValidationError):
            execute_operation(actor=actor, authorization=record, name="order_cancel", payload={"erpNo": "OFFLINE-1"}, client=client)
        assert not client._signed_request.called
        result = execute_operation(actor=actor, authorization=record, name="order_cancel", payload={"erpNo": "OFFLINE-1"},
            confirmed=True, idempotency_key="offline-attempt-002", client=client)
    assert result["data"]["invoiceSecretKey"] == "<REDACTED>"
    assert result["local_business_updated"] is False
    assert WarehouseApiAttempt.objects.get().status == "succeeded"


@pytest.mark.django_db
def test_catalog_and_preview_work_without_warehouse_auth_and_do_not_call_network(authorized_record):
    actor, record = authorized_record
    client = APIClient()
    client.force_authenticate(actor)
    with patch("apps.integrations.net_guard.PlatformHttpClient.request", side_effect=AssertionError("network forbidden")):
        assert client.get("/api/internal/integrations/warehouse-api/operations/").status_code == 200
        response = client.post("/api/internal/integrations/warehouse-api/preview/", {
            "operation": "order_get", "payload": {"platformOrderNo": "OFFLINE-1"}}, format="json")
        assert response.status_code == 200
    assert WarehouseApiAttempt.objects.count() == 0


@pytest.mark.django_db
@override_settings(WAREHOUSE_BUSINESS_API_ENABLED=True, WAREHOUSE_BUSINESS_WRITE_ENABLED=True)
def test_cross_tenant_and_atomic_write_are_blocked(authorized_record):
    actor, record = authorized_record
    client = Mock()
    with pytest.raises(PermissionDenied):
        execute_operation(actor=SimpleNamespace(tenant_id=-1), authorization=record, name="order_get",
            payload={"erpNo": "OFFLINE"}, client=client)
    with patch("apps.integrations.warehouse_api_service.check_user_permission", return_value=True), \
            patch("apps.integrations.warehouse_api_service.integration_values_allowed", return_value=True), transaction.atomic():
        with pytest.raises(ValidationError):
            execute_operation(actor=actor, authorization=record, name="order_cancel", payload={"erpNo": "OFFLINE"},
                confirmed=True, idempotency_key="offline-attempt-003", client=client)
    assert not client._signed_request.called


@pytest.mark.parametrize("value", [False, "false", "true", 1, None])
def test_gate_requires_explicit_boolean_true(value):
    with override_settings(WAREHOUSE_BUSINESS_API_ENABLED=value), pytest.raises(PermissionDenied):
        execute_operation(actor=None, authorization=None, name="order_get", payload={"erpNo": "OFFLINE"})


@pytest.mark.django_db(transaction=True)
@override_settings(WAREHOUSE_BUSINESS_API_ENABLED=True, WAREHOUSE_BUSINESS_WRITE_ENABLED=True)
@pytest.mark.parametrize("response", [{"code": 50017, "message": "synthetic rejection"},
    {"code": 0, "data": {"warehouseCode": "OTHER"}}, {"data": {}}])
def test_rejected_or_mismatched_response_never_marks_write_success(authorized_record, response):
    actor, record = authorized_record
    client = Mock()
    client._signed_request.return_value = response
    with patch("apps.integrations.warehouse_api_service.check_user_permission", return_value=True), \
            patch("apps.integrations.warehouse_api_service.integration_values_allowed", return_value=True):
        with pytest.raises(ValidationError):
            execute_operation(actor=actor, authorization=record, name="order_cancel", payload={"erpNo": "OFFLINE"},
                confirmed=True, idempotency_key="offline-attempt-004", client=client)
    assert WarehouseApiAttempt.objects.get().status in {"rejected", "unknown"}


@pytest.mark.django_db(transaction=True)
@override_settings(WAREHOUSE_BUSINESS_API_ENABLED=True, WAREHOUSE_BUSINESS_WRITE_ENABLED=True)
def test_validation_error_after_reservation_marks_result_unknown(authorized_record):
    actor, record = authorized_record
    client = Mock()
    client._signed_request.side_effect = ValidationError("synthetic invalid provider JSON")
    with patch("apps.integrations.warehouse_api_service.check_user_permission", return_value=True), \
            patch("apps.integrations.warehouse_api_service.integration_values_allowed", return_value=True):
        with pytest.raises(ValidationError):
            execute_operation(actor=actor, authorization=record, name="order_cancel", payload={"erpNo": "OFFLINE"},
                confirmed=True, idempotency_key="offline-attempt-005", client=client)
    assert WarehouseApiAttempt.objects.get().status == "unknown"
