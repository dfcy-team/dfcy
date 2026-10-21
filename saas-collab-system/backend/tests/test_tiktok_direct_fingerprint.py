"""Independent app enablement must preserve existing TK mapping fingerprints."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from apps.integrations import oauth_state_service as states

SHOP = 'https://saas.example.test/integrations/tiktok/shop-callback'
ADS = 'https://saas.example.test/integrations/tiktok-ads/direct-callback'


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setattr(states, 'get_effective_runtime_version', lambda: None)
    monkeypatch.setattr(states, 'get_runtime_platform_config', lambda platform: {'contract_approved': True})
    return SimpleNamespace(platform='tiktok', config_version=1, credential_reference_version=1,
        credential_key_version='synthetic', credential_fingerprint='synthetic', credential_id='synthetic-ref',
        credential_status='configured', callback_url='https://legacy.example.test/callback',
        platform_config={'api_type': 'marketplace'}, environment='production', contract_version='synthetic',
        scopes=[], regions=['PH'], network_enabled=True, status='verified', deleted_at=None)


def original_digest(config):
    fields = ('config_version', 'credential_reference_version', 'credential_key_version',
        'credential_fingerprint', 'credential_id', 'credential_status', 'callback_url',
        'platform_config', 'environment', 'contract_version', 'scopes', 'regions',
        'network_enabled', 'status', 'deleted_at')
    values = {field: getattr(config, field) for field in fields}
    values.update(runtime_version=None, runtime_platform={'contract_approved': True})
    return hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()


@pytest.mark.parametrize('api_type', ['marketplace', 'advertising'])
def test_existing_config_keeps_the_pre_direct_digest(config, settings, api_type):
    config.platform_config['api_type'] = api_type
    expected = original_digest(config)
    for shop, ads in [('', ''), (SHOP, ADS), (SHOP + '/changed', ADS + '/changed')]:
        settings.TIKTOK_SHOP_DIRECT_CALLBACK_URL = shop
        settings.TIKTOK_ADS_DIRECT_CALLBACK_URL = ads
        assert states.configuration_digest(config) == expected


@pytest.mark.parametrize('api_type,callback,relevant,other', [
    ('marketplace', SHOP, 'TIKTOK_SHOP_DIRECT_CALLBACK_URL', 'TIKTOK_ADS_DIRECT_CALLBACK_URL'),
    ('advertising', ADS, 'TIKTOK_ADS_DIRECT_CALLBACK_URL', 'TIKTOK_SHOP_DIRECT_CALLBACK_URL'),
])
def test_direct_config_is_fenced_only_by_its_own_callback(config, settings, api_type, callback, relevant, other):
    config.platform_config['api_type'] = api_type
    config.callback_url = callback
    setattr(settings, relevant, callback)
    setattr(settings, other, '')
    baseline = states.configuration_digest(config)
    assert baseline != original_digest(config)
    setattr(settings, other, 'https://unrelated.example.test/changed')
    assert states.configuration_digest(config) == baseline
    setattr(settings, relevant, '')
    assert states.configuration_digest(config) != baseline
