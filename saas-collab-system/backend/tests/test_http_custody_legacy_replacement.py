import json

import pytest
from django.test import override_settings

from apps.integrations.custody import HttpCustodyBackend
from apps.integrations.models import PlatformIntegrationConfig, authorization_service_write
from apps.integrations.net_guard import HttpResponse, PlatformHttpClient
from apps.tenants.models import Tenant
from tests.test_custody_service import service, _request
from tests.test_integration_credential_maintenance import _client_with_permissions


@pytest.mark.django_db
@pytest.mark.parametrize('failure', ['', 'unauthorized', 'unavailable', 'corrupt'])
def test_old_reference_can_only_be_replaced_after_confirmed_absence(service, monkeypatch, failure):
    from apps.integrations import credential_service, views

    tenant = Tenant.objects.create(name='Custody migration test', code='custody-migration-test')
    user, client = _client_with_permissions(tenant)
    callback = 'https://app.example.test/callback/shopee/'
    config = PlatformIntegrationConfig.objects.create(
        tenant=tenant, platform='shopee', environment='production', account_alias='Synthetic migration',
        platform_config={'api_type': 'marketplace', 'partner_id': '12345'}, callback_url=callback, created_by=user,
    )
    with authorization_service_write():
        config.credential_id = 'cred_old_store_only'
        config.token_id = 'tok_old_store_only'
        config.save(update_fields=['credential_id', 'token_id'])
    calls = []

    def transport(method, url, *, data=None, headers=None, **kwargs):
        path = url.removeprefix('https://custody.example.test')
        calls.append(path)
        if failure == 'unavailable':
            return HttpResponse(503, {}, '{}')
        if failure == 'corrupt':
            return HttpResponse(400, {}, '{"error_code":"CUSTODY_OPERATION_FAILED"}')
        response = _request(service, path, payload=json.loads(data),
                            token=None if failure == 'unauthorized' else 'sidecar-token')
        return HttpResponse(response['status'], {}, json.dumps(response['body']))

    custody = HttpCustodyBackend('https://custody.example.test', PlatformHttpClient(transport=transport, max_retries=0), 'sidecar-token')
    monkeypatch.setattr(views, 'get_custody_backend', lambda: custody)
    monkeypatch.setattr(credential_service, 'get_custody_backend', lambda: custody)
    with override_settings(LIVE_PLATFORM_ALLOWED_HOSTS=['custody.example.test'],
                           LIVE_SHOPEE_REDIRECT_URI=callback, LIVE_OAUTH_REDIRECT_ALLOWLIST=[callback]):
        response = client.post(
            f'/api/internal/integrations/configs/{config.id}/credentials/rotate/',
            {'version': config.config_version, 'reason': 'Synthetic old-store replacement',
             'credentials': {'partner_key': 'SYNTHETIC-NEW-PARTNER-KEY'}},
            format='json', HTTP_IDEMPOTENCY_KEY='synthetic-http-replacement-01',
        )
        config.refresh_from_db()
        assert 'SYNTHETIC-NEW-PARTNER-KEY' not in json.dumps(response.json())
        if failure:
            assert response.status_code >= 400
            assert config.credential_id == 'cred_old_store_only'
            assert '/tokens' not in calls and '/tokens/rotate' not in calls
            assert not list(service._store._store.path.glob('cred_*.json'))
        else:
            assert response.status_code == 200, response.json()
            assert config.credential_id != 'cred_old_store_only'
            assert calls[:2] == ['/secrets/resolve', '/tokens']
            assert custody.retrieve_secret(config.credential_id) == 'SYNTHETIC-NEW-PARTNER-KEY'
            assert all(b'SYNTHETIC-NEW-PARTNER-KEY' not in p.read_bytes()
                       for p in service._store._store.path.glob('cred_*.json'))
