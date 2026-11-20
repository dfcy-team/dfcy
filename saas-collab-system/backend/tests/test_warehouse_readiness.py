from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError

from apps.integrations import warehouse_readiness as gates
from apps.integrations.production_settings import SAFE_DEFAULTS, validate_runtime_config
from apps.integrations.readiness_service import build_config_readiness, build_platform_readiness
from apps.integrations.readonly_clients import JifengWmsReadonlyClient


@pytest.fixture
def ready_warehouse_config(monkeypatch, settings):
    settings.DEBUG = False
    network = {"mode": "approved-live-test", "security_approved": True,
        "readonly_sync_enabled": True, "allowed_hosts": ["wms.example.test"]}
    runtime = {"contract_approved": True}
    monkeypatch.setattr(gates, "get_runtime_setting", lambda section, key, **kwargs: network.get(key))
    monkeypatch.setattr(gates, "get_runtime_platform_config", lambda platform: runtime)
    monkeypatch.setattr(gates, "is_module_enabled", lambda *args: True)
    monkeypatch.setattr(gates, "approved_custody_configured", lambda: True)
    monkeypatch.setattr("apps.integrations.readiness_service.get_runtime_platform_config", lambda platform: runtime)
    monkeypatch.setattr("apps.integrations.readiness_service.get_runtime_setting", lambda section, key, **kwargs: network.get(key))
    monkeypatch.setattr("apps.integrations.readonly_clients.require_live_mode", lambda *args: None)
    monkeypatch.setattr("apps.integrations.readonly_clients.is_module_enabled", lambda *args: True)
    monkeypatch.setattr("apps.integrations.readonly_clients.get_runtime_setting", lambda *args, **kwargs: True)
    config = SimpleNamespace(id=4, platform="jifeng_wms", account_alias="test-warehouse-config",
        environment="production", status="verified", config_version=1, contract_version="legacy",
        callback_url="", network_enabled=False, sync_read_enabled=False, sync_write_enabled=False,
        credential_status="configured", credential_id="test-reference",
        platform_config={"api_host": "https://wms.example.test/api", "domain": "test-domain",
            "client_id": "test-client", "contract_approved": False})
    return config, runtime, network


def test_warehouse_runtime_only_accepts_non_secret_contract_flag():
    assert SAFE_DEFAULTS["platforms"]["jifeng_wms"] == {
        "contract_approved": False,
        "auto_refresh_enabled": False,
    }
    assert validate_runtime_config({"platforms": {"jifeng_wms": {"contract_approved": True}}})
    for field in ("email", "token", "client_secret", "api_host", "redirect_uri"):
        with pytest.raises(DjangoValidationError):
            validate_runtime_config({"platforms": {"jifeng_wms": {field: "fake-value"}}})


def test_warehouse_approval_is_not_circular_or_oauth_based(ready_warehouse_config):
    config, _, _ = ready_warehouse_config
    row = build_config_readiness(config)
    assert set(row["blocker_codes"]) == {"network_not_approved", "readonly_not_approved"}
    assert row["can_approve_readonly"] is True
    assert row["can_repair_contract"] is False
    assert row["subject_type"] == "warehouse"
    assert row["contract_approved"] is True
    assert row["supported_readonly_resources"] == ["inbound", "inventory_snapshot", "warehouse_order_lookup"]
    assert "test-reference" not in str(row)
    assert "test-client" not in str(row)
    assert any(item["platform_code"] == "jifeng_wms" for item in build_platform_readiness([config])["items"])


def test_runtime_contract_is_authoritative_and_revoke_blocks_execution(ready_warehouse_config):
    config, runtime, _ = ready_warehouse_config
    config.network_enabled = config.sync_read_enabled = True
    client = JifengWmsReadonlyClient(config, http_client=Mock(), custody=Mock())
    client.preflight()  # A stale legacy False must not override the approved runtime.
    runtime["contract_approved"] = False
    config.platform_config["contract_approved"] = True
    with pytest.raises(ValidationError, match="接口合同未确认"):
        client.preflight()  # Nor may legacy True bypass a revoked runtime version.
    assert build_config_readiness(config)["blocker_codes"] == ["platform_contract_not_enabled"]
    client.http.request.assert_not_called()
    client.custody.retrieve_secret.assert_not_called()


@pytest.mark.parametrize("field,value,blocker", [
    ("api_host", "http://wms.example.test", "warehouse_api_url_invalid"),
    ("api_host", "https://other.example.test/api", "warehouse_host_not_allowlisted"),
    ("api_host", "https://wms.example.test:444/api", "warehouse_api_url_invalid"),
    ("domain", "", "warehouse_domain_missing"),
    ("client_id", "", "warehouse_client_id_missing"),
])
def test_warehouse_public_config_blockers_disable_approval(ready_warehouse_config, field, value, blocker):
    config, _, _ = ready_warehouse_config
    config.platform_config[field] = value
    row = build_config_readiness(config)
    assert blocker in row["blocker_codes"]
    assert row["can_approve_readonly"] is False


