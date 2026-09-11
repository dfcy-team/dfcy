from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from kombu.exceptions import OperationalError

from apps.integrations.models import SyncRun
from apps.permissions.models import Permission, Role
from tests.test_mock_sync_isolation import context, assert_no_execution

pytestmark = pytest.mark.django_db


def grant_live(job):
    permission, _ = Permission.objects.get_or_create(code='integrations.run_live_readonly',
        defaults={'name': 'Live readonly', 'module': 'integrations', 'action': 'run_live_readonly'})
    Role.objects.get(tenant=job.tenant).permissions.add(permission)


@pytest.mark.parametrize('enabled', ['true', 1, None])
def test_toggle_rejects_non_boolean_without_changing_job(context, enabled):
    client, job = context
    response = client.post(f'/api/internal/integrations/sync-jobs/{job.id}/toggle/', {'enabled': enabled}, format='json')
    assert response.status_code == 400
    job.refresh_from_db()
    assert job.is_enabled


def test_enable_only_prepares_job_without_running_or_scheduling(context):
    client, job = context
    job.is_enabled = False
    job.status = 'disabled'
    job.save()
    response = client.post(f'/api/internal/integrations/sync-jobs/{job.id}/toggle/', {'enabled': True}, format='json')
    assert response.status_code == 200
    job.refresh_from_db()
    assert job.is_enabled and job.status == 'idle' and job.next_run_at is None
    assert_no_execution(job)


def test_failed_enable_preflight_keeps_task_disabled(context):
    client, job = context
    job.is_enabled = False
    job.save()
    with patch('apps.integrations.sync_services.get_adapter_for_config') as choose:
        choose.return_value.execution_mode = 'live_readonly'
        choose.return_value.validate_configuration.side_effect = ValidationError('只读配置未批准')
        response = client.post(f'/api/internal/integrations/sync-jobs/{job.id}/toggle/', {'enabled': True}, format='json')
    assert response.status_code == 400
    job.refresh_from_db()
    assert not job.is_enabled
    assert_no_execution(job)


@pytest.mark.parametrize('status,enabled', [('idle', False), ('disabled', True), ('running', True)])
def test_live_run_rejects_disabled_or_busy_before_queue(context, status, enabled):
    client, job = context
    grant_live(job)
    job.status, job.is_enabled = status, enabled
    job.save()
    with patch('apps.integrations.views.run_readonly_sync_job.delay') as queue:
        response = client.post(f'/api/internal/integrations/sync-jobs/{job.id}/run/', {}, format='json')
    assert response.status_code == 400
    queue.assert_not_called()
    assert_no_execution(job)


def test_live_run_requires_distinct_permission(context):
    client, job = context
    with patch('apps.integrations.views.run_readonly_sync_job.delay') as queue:
        response = client.post(f'/api/internal/integrations/sync-jobs/{job.id}/run/', {}, format='json')
    assert response.status_code == 403
    queue.assert_not_called()


def test_live_endpoint_cannot_enqueue_mock(context):
    client, job = context
    grant_live(job)
    with patch('apps.integrations.views.run_readonly_sync_job.delay') as queue:
        response = client.post(f'/api/internal/integrations/sync-jobs/{job.id}/run/', {}, format='json')
    assert response.status_code == 400
    queue.assert_not_called()


def test_live_request_is_only_accepted_after_preflight(context):
    client, job = context
    grant_live(job)
    adapter = Mock(execution_mode='live_readonly')
    with patch('apps.integrations.sync_services.get_adapter_for_config', return_value=adapter), \
            patch('apps.integrations.views.run_readonly_sync_job.delay', return_value=SimpleNamespace(id='fake-task')) as queue:
        response = client.post(f'/api/internal/integrations/sync-jobs/{job.id}/run/', {'idempotency_key': 'fake-key'}, format='json')
    assert response.status_code == 202
    assert response.data['data']['accepted'] is True
    adapter.validate_configuration.assert_called_once()
    queue.assert_called_once_with(job.id, 'fake-key')
    assert not SyncRun.objects.filter(sync_job=job).exists()


def test_preflight_failure_never_enqueues(context):
    client, job = context
    grant_live(job)
    adapter = Mock(execution_mode='live_readonly')
    adapter.validate_configuration.side_effect = ValidationError('只读配置未批准')
    with patch('apps.integrations.sync_services.get_adapter_for_config', return_value=adapter), \
            patch('apps.integrations.views.run_readonly_sync_job.delay') as queue:
        response = client.post(f'/api/internal/integrations/sync-jobs/{job.id}/run/', {}, format='json')
    assert response.status_code == 400
    queue.assert_not_called()


def test_expired_authorization_is_rejected_before_adapter_preflight():
    from tests.test_sync_capability_gate import make_job
    from apps.integrations.sync_services import validate_manual_sync_job
    job, authorization = make_job()
    authorization.expires_at = timezone.now() - timedelta(seconds=1)
    job.store_authorization = authorization
    adapter = Mock(execution_mode='live_readonly')
    with patch('apps.integrations.sync_services.get_adapter_for_config', return_value=adapter):
        with pytest.raises(ValidationError, match='主体授权已过期'):
            validate_manual_sync_job(job, live_only=True)
    adapter.validate_configuration.assert_not_called()


def test_queue_error_does_not_expose_connection_details_or_claim_success(context):
    client, job = context
    grant_live(job)
    with patch('apps.integrations.sync_services.get_adapter_for_config', return_value=Mock(execution_mode='live_readonly')), \
            patch('apps.integrations.views.run_readonly_sync_job.delay', side_effect=OperationalError('FAKE_PRIVATE_CONNECTION_DETAIL')):
        response = client.post(f'/api/internal/integrations/sync-jobs/{job.id}/run/', {}, format='json')
    assert response.status_code == 400
    assert '尚不能确认' in str(response.data)
    assert 'FAKE_PRIVATE_CONNECTION_DETAIL' not in str(response.data)
    assert_no_execution(job)


def test_running_job_cannot_be_disabled(context):
    client, job = context
    job.status = 'running'
    job.save()
    response = client.post(f'/api/internal/integrations/sync-jobs/{job.id}/disable/', {}, format='json')
    assert response.status_code == 400
    job.refresh_from_db()
    assert job.is_enabled and job.status == 'running'
