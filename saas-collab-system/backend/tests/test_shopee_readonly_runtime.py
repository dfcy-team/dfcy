from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.integrations import readonly_clients as clients


def configured(monkeypatch, runtime):
    monkeypatch.setattr(clients, "get_runtime_platform_config", lambda platform: runtime)
    monkeypatch.setattr(clients, "get_runtime_setting", lambda *args, **kwargs: True)
    monkeypatch.setattr(clients, "is_module_enabled", lambda *args: True)
    monkeypatch.setattr(clients, "require_live_mode", lambda *args: None)
    config = SimpleNamespace(platform="shopee", environment="production", status="verified",
        platform_config={"partner_id": "123"}, network_enabled=True, sync_read_enabled=True,
        sync_write_enabled=False, credential_id="FAKE_REFERENCE", connect_timeout_seconds=1, read_timeout_seconds=1)
    authorization = SimpleNamespace(status="active", Status=SimpleNamespace(ACTIVE="active"),
        token_id="FAKE_TOKEN_REFERENCE", platform_store_id="456", expires_at=timezone.now() + timedelta(hours=1))
    custody, http = Mock(), Mock()
    custody.retrieve_secret.return_value = "FAKE_SECRET"
    custody.retrieve_access_token.return_value = "FAKE_ACCESS"
    http.request.return_value.json.return_value = {"error": "", "response": {"order_list": []}}
    return clients.ShopeeReadonlyClient(config, authorization, http_client=http, custody=custody), http


@pytest.mark.parametrize("resource", ["sales_order", "refund_return", "platform_product"])
def test_shopee_reads_approved_runtime_contract_and_host(monkeypatch, resource):
    client, http = configured(monkeypatch, {"contract_approved": True,
        "product_contract_approved": True, "api_host": "https://approved.example.test"})
    client.resource_type = resource
    client._request("/api/v2/order/get_order_list", {})
    assert urlsplit(http.request.call_args.args[1]).hostname == "approved.example.test"


@pytest.mark.parametrize("resource,key", [("sales_order", "contract_approved"),
    ("refund_return", "contract_approved"), ("platform_product", "product_contract_approved")])
def test_local_legacy_approval_cannot_bypass_runtime_denial(monkeypatch, resource, key):
    client, http = configured(monkeypatch, {key: False, "api_host": "https://approved.example.test"})
    client.resource_type = resource
    client.platform_config.update(contract_approved=True, product_contract_approved=True)
    with pytest.raises(ValidationError, match="not approved"):
        client._request("/api/v2/order/get_order_list", {})
    http.request.assert_not_called()


def test_missing_runtime_host_does_not_fall_back_to_unapproved_legacy_host(monkeypatch):
    client, http = configured(monkeypatch, {"contract_approved": True, "api_host": ""})
    client.platform_config.update(contract_approved=True, api_host="https://legacy.example.test")
    with pytest.raises(ValidationError, match="shopee.api_host"):
        client._request("/api/v2/order/get_order_list", {})
    http.request.assert_not_called()
