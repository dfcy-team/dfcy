from unittest.mock import patch

import pytest

from apps.integrations.adapters import MockPlatformAdapter
from apps.integrations.models import SyncCheckpoint, SyncCursor, SyncRun
from apps.tenants.models import Tenant
from tests.test_phase2_sync_framework import (
    authenticated_client, create_sync_job, create_user, grant_integration_access,
)


pytestmark = pytest.mark.django_db


@pytest.fixture
def context():
    tenant = Tenant.objects.create(name='Mock isolation', code='mock-isolation')
    user = create_user(tenant, 'mock-isolation-user')
    grant_integration_access(user)
    return authenticated_client(user), create_sync_job(tenant, user)


def run(client, job):
    return client.post(f'/api/internal/integrations/sync-jobs/{job.pk}/run-mock/',
                       {'idempotency_key': 'FAKE_SIMULATION_KEY'}, format='json')


def assert_no_execution(job):
    assert not SyncRun.objects.filter(sync_job=job).exists()
    assert not SyncCursor.objects.filter(sync_job=job).exists()
    assert not SyncCheckpoint.objects.filter(sync_job=job).exists()


@pytest.mark.parametrize('status,enabled', [('idle', False), ('disabled', True)])
def test_disabled_mock_is_rejected_before_adapter_selection(context, status, enabled):
    client, job = context
    job.status, job.is_enabled = status, enabled
    job.save()
    with patch('apps.integrations.sync_services.get_adapter_for_config', return_value=MockPlatformAdapter()) as select:
        response = run(client, job)
    assert response.status_code == 400
    assert '任务已停用' in str(response.data)
    select.assert_not_called()
    assert_no_execution(job)


@pytest.mark.parametrize('environment', ['pilot', 'production', 'sandbox'])
def test_real_or_placeholder_config_cannot_run_mock_or_advance_cursor(context, environment):
    client, job = context
    job.integration_config.environment = environment
    job.integration_config.save(update_fields=['environment'])
    with patch('apps.integrations.sync_services.get_adapter_for_config', return_value=MockPlatformAdapter()) as select:
        response = run(client, job)
    assert response.status_code == 400
    assert '独立 Mock 任务' in str(response.data)
    select.assert_not_called()
    assert_no_execution(job)


def test_business_resource_cannot_receive_mock_checkpoint(context):
    client, job = context
    job.resource_type = 'sales_order'
    job.save(update_fields=['resource_type'])
    with patch('apps.integrations.sync_services.get_adapter_for_config', return_value=MockPlatformAdapter()) as select:
        response = run(client, job)
    assert response.status_code == 400
    select.assert_not_called()
    assert_no_execution(job)


def test_enabled_mock_uses_explicit_mock_adapter_and_remains_idempotent(context):
    client, job = context
    with patch('apps.integrations.sync_services.get_adapter_for_config', side_effect=AssertionError('Must not select live adapter')):
        first, second = run(client, job), run(client, job)
    assert first.status_code == second.status_code == 200
    assert first.data['data']['created'] is True
    assert second.data['data']['created'] is False
    assert SyncRun.objects.filter(sync_job=job).count() == 1
    assert SyncCursor.objects.get(sync_job=job).cursor_value == 'done'
