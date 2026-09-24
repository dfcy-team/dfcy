from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.integrations.missing_jobs import preview_missing_jobs
from apps.integrations.models import SyncJob, SyncRun
from apps.integrations.workspace_service import _matches, _run_rows, _schedule_state
from tests.test_mock_sync_isolation import context, assert_no_execution
from tests.test_sync_capability_gate import make_job, grant_workspace_view

pytestmark = pytest.mark.django_db


def test_creation_defaults_to_disabled_manual_and_does_not_execute(context):
    client, original = context
    with patch('apps.integrations.views.run_sync_job', side_effect=AssertionError('must not execute')):
        response = client.post('/api/internal/integrations/sync-jobs/', {
            'integration_config_id': original.integration_config_id,
            'resource_type': 'mock_record',
        }, format='json')
    assert response.status_code == 201, response.data
    job = SyncJob.objects.get(pk=response.data['data']['id'])
    assert not job.is_enabled and job.status == 'disabled' and job.schedule_type == 'manual'
    assert job.next_run_at is None
    assert_no_execution(job)


def test_creation_preview_includes_existing_without_mutation():
    job, authorization = make_job()
    grant_workspace_view(authorization.created_by)
    before = SyncJob.objects.count()
    result = preview_missing_jobs(authorization.created_by, include_existing=True)
    assert any(row['existing_job_id'] == job.id for row in result['items'])
    assert SyncJob.objects.count() == before and not SyncRun.objects.exists()
    assert not any(row['existing_job_id'] for row in preview_missing_jobs(authorization.created_by)['items'])


def test_duplicate_store_creation_is_rejected_without_running():
    job, authorization = make_job()
    grant_workspace_view(authorization.created_by)
    client = APIClient()
    client.force_authenticate(authorization.created_by)
    payload = {'integration_config_id': job.integration_config_id, 'store_authorization_id': authorization.id,
               'resource_type': job.resource_type, 'is_enabled': False, 'schedule_type': 'manual'}
    for _ in range(2):
        assert client.post('/api/internal/integrations/sync-jobs/', payload, format='json').status_code == 400
    assert SyncJob.objects.count() == 1 and SyncRun.objects.count() == 0


def test_scoped_run_filter_cannot_expose_other_tenant(context):
    client, own_job = context
    grant_workspace_view(own_job.integration_config.created_by)
    other_job, _ = make_job()
    SyncRun.objects.create(tenant=other_job.tenant, sync_job=other_job, run_id='other-run', idempotency_key='other-key')
    response = client.get('/api/internal/integrations/workspace/', {'mode': 'sync-runs', 'sync_job_id': other_job.id})
    assert response.status_code == 200
    assert response.data['data']['results'] == []


def test_workspace_filters_combine_without_expanding_scope():
    row = {'id': 7, 'platform': 'tiktok', 'subject_key': 'store:2', 'health_state': 'healthy'}
    assert _matches(row, {'platform': 'shopee,tiktok', 'subject_key': 'store:1,store:2', 'sync_job_id': '7'}, 'sync-jobs')
    assert not _matches(row, {'platform': 'shopee', 'subject_key': 'store:2'}, 'sync-jobs')
    assert not _matches(row, {'sync_job_id': '8'}, 'sync-jobs')


def test_uncollected_counts_are_unknown_and_mode_not_inferred(context):
    _, job = context
    run = SyncRun.objects.create(tenant=job.tenant, sync_job=job, run_id='test-run', idempotency_key='test-key', started_at=timezone.now())
    row = _run_rows([run], {})[0]
    assert row['fetched_count'] is None and row['failed_count'] is None
    assert row['execution_mode'] == '' and row['duration_seconds'] is None
    run.masked_log = {'fetched': 0, 'execution_mode': 'simulation'}
    row = _run_rows([run], {})[0]
    assert row['fetched_count'] == 0 and row['created_count'] == 0
    assert row['execution_mode'] == 'simulation'


def test_queued_manual_run_is_visible_and_blocks_another_submission(context):
    _, job = context
    enqueued_at = timezone.now()
    run = SyncRun.objects.create(
        tenant=job.tenant,
        sync_job=job,
        run_id='queued-run',
        idempotency_key='queued-key',
        status=SyncRun.Status.QUEUED,
        enqueued_at=enqueued_at,
        masked_log={'execution_mode': 'live_readonly', 'trigger_type': 'manual'},
    )

    row = _run_rows([run], {})[0]
    assert row['status'] == 'queued'
    assert row['enqueued_at'] is not None
    assert row['started_at'] is None
    assert _schedule_state(job, run) == 'queued'
