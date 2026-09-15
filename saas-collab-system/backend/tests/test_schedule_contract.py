from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import pytest

from apps.integrations.models import SyncScheduleDispatch
from apps.integrations.scheduler import calculate_next_run_at, dispatch_due_jobs, preview_schedule
from apps.integrations.sync_services import run_sync_job
from apps.integrations.adapters import MockPlatformAdapter
from apps.integrations.tasks import run_readonly_sync_job
from apps.integrations.models import SyncRun
from tests.test_mock_sync_isolation import context

pytestmark = pytest.mark.django_db
NOW = datetime(2026, 9, 14, 0, 0, tzinfo=UTC)


def scheduled(job, **policy):
    job.schedule_type = 'interval'
    job.sync_scope = {'schedule': {'interval_minutes': 60, 'catch_up': 'skip', **policy}}
    job.next_run_at = NOW
    job.save()


def test_preview_disabled_job_has_three_times_without_saving(context):
    _, job = context
    scheduled(job)
    job.is_enabled = False
    assert preview_schedule(job, NOW) == [NOW + timedelta(hours=n) for n in (1, 2, 3)]
    assert calculate_next_run_at(job, NOW) is None


def test_daily_and_weekly_use_configured_timezone(context):
    _, job = context
    job.schedule_type = 'weekly'
    job.sync_scope = {'schedule': {'timezone': 'Asia/Shanghai', 'local_time': '09:00', 'weekdays': [1, 3]}}
    assert preview_schedule(job, NOW) == [NOW + timedelta(hours=1), NOW + timedelta(days=2, hours=1), NOW + timedelta(days=7, hours=1)]


def test_dispatch_only_once_and_does_not_accumulate_while_queued(context):
    _, job = context
    scheduled(job)
    queue = Mock()
    dispatch_due_jobs(queue, NOW)
    dispatch_due_jobs(queue, NOW)
    dispatch_due_jobs(queue, NOW + timedelta(hours=1))
    assert queue.call_count == 1
    assert SyncScheduleDispatch.objects.filter(status='queued').count() == 1


@pytest.mark.parametrize('policy,expected', [('skip', 0), ('run_once', 1)])
def test_missed_schedule_policy(context, policy, expected):
    _, job = context
    scheduled(job, catch_up=policy)
    queue = Mock()
    dispatch_due_jobs(queue, NOW + timedelta(hours=10, minutes=15))
    assert queue.call_count == expected
    job.refresh_from_db()
    assert job.next_run_at == NOW + timedelta(hours=11)


def test_pause_prevents_dispatch_and_bounded_catchup(context):
    _, job = context
    scheduled(job, pause_until=(NOW + timedelta(hours=5)).isoformat(), catch_up='run_once')
    queue = Mock()
    dispatch_due_jobs(queue, NOW + timedelta(hours=2))
    assert not queue.called
    dispatch_due_jobs(queue, NOW + timedelta(hours=5))
    assert queue.call_count == 1


def test_manual_execution_does_not_move_normal_schedule(context):
    _, job = context
    scheduled(job)
    with patch('apps.integrations.sync_services.timezone.now', return_value=NOW):
        run_sync_job(job, adapter=MockPlatformAdapter(), idempotency_key='manual-test')
    job.refresh_from_db()
    assert job.next_run_at == NOW


def test_scheduled_worker_links_run_and_ignores_redelivery(context):
    _, job = context
    scheduled(job)
    queue = Mock()
    dispatch_due_jobs(queue, NOW)
    key = queue.call_args.args[1]
    with patch('apps.integrations.tasks.run_sync_job', wraps=run_sync_job) as execute_mock:
        first = run_readonly_sync_job.run(job.id, key)
        second = run_readonly_sync_job.run(job.id, key)
    assert first['status'] == 'success' and not second['created']
    assert execute_mock.call_count == 1
    dispatch = SyncScheduleDispatch.objects.get()
    assert dispatch.sync_run.masked_log['trigger_type'] == 'scheduled'
    assert dispatch.sync_run.masked_log['scheduled_at'] == NOW.isoformat()
    assert dispatch.status == 'success'
    job.refresh_from_db()
    assert job.next_run_at == NOW + timedelta(hours=1)


def test_crash_before_lease_recovers_and_fences_late_worker(context):
    from rest_framework.exceptions import ValidationError
    _, job = context
    scheduled(job)
    dispatch = SyncScheduleDispatch.objects.create(tenant=job.tenant, sync_job=job,
        scheduled_at=NOW, status='queued')
    with patch('apps.integrations.tasks.timezone.now', return_value=NOW), patch('apps.integrations.tasks.validate_manual_sync_job', side_effect=SystemExit('worker terminated')):
        with pytest.raises(SystemExit):
            run_readonly_sync_job.run(job.id, f'scheduled:{job.id}:{dispatch.id}')
    job.refresh_from_db()
    assert job.status == 'idle' and not job.lock_token
    queue = Mock()
    dispatch_due_jobs(queue, NOW + timedelta(minutes=6))
    dispatch.refresh_from_db()
    assert dispatch.status == 'failed' and dispatch.finished_at is not None
    assert '启动超时' in dispatch.reason
    with pytest.raises(ValidationError, match='派发已终止'):
        run_sync_job(job, adapter=MockPlatformAdapter(), dispatch=dispatch)
    assert not SyncRun.objects.exists()
    dispatch_due_jobs(queue, NOW + timedelta(hours=1))
    assert queue.call_count == 1


