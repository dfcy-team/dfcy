from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
from django.utils import timezone

from apps.integrations.readonly_clients import ReadonlyConfigurationError
from tests.test_tiktok_readonly_approval import configured


@pytest.mark.parametrize('resource', ['sales_order', 'refund_return', 'platform_product'])
@pytest.mark.parametrize('legacy', [None, 'https://legacy.example.test'])
def test_request_uses_runtime_host_not_legacy_metadata(monkeypatch, resource, legacy):
    client = configured(monkeypatch, resource, {'contract_approved': True,
        'product_contract_approved': True, 'api_host': 'https://approved.example.test'})
    client.platform_config.update(app_key='FAKE_APP_KEY')
    if legacy:
        client.platform_config['api_host'] = legacy
    client.config.credential_id = 'FAKE_SECRET_REF'
    client.config.connect_timeout_seconds = client.config.read_timeout_seconds = 1
    client.authorization = SimpleNamespace(status='active', Status=SimpleNamespace(ACTIVE='active'),
        expires_at=timezone.now() + timedelta(hours=1), token_id='FAKE_TOKEN_REF')
    client.custody.retrieve_secret.return_value = 'FAKE_SECRET'
    client.custody.retrieve_access_token.return_value = 'FAKE_ACCESS'
    client.http.request.return_value.json.return_value = {'code': 0, 'data': {}}
    client._request('/test/read', method='POST', body={})
    assert urlsplit(client.http.request.call_args.args[1]).hostname == 'approved.example.test'


@pytest.mark.parametrize('host', ['', None, 'REPLACE_ME_HOST'])
def test_missing_runtime_host_fails_preflight_without_credentials_or_network(monkeypatch, host):
    client = configured(monkeypatch, 'sales_order', {'contract_approved': True, 'api_host': host})
    client.platform_config['api_host'] = 'https://legacy.example.test'
    with pytest.raises(ReadonlyConfigurationError, match='tiktok.api_host'):
        client.preflight()
    assert not client.custody.mock_calls
    client.http.request.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize('configuration_error', [True, False])
def test_configuration_failure_is_not_retried_but_transient_errors_still_are(configuration_error):
    from apps.integrations.models import SyncCheckpoint, SyncAlertIncident
    from apps.integrations.sync_services import run_sync_job
    from tests.test_phase2_sync_framework import create_sync_job, create_user
    from apps.tenants.models import Tenant

    tenant = Tenant.objects.create(name='Host test', code='host-test')
    job = create_sync_job(tenant, create_user(tenant, 'host-test-user'))
    adapter = Mock(execution_mode='mock')
    error = ReadonlyConfigurationError('缺少 tiktok.api_host，请检查生产环境配置。') if configuration_error else RuntimeError('temporary test outage')
    adapter.fetch_page.side_effect = error
    wait = Mock()
    run, created = run_sync_job(job, adapter=adapter, retry_wait=wait)
    assert created and run.status == 'failed'
    if configuration_error:
        assert run.error_code == 'SYNC_CONFIGURATION_MISSING'
        assert run.retry_count == 0
        assert adapter.fetch_page.call_count == 1
        wait.assert_not_called()
        assert 'ErrorDetail' not in run.masked_error_message
        assert 'tiktok.api_host' in run.masked_error_message
    else:
        assert run.error_code == 'MAX_RETRY_EXCEEDED'
        assert run.retry_count == job.max_retry_count
        assert wait.call_count == job.max_retry_count
    job.refresh_from_db()
    assert not job.lock_token and job.lock_expires_at is None
    assert not SyncCheckpoint.objects.filter(sync_job=job).exists()
    assert run.fetched_count == run.created_count == run.updated_count == 0
    assert SyncAlertIncident.objects.get(sync_job=job).last_error_code == run.error_code
