import pytest
from rest_framework.test import APIClient
from apps.accounts.models import CustomUser
from apps.tenants.models import Tenant
from apps.masterdata.models import PlatformMaster
from apps.integrations.models import PlatformIntegrationConfig, WarehouseAuthorization, SyncJob

pytestmark = pytest.mark.django_db


def context(number=1, selected=True):
    tenant = Tenant.objects.create(code=f'best-create-{number}', name='BEST create')
    user = CustomUser.objects.create_user(username=f'best-create-{number}', tenant=tenant, user_type='internal', is_superuser=True)
    PlatformMaster.objects.create(tenant=tenant, code='BEST', name='百世', platform_type='warehouse_third_party',
        warehouse_connector_state='selected' if selected else 'pending', warehouse_connector_key='best_ecapi' if selected else '')
    client = APIClient(); client.force_authenticate(user)
    return client, tenant


def payload():
    return {'account_alias': 'BEST test', 'platform': 'best_ecapi', 'api_type': 'inventory',
        'environment': 'production', 'regions': ['MY']}


def test_best_create_is_tenant_scoped_and_does_not_enable_api(settings):
    settings.BEST_ECAPI_ENABLED = False
    for number in (1, 2):
        client, tenant = context(number)
        response = client.post('/api/internal/integrations/workspace-configs/', payload(), format='json')
        assert response.status_code == 201, response.data
        config = PlatformIntegrationConfig.objects.get(pk=response.data['data']['id'])
        assert config.tenant_id == tenant.pk
        assert config.platform_config == {'api_type': 'inventory'}
        assert config.status == 'pending_review'
        assert not any((config.network_enabled, config.sync_read_enabled, config.sync_write_enabled, config.credential_id, config.token_id))
        assert not WarehouseAuthorization.objects.filter(integration_config=config).exists()
        assert not SyncJob.objects.filter(integration_config=config).exists()


def test_creation_rejects_credentials_and_public_access_parameters():
    client, _ = context()
    for field in ('best_config', 'credentials'):
        data = {**payload(), field: {'partner_id': 'TEST_PARTNER'}}
        response = client.post('/api/internal/integrations/workspace-configs/', data, format='json')
        assert response.status_code == 400
    assert not PlatformIntegrationConfig.objects.exists()


def test_other_tenant_selection_does_not_enable_unconfirmed_best():
    context(1)
    client, _ = context(2, selected=False)
    response = client.post('/api/internal/integrations/workspace-configs/', payload(), format='json')
    assert response.status_code == 400
    assert not PlatformIntegrationConfig.objects.exists()
