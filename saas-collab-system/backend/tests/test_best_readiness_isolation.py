from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from rest_framework.exceptions import PermissionDenied
from apps.integrations.best_glink import BestGlinkClient

@pytest.mark.parametrize("approved", [False, True])
def test_live_client_honors_its_own_contract_before_network(monkeypatch, settings, approved):
    settings.BEST_ECAPI_ENABLED = True
    for name in ["live_network_mode_enabled", "live_platform_security_approved", "approved_custody_configured"]:
        monkeypatch.setattr("apps.integrations.capability."+name, lambda: True)
    monkeypatch.setattr("apps.common.module_gate.is_module_enabled", lambda *args: True)
    monkeypatch.setattr("apps.integrations.production_settings.get_runtime_platform_config",
        lambda provider: {"contract_approved": approved if provider == "best_ecapi" else not approved})
    monkeypatch.setattr("apps.integrations.best_glink.gateway_for", lambda env: "https://example.test")
    config = SimpleNamespace(pk=4, tenant_id=1, platform="best_ecapi", environment="production",
        contract_version="glink", credential_id="synthetic-reference", credential_status="configured",
        sync_write_enabled=False, status="verified", network_enabled=True, sync_read_enabled=True)
    auth = SimpleNamespace(provider="best_ecapi", integration_config_id=4, tenant_id=1, status="active",
        warehouse=SimpleNamespace(tenant_id=1, status="active"), validation_status="verified", external_warehouse_code="TEST-W")
    http, custody = Mock(), Mock()
    client = BestGlinkClient(config, auth, http_client=http, custody=custody)
    if approved:
        client.preflight()
    else:
        with pytest.raises(PermissionDenied, match="百世接口合同"):
            client.preflight()
    http.request.assert_not_called()
    custody.retrieve_secret.assert_not_called()