def test_recovery_preserves_active_lease(context):
    _, job = context
    scheduled(job)
    dispatch = SyncScheduleDispatch.objects.create(tenant=job.tenant, sync_job=job,
        scheduled_at=NOW, started_at=NOW, status='running')
    job.lock_expires_at = NOW + timedelta(hours=1)
    job.save()
    queue = Mock()
    dispatch_due_jobs(queue, NOW + timedelta(minutes=6))
    dispatch.refresh_from_db()
    assert dispatch.status == 'running' and not queue.called


@pytest.mark.parametrize('resource,environment', [('sales_order','mock'), ('mock_record','production')])
def test_scheduled_worker_does_not_simulate_business_or_live_job(context, resource, environment):
    _, job = context
    scheduled(job)
    job.resource_type = resource
    job.save()
    job.integration_config.environment = environment
    job.integration_config.save()
    dispatch = SyncScheduleDispatch.objects.create(tenant=job.tenant, sync_job=job,
        scheduled_at=NOW, status='queued')
    from rest_framework.exceptions import ValidationError
    with pytest.raises(ValidationError):
        run_readonly_sync_job.run(job.id, f'scheduled:{job.id}:{dispatch.id}')
    assert not SyncRun.objects.exists()


def test_disable_after_enqueue_prevents_execution(context):
    _, job = context
    scheduled(job)
    queue = Mock()
    dispatch_due_jobs(queue, NOW)
    job.is_enabled = False
    job.save()
    with patch('apps.integrations.tasks.run_sync_job') as execute:
        result = run_readonly_sync_job.run(job.id, queue.call_args.args[1])
    assert result['status'] == 'skipped' and not execute.called
    assert not SyncRun.objects.exists()


def test_reentrant_dispatch_and_uncertain_queue_failure_do_not_repeat_slot(context):
    _, job = context
    scheduled(job)
    nested = Mock()
    def queue(*args):
        dispatch_due_jobs(nested, NOW)
        raise RuntimeError('queue unavailable')
    dispatch_due_jobs(queue, NOW)
    dispatch_due_jobs(nested, NOW)
    assert not nested.called
    assert SyncScheduleDispatch.objects.get().status == 'dispatch_failed'


def test_preview_and_save_keep_disabled_state_and_query_scope(context):
    client, job = context
    job.is_enabled = False
    job.sync_scope = {'query': {'mode': 'incremental', 'lookback_days': 30}}
    job.save()
    payload = {'schedule_type': 'weekly', 'local_time': '09:00', 'weekdays': [1, 3], 'timezone': 'Asia/Shanghai', 'catch_up': 'skip'}
    preview = client.post(f'/api/internal/integrations/sync-jobs/{job.id}/schedule-preview/', payload, format='json')
    assert preview.status_code == 200 and len(preview.data['data']['times']) == 3
    job.refresh_from_db()
    assert job.schedule_type == 'manual'
    saved = client.patch(f'/api/internal/integrations/sync-jobs/{job.id}/', payload, format='json')
    assert saved.status_code == 200
    job.refresh_from_db()
    assert not job.is_enabled and job.next_run_at is None
    assert job.sync_scope['query'] == {'mode': 'incremental', 'lookback_days': 30}
    assert not SyncRun.objects.exists() and not SyncScheduleDispatch.objects.exists()


@pytest.mark.parametrize('payload', [{'schedule_type': 'cron'}, {'timezone': 'Invalid/Zone'}, {'local_time': '27:90'}, {'pause_until': '2026-09-15T10:00:00'}, {'pause_until': '2026-99-15T10:00:00Z'}])
def test_invalid_schedule_is_rejected_without_save(context, payload):
    client, job = context
    response = client.post(f'/api/internal/integrations/sync-jobs/{job.id}/schedule-preview/', payload, format='json')
    assert response.status_code == 400
    job.refresh_from_db()
    assert job.schedule_type == 'manual'


def test_pause_only_full_form_save_preserves_due_slot(context):
    client, job = context
    scheduled(job)
    payload = {'schedule_type': 'interval', 'interval_minutes': 60, 'local_time': '02:00', 'weekdays': [1], 'timezone': 'Asia/Shanghai', 'catch_up': 'run_once', 'pause_until': (NOW + timedelta(hours=5)).isoformat()}
    response = client.patch(f'/api/internal/integrations/sync-jobs/{job.id}/', payload, format='json')
    assert response.status_code == 200
    job.refresh_from_db()
    assert job.next_run_at == NOW
