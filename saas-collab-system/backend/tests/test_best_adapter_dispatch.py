"""Exercise the selected adapter boundary without external business requests."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.integrations.adapters import BestInboundAdapter, get_adapter_for_config
from apps.integrations.best_glink import BestGlinkClient
from apps.integrations.models import PlatformIntegrationConfig, SyncJob


def test_selected_best_inbound_adapter_forwards_frozen_scope_and_cursor():
    config = PlatformIntegrationConfig(platform='best_ecapi', environment='production', platform_config={})
    adapter = get_adapter_for_config(config, SyncJob.ResourceType.INBOUND)
    assert isinstance(adapter, BestInboundAdapter)
    adapter.scope = {'time_from': 100, 'time_to': 200}
    client = Mock(spec=BestGlinkClient)
    page = {'records': [{'external_inbound_id': 'ASN-1'}], 'next_cursor': '3'}
    client.fetch_inbound.return_value = page
    adapter.client = client
    result = adapter.fetch_page(SimpleNamespace(resource_type=SyncJob.ResourceType.INBOUND), '2')
    assert result is page
    client.fetch_inbound.assert_called_once_with('2', {'time_from': 100, 'time_to': 200})
    with pytest.raises(ValidationError):
        adapter.fetch_page(SimpleNamespace(resource_type=SyncJob.ResourceType.INVENTORY_SNAPSHOT))
    assert client.fetch_inbound.call_count == 1


def test_debug_blocks_best_client_before_credentials_or_network(settings):
    settings.DEBUG = True
    settings.BEST_ECAPI_ENABLED = True
    config = SimpleNamespace(platform_config={'partner_id': 'TEST-P', 'customer_code': 'TEST-C'})
    authorization = SimpleNamespace(external_warehouse_code='TEST-W', warehouse=SimpleNamespace(country_code='MY'))
    http, custody = Mock(), Mock()
    client = BestGlinkClient(config, authorization, http_client=http, custody=custody)
    with pytest.raises(PermissionDenied, match='DEBUG'):
        client.query('GLINK_QUERY_WAREHOUSE_NOTIFY', {})
    http.request.assert_not_called()
    custody.retrieve_secret.assert_not_called()
