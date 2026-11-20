import json
import pytest
from apps.integrations.custody import reset_custody_backend_cache, get_custody_backend
from apps.integrations.models import PlatformIntegrationConfig, IntegrationAuditLog
from tests.test_best_config_create import context, payload

pytestmark = pytest.mark.django_db


@pytest.fixture
def draft(settings, tmp_path):
    settings.DEBUG = True
    settings.PLATFORM_NETWORK_MODE = ""
    settings.LIVE_CUSTODY_BACKEND = 'file'
    settings.CREDENTIAL_CUSTODY_PATH = str(tmp_path / 'custody')
    settings.BEST_ECAPI_ENABLED = False
    reset_custody_backend_cache()
    client, tenant = context()
    response = client.post('/api/internal/integrations/workspace-configs/', payload(), format='json')
    assert response.status_code == 201
    config = PlatformIntegrationConfig.objects.get(pk=response.data['data']['id'])
    yield client, config
    reset_custody_backend_cache()


def credentials():
    return {'partner_id': 'TEST_PARTNER', 'partner_key': 'FAKE_TEST_KEY', 'customer_code': 'TEST_CUSTOMER',
        'api_host': 'https://edi-glink.800best.com/gateway/api/glink', 'site_code': 'MY'}


def save(client, config, values, key='best-maintenance-first'):
    return client.post(f'/api/internal/integrations/configs/{config.pk}/credentials/rotate/',
        {'version': config.config_version, 'reason': 'test BEST maintenance', 'credentials': values},
        format='json', HTTP_IDEMPOTENCY_KEY=key)


def test_create_then_maintain_custody_without_enabling_network(draft):
    client, config = draft
    response = save(client, config, credentials())
    assert response.status_code == 200, response.data
    assert 'FAKE_TEST_KEY' not in json.dumps(response.data)
    assert 'FAKE_TEST_KEY' not in json.dumps(list(IntegrationAuditLog.objects.values('masked_detail')))
    config.refresh_from_db()
    assert config.platform_config == {'api_type': 'inventory', **{k:v for k,v in credentials().items() if k != 'partner_key'}}
    assert get_custody_backend().retrieve_secret(config.credential_id) == 'FAKE_TEST_KEY'
    assert not config.network_enabled and not config.sync_read_enabled and not config.sync_write_enabled
    response = save(client, config, {'customer_code': 'UPDATED_CUSTOMER'}, 'best-maintenance-update')
    assert response.status_code == 200, response.data
    config.refresh_from_db()
    assert config.platform_config['customer_code'] == 'UPDATED_CUSTOMER'
    assert get_custody_backend().retrieve_secret(config.credential_id) == 'FAKE_TEST_KEY'
    assert save(client, config, {'partner_id':'CHANGED_PARTNER'}, 'best-maintenance-identity').status_code == 400


@pytest.mark.parametrize('change,field', [({'partner_key':''},'partner_key'),
    ({'api_host':'http://example.com/ecapi/api/process'},'api_host'), ({'site_code':'PH'},'site_code')])
def test_bad_credentials_do_not_write_custody(draft, change, field):
    client, config = draft
    values = {**credentials(), **change}
    if not values['partner_key']: del values['partner_key']
    response = save(client, config, values)
    assert response.status_code == 400
    assert field in str(response.data['data'])
    config.refresh_from_db()
    assert not config.credential_id


def test_other_tenant_cannot_maintain_config(draft):
    _, config = draft
    other, _ = context(2)
    assert save(other, config, credentials()).status_code == 404
