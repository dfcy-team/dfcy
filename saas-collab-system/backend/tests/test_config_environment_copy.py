import pytest
from rest_framework.test import APIClient
from apps.integrations.models import PlatformIntegrationConfig, SyncJob, MarketplaceStoreAuthorization
from tests.test_store_api_merge_closure import _context, _grant

pytestmark = pytest.mark.django_db

def test_target_environment_is_new_unbound_configuration_and_source_is_unchanged():
    ctx = _context()
    user, source = ctx['user'], ctx['config']
    _grant(user, ('integrations.config.create','integrations.config.update','integrations.config.view'), role_code='integration_admin')
    client = APIClient(); client.force_authenticate(user=user)
    old = (source.environment, source.config_version, source.status, source.credential_id, source.callback_url)
    rejected = client.patch(f'/api/internal/integrations/configs/{source.pk}/',
        {'version':source.config_version,'environment':'production'}, format='json')
    assert rejected.status_code == 400
    response = client.post('/api/internal/integrations/workspace-configs/',
        {'account_alias':source.account_alias,'platform':'shopee','api_type':'marketplace','environment':'production','regions':['MY']},format='json')
    assert response.status_code == 201
    target = PlatformIntegrationConfig.objects.get(pk=response.data['data']['id'])
    assert target.pk != source.pk and target.environment == 'production'
    assert target.status == 'pending_review' and not target.network_enabled
    assert not target.credential_id and not target.token_id and not target.callback_url
    assert not SyncJob.objects.filter(integration_config=target).exists()
    assert not MarketplaceStoreAuthorization.objects.filter(integration_config=target).exists()
    source.refresh_from_db()
    assert (source.environment, source.config_version, source.status, source.credential_id, source.callback_url) == old
    assert all(job.integration_config_id == source.pk for job in ctx['jobs'])
    # The new environment must still pass callback validation before activation.
    blocked = client.patch(f'/api/internal/integrations/configs/{target.pk}/',
        {'version':target.config_version,'status':'verified'}, format='json')
    assert blocked.status_code == 400
