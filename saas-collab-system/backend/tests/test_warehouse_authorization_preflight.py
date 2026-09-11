from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rest_framework.exceptions import ValidationError

from apps.common.exceptions import custom_exception_handler
from apps.integrations.readonly_clients import JifengWmsReadonlyClient
from apps.integrations.warehouse_credential_service import authorize_warehouse


@pytest.fixture
def warehouse(monkeypatch):
    monkeypatch.setattr("apps.integrations.readonly_clients.is_module_enabled", lambda *args: True)
    monkeypatch.setattr("apps.integrations.readonly_clients.require_live_mode", lambda *args: None)
    monkeypatch.setattr("apps.integrations.readonly_clients.get_runtime_setting", lambda *args, **kwargs: True)
    monkeypatch.setattr("apps.integrations.warehouse_readiness.get_runtime_platform_config", lambda *args: {"contract_approved": False})
    config = SimpleNamespace(platform="jifeng_wms", environment="production", status="verified",
        network_enabled=False, sync_read_enabled=True, sync_write_enabled=False,
        platform_config={"contract_approved": False})
    return SimpleNamespace(integration_config=config, bootstrap_consumed_at=None)


def test_authorize_lists_all_config_blockers_without_consuming_token(warehouse):
    http, custody = Mock(), Mock()
    with pytest.raises(ValidationError) as error:
        authorize_warehouse(actor=SimpleNamespace(), authorization=warehouse, http=http, custody=custody)
    response = custom_exception_handler(error.value, {})
    assert response.status_code == 400
    assert "网络访问未审批" in response.data["message"]
    assert "接口合同未确认" in response.data["message"]
    assert "error message" not in response.data["message"]
    assert warehouse.bootstrap_consumed_at is None
    http.request.assert_not_called()
    custody.retrieve_secret.assert_not_called()


def test_contract_remains_blocked_after_network_approval(warehouse):
    warehouse.integration_config.network_enabled = True
    client = JifengWmsReadonlyClient(warehouse.integration_config, custody=Mock())
    with pytest.raises(ValidationError) as error:
        client.preflight()
    assert "接口合同未确认" in str(error.value)


def test_approved_config_still_refuses_write_capability(warehouse):
    config = warehouse.integration_config
    config.network_enabled = True
    config.platform_config["contract_approved"] = True
    config.sync_write_enabled = True
    client = JifengWmsReadonlyClient(config, custody=Mock())
    with pytest.raises(ValidationError):
        client.preflight()