@pytest.mark.parametrize("field,value,blocker", [
    ("status", "configured", "config_not_approved"),
    ("sync_write_enabled", True, "write_sync_enabled"),
    ("credential_id", "", "credential_reference_missing"),
])
def test_warehouse_readiness_retains_safety_gates(ready_warehouse_config, field, value, blocker):
    config, _, _ = ready_warehouse_config
    setattr(config, field, value)
    row = build_config_readiness(config)
    assert blocker in row["blocker_codes"]
    assert row["can_approve_readonly"] is False

def test_best_readiness_has_warehouse_gates_without_oauth(ready_warehouse_config, monkeypatch, settings):
    config, _, _ = ready_warehouse_config
    settings.BEST_ECAPI_ENABLED = True
    config.platform = 'best_ecapi'
    config.contract_version = 'glink'
    config.platform_config = {'partner_id': 'TEST-P', 'customer_code': 'TEST-C',
        'api_host': 'https://edi-glink.800best.com/gateway/api/glink'}
    monkeypatch.setattr('apps.integrations.net_guard.get_allowed_hosts', lambda: {'edi-glink.800best.com'})
    row = build_config_readiness(config)
    assert row['subject_type'] == 'warehouse'
    assert row['can_approve_readonly'] is True
    assert 'warehouse_domain_missing' not in row['blocker_codes']
    assert 'warehouse_client_id_missing' not in row['blocker_codes']
    config.platform_config['api_host'] = 'https://kytest.800best.com/gateway/api/glink'
    assert 'best_gateway_invalid' in build_config_readiness(config)['blocker_codes']
    config.platform_config['api_host'] = 'https://edi-glink.800best.com/gateway/api/glink'
    settings.BEST_ECAPI_ENABLED = False
    assert 'best_feature_disabled' in build_config_readiness(config)['blocker_codes']

def test_best_runtime_contract_is_supported_without_oauth_fields():
    from apps.integrations.production_settings import validate_runtime_config
    approved = validate_runtime_config({'platforms': {'best_ecapi': {'contract_approved': True}}})
    assert approved['platforms']['best_ecapi']['contract_approved'] is True
    with pytest.raises(DjangoValidationError):
        validate_runtime_config({'platforms': {'best_ecapi': {'auto_refresh_enabled': True}}})


def test_best_authorization_summary_uses_signature_credentials():
    from apps.integrations.serializers import WarehouseAuthorizationSerializer
    row = SimpleNamespace(provider='best_ecapi', token_id='', bootstrap_credential_id='',
        integration_config=SimpleNamespace(credential_id='synthetic-custody-ref'))
    serializer = WarehouseAuthorizationSerializer()
    assert serializer.get_oauth_token_available(row) is True
    assert serializer.get_token_configured(row) is True
    row.integration_config.credential_id = ''
    assert serializer.get_oauth_token_available(row) is False

def test_best_is_supported_by_warehouse_readonly_approval_gate():
    from apps.integrations.views import _require_marketplace_readiness_config
    config = SimpleNamespace(platform='best_ecapi')
    assert _require_marketplace_readiness_config(config, allow_warehouse=True) == ''


@pytest.mark.parametrize("platform,best_approved,jifeng_approved,blocked", [
    ("best_ecapi", True, False, False),
    ("best_ecapi", False, True, True),
    ("jifeng_wms", True, False, True),
    ("jifeng_wms", False, True, False),
])
def test_warehouse_contract_isolated_by_provider(ready_warehouse_config, monkeypatch, settings,
        platform, best_approved, jifeng_approved, blocked):
    config, _, _ = ready_warehouse_config
    config.platform = platform
    settings.BEST_ECAPI_ENABLED = True
    if platform == "best_ecapi":
        config.contract_version = "glink"
        config.platform_config = {"partner_id": "TEST-P", "customer_code": "TEST-C",
            "api_host": "https://edi-glink.800best.com/gateway/api/glink"}
        monkeypatch.setattr("apps.integrations.net_guard.get_allowed_hosts", lambda: {"edi-glink.800best.com"})
    approved = {"best_ecapi": best_approved, "jifeng_wms": jifeng_approved}
    lookup = lambda provider: {"contract_approved": approved[provider]}
    monkeypatch.setattr(gates, "get_runtime_platform_config", lookup)
    monkeypatch.setattr("apps.integrations.readiness_service.get_runtime_platform_config", lookup)
    row = build_config_readiness(config)
    assert ("platform_contract_not_enabled" in row["blocker_codes"]) is blocked
    assert row["contract_approved"] is (not blocked)
    assert row["can_approve_readonly"] is (not blocked)
    assert config.network_enabled is False and config.sync_read_enabled is False
