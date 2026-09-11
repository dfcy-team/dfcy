from types import SimpleNamespace
from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.integrations.warehouse_authorization_service import resolve_external_warehouse_identity
from apps.integrations.warehouse_credential_service import require_verified_warehouse


@pytest.mark.parametrize("environment", ["pilot", "production"])
def test_external_code_is_optional_for_binding_not_inventory_sync(environment):
    config = SimpleNamespace(environment=environment, platform_config={"contract_approved": True})
    code, region = resolve_external_warehouse_identity(warehouse=SimpleNamespace(country_code="TH"),
        integration_config=config, provider="jifeng_wms", external_warehouse_code="")
    assert (code, region) == ("", "TH")
    record = SimpleNamespace(provider="jifeng_wms", email="fake@example.test", bootstrap_credential_id="FAKE",
        oauth_user_id="FAKE", token_id="FAKE", external_warehouse_code="", validation_status="verified")
    with pytest.raises(ValidationError, match="外部仓库编码"):
        require_verified_warehouse(record)


def test_explicit_empty_code_does_not_inherit_shared_config_identity():
    config = SimpleNamespace(environment="production", platform_config={"warehouse_code": "OTHER-WAREHOUSE"})
    assert resolve_external_warehouse_identity(warehouse=SimpleNamespace(country_code="TH"),
        integration_config=config, provider="jifeng_wms", external_warehouse_code="")[0] == ""


def test_empty_binding_cannot_read_shared_config_warehouse(monkeypatch):
    from apps.integrations.readonly_clients import JifengWmsReadonlyClient
    monkeypatch.setattr(JifengWmsReadonlyClient, "preflight", lambda self: None)
    config = SimpleNamespace(platform_config={"api_host": "https://example.test", "client_id": "FAKE",
        "site_code": "TH", "warehouse_code": "OTHER-WAREHOUSE"})
    binding = SimpleNamespace(Status=SimpleNamespace(ACTIVE="active"), status="active",
        email="fake@example.test", oauth_user_id="FAKE", oauth_expires_at=timezone.now() + timedelta(hours=1),
        external_warehouse_code="")
    custody, http = Mock(), Mock()
    client = JifengWmsReadonlyClient(config, binding, http_client=http, custody=custody)
    with pytest.raises(ValidationError, match="external_warehouse_code"):
        client.fetch_inventory(None, {})
    http.request.assert_not_called()
    custody.retrieve_secret.assert_not_called()
