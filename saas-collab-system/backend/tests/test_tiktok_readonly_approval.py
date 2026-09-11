from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rest_framework.exceptions import ValidationError

from apps.integrations import readonly_clients as clients


def configured(monkeypatch, resource, runtime):
    runtime = {'api_host': 'https://approved.example.test', **runtime}
    monkeypatch.setattr(clients, 'get_runtime_platform_config', lambda platform: runtime)
    monkeypatch.setattr(clients, 'get_runtime_setting', lambda *args, **kwargs: True)
    monkeypatch.setattr(clients, 'is_module_enabled', lambda *args: True)
    monkeypatch.setattr(clients, 'require_live_mode', lambda *args: None)
    config = SimpleNamespace(platform='tiktok', environment='production', status='verified',
        platform_config={}, network_enabled=True, sync_read_enabled=True, sync_write_enabled=False)
    client = clients.TikTokReadonlyClient(config, http_client=Mock(), custody=Mock())
    client.resource_type = resource
    return client


@pytest.mark.parametrize('resource', ['sales_order', 'refund_return', 'platform_product'])
@pytest.mark.parametrize('legacy', [None, False])
def test_runtime_approval_is_authoritative(monkeypatch, resource, legacy):
    client = configured(monkeypatch, resource, {'contract_approved': True, 'product_contract_approved': True})
    if legacy is not None:
        client.platform_config.update(contract_approved=legacy, product_contract_approved=legacy)
    client.preflight()
    client.http.request.assert_not_called()
    assert not client.custody.mock_calls


@pytest.mark.parametrize('resource,key', [('sales_order', 'contract_approved'),
    ('refund_return', 'contract_approved'), ('platform_product', 'product_contract_approved')])
@pytest.mark.parametrize('approval', [False, None])
def test_legacy_approval_cannot_override_runtime_denial(monkeypatch, resource, key, approval):
    client = configured(monkeypatch, resource, {key: approval})
    client.platform_config.update(contract_approved=True, product_contract_approved=True)
    with pytest.raises(ValidationError, match='not approved'):
        client.preflight()
    client.http.request.assert_not_called()
    assert not client.custody.mock_calls


@pytest.mark.parametrize('resource', ['sales_order', 'refund_return'])
def test_product_approval_does_not_grant_orders_or_returns(monkeypatch, resource):
    client = configured(monkeypatch, resource, {'product_contract_approved': True})
    with pytest.raises(ValidationError, match='not approved'):
        client.preflight()


@pytest.mark.parametrize('field,value', [('network_enabled', False), ('sync_read_enabled', False),
    ('sync_write_enabled', True), ('status', 'draft'), ('environment', 'mock')])
def test_other_preflight_gates_remain_enforced(monkeypatch, field, value):
    client = configured(monkeypatch, 'sales_order', {'contract_approved': True})
    setattr(client.config, field, value)
    with pytest.raises(ValidationError):
        client.preflight()
    client.http.request.assert_not_called()
