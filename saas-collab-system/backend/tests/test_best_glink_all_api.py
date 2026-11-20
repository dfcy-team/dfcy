import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.test import override_settings
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.integrations.best_glink import BestGlinkClient, OPERATIONS, prepare_operation
from apps.integrations.best_glink_contract import CONTRACTS, CALLBACKS, request_template


def scoped(value):
    if isinstance(value, dict):
        return {key: "TEST-C" if key in {"customerCode", "ownerCode"}
                else "TEST-W" if key in {"warehouseCode", "whCode"} else scoped(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [scoped(item) for item in value]
    return value


def make_client():
    config = SimpleNamespace(platform_config={"partner_id": "TEST-P", "customer_code": "TEST-C"},
        credential_id="synthetic-reference", environment="production", connect_timeout_seconds=3, read_timeout_seconds=8)
    auth = SimpleNamespace(external_warehouse_code="TEST-W", integration_config=config)
    http, custody = Mock(), Mock()
    custody.retrieve_secret.return_value = "TEST-ONLY-KEY"
    http.request.return_value = SimpleNamespace(status_code=200, text='{"success":true}')
    client = BestGlinkClient(config, auth, http_client=http, custody=custody)
    client.preflight = Mock()
    return client, http


def test_documented_contract_is_complete_and_directions_are_separate():
    assert len(CONTRACTS) == 30
    assert len(OPERATIONS) == 26
    assert len(CALLBACKS) == 4
    assert sum(item.write for item in OPERATIONS) == 10
    assert not {item.name for item in OPERATIONS}.intersection(CALLBACKS)


@pytest.mark.parametrize("operation", OPERATIONS, ids=lambda item: item.name)
@override_settings(WAREHOUSE_BUSINESS_WRITE_ENABLED=True)
def test_every_documented_request_sample_is_signed_and_scoped(operation):
    client, http = make_client()
    fields = {**scoped(request_template(operation.name)), "customerCode": "TEST-C", "warehouseCode": "TEST-W"}
    payload = {"bizData": json.dumps(fields)}
    prepared = prepare_operation(operation.name, payload)
    assert prepared["requires_confirmation"] is operation.write
    result = client._signed_request("POST", operation.name, payload)
    assert result["code"] == "0"
    sent = http.request.call_args.kwargs["form_body"]
    assert sent["partnerId"] == "TEST-P"
    assert sent["serviceType"] == operation.name
    assert sent["sign"] == hashlib.md5((sent["bizData"] + "TEST-ONLY-KEY").encode()).hexdigest()
    assert http.request.call_args.kwargs["retry"] is False
    data = json.loads(sent["bizData"])
    if operation.name == "GLINK_QUERY_STOCK_SNAP_NOTIFY":
        assert data["whCode"] == "TEST-W" and "warehouseCode" not in data
    if operation.name == "GLINK_QUERY_WORK_ORDER":
        assert data["ownerCode"] == "TEST-C" and "customerCode" not in data


@pytest.mark.parametrize("operation", [item for item in OPERATIONS if item.write], ids=lambda item: item.name)
def test_every_write_is_denied_when_write_feature_is_off(operation):
    client, http = make_client()
    fields = {**scoped(request_template(operation.name)), "customerCode": "TEST-C", "warehouseCode": "TEST-W"}
    with override_settings(WAREHOUSE_BUSINESS_WRITE_ENABLED=False), pytest.raises(PermissionDenied):
        client._signed_request("POST", operation.name, {"bizData": json.dumps(fields)})
    http.request.assert_not_called()


@pytest.mark.parametrize("name", CALLBACKS)
def test_callback_cannot_be_sent_as_an_outbound_request(name):
    with pytest.raises(ValidationError):
        prepare_operation(name, {"bizData": "{}"})


def test_alias_override_and_response_tenant_conflict_are_rejected():
    client, http = make_client()
    with pytest.raises(PermissionDenied):
        client.query("GLINK_QUERY_STOCK_SNAP_NOTIFY", {"whCode": "OTHER", "eventDate": "2026-11-19"})
    with pytest.raises(PermissionDenied):
        client.query("GLINK_QUERY_WORK_ORDER", {"ownerCode": "OTHER", "workOrderList": ["WO1"]})
    http.request.assert_not_called()
    http.request.return_value.text = '{"success":true,"resultList":[{"customerCode":"OTHER"}]}'
    with pytest.raises(PermissionDenied):
        client.query("GLINK_QUERY_WAREHOUSE_NOTIFY", {})


@pytest.fixture
def callback_binding():
    from tests.test_warehouse_api_binding_closure import _fixture
    from apps.integrations.models import WarehouseAuthorization
    actor, warehouse, config, _ = _fixture()
    config.platform = "best_ecapi"
    config.contract_version = "glink"
    config.platform_config = {"partner_id": "TEST-P", "customer_code": "TEST-C"}
    config.save()
    binding = WarehouseAuthorization.objects.create(tenant=actor.tenant, warehouse=warehouse,
        integration_config=config, provider="best_ecapi", external_warehouse_code="TEST-W",
        external_warehouse_region="MY", status="active", validation_status="verified", created_by=actor, updated_by=actor)
    return actor, binding


def callback_request(binding, name, *, mutate=None, bad_signature=False):
    from django.test import RequestFactory
    from urllib.parse import urlencode
    data = scoped(CONTRACTS[name]["examples"][0])
    data["partnerId"] = "TEST-P"
    if mutate:
        mutate(data)
    raw = json.dumps(data, ensure_ascii=False)
    fields = {"partnerId": "TEST-P", "serviceType": name, "bizData": raw,
        "sign": "0" * 32 if bad_signature else hashlib.md5((raw + "TEST-ONLY-KEY").encode()).hexdigest()}
    return RequestFactory().post("/callback", urlencode(fields), content_type="application/x-www-form-urlencoded")


@pytest.mark.django_db
@pytest.mark.parametrize("name", CALLBACKS)
@override_settings(BEST_GLINK_CALLBACKS_ENABLED=True, RAW_PAYLOAD_STORAGE_ALIAS="")
def test_each_callback_is_verified_persisted_and_deduplicated(callback_binding, name):
    from unittest.mock import patch
    from apps.integrations.best_glink_callbacks import receive
    from apps.integrations.models import WebhookEvent, SyncRawEnvelope
    from apps.commerce.models import InboundRecord
    actor, binding = callback_binding
    with patch("apps.integrations.best_glink_callbacks.get_custody_backend") as custody:
        custody.return_value.retrieve_secret.return_value = "TEST-ONLY-KEY"
        for _ in range(2):
            response = receive(callback_request(binding, name), binding.integration_config_id)
            assert response.status_code == 200
            assert json.loads(response.content)["success"] is True
    event = WebhookEvent.objects.get(tenant=actor.tenant)
    assert event.signature_status == "valid" and event.processing_status == "received"
    assert SyncRawEnvelope.objects.count() == 1
    assert event.raw_envelope.payload["payload"]["warehouse_authorization_id"] == binding.pk
    assert "partnerId" not in event.raw_envelope.payload["payload"]["bizData"]
    assert not InboundRecord.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("failure", ["signature", "customer", "warehouse", "nested", "credential", "disabled", "storage"])
@override_settings(BEST_GLINK_CALLBACKS_ENABLED=True, RAW_PAYLOAD_STORAGE_ALIAS="")
def test_invalid_callback_never_acknowledges_or_keeps_partial_event(callback_binding, failure):
    from unittest.mock import patch
    from apps.integrations.best_glink_callbacks import receive
    from apps.integrations.models import WebhookEvent
    _, binding = callback_binding
    changes = {
        "customer": lambda d: d.update(customerCode="OTHER"),
        "warehouse": lambda d: d.update(warehouseCode="OTHER"),
        "nested": lambda d: d.update(extra={"warehouseCode": "OTHER"}),
        "credential": lambda d: d.update(partnerKey="TEST-ONLY-KEY"),
    }
    request = callback_request(binding, "GLINK_ADJUST_STOCK_PUSH", mutate=changes.get(failure),
        bad_signature=failure == "signature")
    with patch("apps.integrations.best_glink_callbacks.get_custody_backend") as custody:
        custody.return_value.retrieve_secret.return_value = "TEST-ONLY-KEY"
        if failure == "storage":
            with patch("apps.integrations.best_glink_callbacks.archive_webhook_payload", side_effect=ValidationError("storage unavailable")):
                with pytest.raises(ValidationError):
                    receive(request, binding.integration_config_id)
        else:
            with override_settings(BEST_GLINK_CALLBACKS_ENABLED=failure != "disabled"):
                response = receive(request, binding.integration_config_id)
            assert response.status_code >= 400
    assert not WebhookEvent.objects.exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("name", [item.name for item in OPERATIONS if item.write])
@override_settings(WAREHOUSE_BUSINESS_API_ENABLED=True, WAREHOUSE_BUSINESS_WRITE_ENABLED=True)
def test_each_manual_write_keeps_durable_fence_on_timeout(callback_binding, name):
    from unittest.mock import patch
    from django.utils import timezone
    from apps.common.exceptions import StateConflict
    from apps.integrations.models import WarehouseApiAttempt
    from apps.integrations.warehouse_api_service import execute_operation
    actor, binding = callback_binding
    binding.last_verified_at = timezone.now()
    binding.save()
    fields = {**scoped(request_template(name)), "customerCode": "TEST-C", "warehouseCode": "TEST-W"}
    client = Mock()
    client._signed_request.side_effect = TimeoutError("synthetic timeout")
    arguments = dict(actor=actor, authorization=binding, name=name,
        payload={"bizData": json.dumps(fields)}, idempotency_key="TEST-DURABLE-WRITE-KEY", client=client)
    with patch("apps.integrations.warehouse_api_service.check_user_permission", return_value=True), \
            patch("apps.integrations.warehouse_api_service.integration_values_allowed", return_value=True):
        with pytest.raises(ValidationError):
            execute_operation(**arguments)
        client._signed_request.assert_not_called()
        with pytest.raises(ValidationError):
            execute_operation(**arguments, confirmed=True)
        assert WarehouseApiAttempt.objects.get().status == "unknown"
        with pytest.raises(StateConflict):
            execute_operation(**arguments, confirmed=True)
    assert client._signed_request.call_count == 1


@pytest.mark.django_db
def test_callback_inbox_is_tenant_and_warehouse_scoped(callback_binding):
    from unittest.mock import patch
    from django.test import RequestFactory
    from rest_framework.test import force_authenticate
    from apps.integrations.warehouse_api_views import best_notifications
    from apps.tenants.models import Tenant
    from apps.accounts.models import CustomUser
    actor, binding = callback_binding
    request = RequestFactory().get('/inbox')
    force_authenticate(request, user=actor)
    with patch('apps.permissions.ui_p6_scopes.integration_values_allowed', return_value=False):
        assert best_notifications(request, binding.pk).status_code == 403
    other = Tenant.objects.create(name='Other callback tenant', code='callback-other')
    outsider = CustomUser.objects.create_user(username='callback-outsider', tenant=other, is_superuser=True)
    request = RequestFactory().get('/inbox')
    force_authenticate(request, user=outsider)
    assert best_notifications(request, binding.pk).status_code in {403, 404}


@pytest.mark.django_db
@override_settings(BEST_GLINK_CALLBACKS_ENABLED=True)
def test_callback_rechecks_credential_state_before_acknowledging(callback_binding):
    from unittest.mock import patch
    from apps.integrations.best_glink_callbacks import receive
    from apps.integrations.models import PlatformIntegrationConfig, WebhookEvent, authorization_service_write
    _, binding = callback_binding
    def revoke(_):
        with authorization_service_write():
            PlatformIntegrationConfig.objects.filter(pk=binding.integration_config_id).update(credential_status="missing")
        return "TEST-ONLY-KEY"
    with patch("apps.integrations.best_glink_callbacks.get_custody_backend") as custody:
        custody.return_value.retrieve_secret.side_effect = revoke
        response = receive(callback_request(binding, "GLINK_ADJUST_STOCK_PUSH"), binding.integration_config_id)
    assert response.status_code == 409
    assert not WebhookEvent.objects.exists()
