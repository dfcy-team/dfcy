from datetime import UTC, datetime, timedelta
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.test import override_settings

from apps.integrations.models import SyncScheduleDispatch
from apps.integrations import scheduler
from apps.integrations.scheduler import calculate_next_run_at, dispatch_due_jobs, preview_schedule
from apps.integrations.sync_services import run_sync_job
from apps.integrations.sync_services import _lease_heartbeat, _recover_expired_lease, _renew_lease
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


def test_interval_offset_edit_preview_missed_slot_and_midnight_rollover(context):
    from apps.integrations.scheduler import next_after_missed

    client, job = context
    now = datetime(2026, 9, 14, 15, 50, tzinfo=UTC)  # 23:50 Asia/Shanghai
    with patch('apps.integrations.scheduler.timezone.now', return_value=now):
        response = client.patch(f'/api/internal/integrations/sync-jobs/{job.id}/', {
            'schedule_type': 'interval', 'interval_minutes': 120, 'interval_offset_seconds': 4500,
        }, format='json')
    assert response.status_code == 200
    job.refresh_from_db()
    first = datetime(2026, 9, 14, 17, 15, tzinfo=UTC)  # next day 01:15 local
    assert job.next_run_at == first
    assert response.data['data']['interval_offset_seconds'] == 4500
    assert preview_schedule(job, now) == [
        first,
        datetime(2026, 9, 14, 19, 15, tzinfo=UTC),
        datetime(2026, 9, 14, 21, 15, tzinfo=UTC),
    ]
    assert next_after_missed(job, first, datetime(2026, 9, 14, 17, 30, tzinfo=UTC)) == datetime(2026, 9, 14, 19, 15, tzinfo=UTC)


def test_clearing_interval_offset_recalculates_using_legacy_interval(context):
    client, job = context
    now = datetime(2026, 9, 14, 15, 50, tzinfo=UTC)
    job.is_enabled = True
    job.schedule_type = 'interval'
    job.sync_scope = {'schedule': {'interval_minutes': 120, 'interval_offset_seconds': 4500}}
    job.next_run_at = datetime(2026, 9, 14, 17, 15, tzinfo=UTC)
    job.save()
    with patch('apps.integrations.scheduler.timezone.now', return_value=now):
        response = client.patch(f'/api/internal/integrations/sync-jobs/{job.id}/', {
            'interval_offset_seconds': None,
        }, format='json')
    assert response.status_code == 200
    job.refresh_from_db()
    assert 'interval_offset_seconds' not in job.sync_scope['schedule']
    assert job.next_run_at == now + timedelta(minutes=120)
    assert response.data['data']['interval_offset_seconds'] is None


@pytest.mark.parametrize('offset', [-1, 86400, True, 1.5, 'bad'])
def test_interval_offset_validation_rejects_invalid_values(context, offset):
    client, job = context
    response = client.post(f'/api/internal/integrations/sync-jobs/{job.id}/schedule-preview/', {
        'schedule_type': 'interval', 'interval_offset_seconds': offset,
    }, format='json')
    assert response.status_code == 400
    job.refresh_from_db()
    assert job.schedule_type == 'manual'


@pytest.mark.parametrize(('interval', 'offset'), [(60, 3600), (100, 0)])
def test_interval_offset_validation_rejects_non_daily_grid_or_offset_outside_period(context, interval, offset):
    client, job = context
    response = client.post(f'/api/internal/integrations/sync-jobs/{job.id}/schedule-preview/', {
        'schedule_type': 'interval', 'interval_minutes': interval, 'interval_offset_seconds': offset,
    }, format='json')
    assert response.status_code == 400
    job.refresh_from_db()
    assert job.schedule_type == 'manual'


def test_daily_interval_offset_skips_dst_nonexistent_wall_time():
    job = SimpleNamespace(
        is_enabled=True,
        schedule_type='interval',
        sync_scope={'schedule': {
            'timezone': 'America/New_York', 'interval_minutes': 1440,
            'interval_offset_seconds': 9000,
        }},
    )
    assert calculate_next_run_at(job, datetime(2026, 3, 7, 8, 0, tzinfo=UTC)) == datetime(2026, 3, 9, 6, 30, tzinfo=UTC)


def test_daily_and_weekly_use_configured_timezone(context):
    _, job = context
    job.schedule_type = 'weekly'
    job.sync_scope = {'schedule': {'timezone': 'Asia/Shanghai', 'local_time': '09:00', 'weekdays': [1, 3]}}
    assert preview_schedule(job, NOW) == [NOW + timedelta(hours=1), NOW + timedelta(days=2, hours=1), NOW + timedelta(days=7, hours=1)]


def test_daily_multiple_local_times_roll_across_midnight_and_skip_equal_time(context):
    _, job = context
    job.schedule_type = 'daily'
    job.sync_scope = {'schedule': {'timezone': 'Asia/Shanghai', 'local_times': ['22:00', '08:00', '16:00', '12:00']}}
    assert calculate_next_run_at(job, datetime(2026, 9, 14, 0, 0, tzinfo=UTC)) == datetime(2026, 9, 14, 4, 0, tzinfo=UTC)
    assert calculate_next_run_at(job, datetime(2026, 9, 14, 16, 0, tzinfo=UTC)) == datetime(2026, 9, 15, 0, 0, tzinfo=UTC)
    job.sync_scope['schedule']['local_times'] = ['08:00', '12:00', '16:00', '22:00']
    assert preview_schedule(job, datetime(2026, 9, 14, 0, 0, tzinfo=UTC)) == [
        datetime(2026, 9, 14, 4, 0, tzinfo=UTC),
        datetime(2026, 9, 14, 8, 0, tzinfo=UTC),
        datetime(2026, 9, 14, 14, 0, tzinfo=UTC),
    ]


@pytest.mark.parametrize('local_times', [['08:00', '08:00'], ['8:00'], ['24:00'], ['0800Z'], '08:00', list(f'{hour:02d}:00' for hour in range(9))])
def test_daily_local_times_validation_rejects_duplicate_malformed_or_too_many(context, local_times):
    client, job = context
    response = client.post(f'/api/internal/integrations/sync-jobs/{job.id}/schedule-preview/', {
        'schedule_type': 'daily', 'local_times': local_times,
    }, format='json')
    assert response.status_code == 400
    job.refresh_from_db()
    assert job.schedule_type == 'manual'


def test_daily_local_times_preview_save_readback_and_legacy_clear(context):
    client, job = context
    payload = {'schedule_type': 'daily', 'timezone': 'Asia/Shanghai', 'local_time': '09:30',
               'local_times': ['16:00', '08:00', '22:00', '12:00']}
    preview = client.post(f'/api/internal/integrations/sync-jobs/{job.id}/schedule-preview/', payload, format='json')
    assert preview.status_code == 200 and len(preview.data['data']['times']) == 3
    saved = client.patch(f'/api/internal/integrations/sync-jobs/{job.id}/', payload, format='json')
    assert saved.status_code == 200
    job.refresh_from_db()
    assert job.sync_scope['schedule']['local_times'] == ['08:00', '12:00', '16:00', '22:00']
    readback = client.get(f'/api/internal/integrations/sync-jobs/{job.id}/')
    assert readback.status_code == 200
    assert readback.data['data']['local_times'] == ['08:00', '12:00', '16:00', '22:00']
    empty = client.patch(f'/api/internal/integrations/sync-jobs/{job.id}/', {
        'local_times': [],
    }, format='json')
    assert empty.status_code == 200
    job.refresh_from_db()
    assert job.sync_scope['schedule']['local_times'] == []
    assert calculate_next_run_at(job, NOW) == datetime(2026, 9, 14, 1, 30, tzinfo=UTC)
    single = client.patch(f'/api/internal/integrations/sync-jobs/{job.id}/', {
        'schedule_type': 'daily', 'local_time': '09:30',
    }, format='json')
    assert single.status_code == 200
    job.refresh_from_db()
    assert 'local_times' not in job.sync_scope['schedule']
    assert calculate_next_run_at(job, NOW) == datetime(2026, 9, 14, 1, 30, tzinfo=UTC)


def test_local_times_only_update_recalculates_next_run_and_budget_only_preserves_it(context):
    client, job = context
    job.is_enabled = True
    job.schedule_type = 'daily'
    job.sync_scope = {'schedule': {'timezone': 'Asia/Shanghai', 'local_time': '02:00', 'local_times': ['02:00']}}
    job.next_run_at = NOW - timedelta(days=1)
    job.save()
    with patch('apps.integrations.scheduler.timezone.now', return_value=NOW):
        response = client.patch(f'/api/internal/integrations/sync-jobs/{job.id}/', {
            'local_times': ['08:00', '12:00', '16:00', '22:00'],
        }, format='json')
    assert response.status_code == 200
    job.refresh_from_db()
    assert job.next_run_at == datetime(2026, 9, 14, 4, 0, tzinfo=UTC)
    previous_next_run = job.next_run_at
    response = client.patch(f'/api/internal/integrations/sync-jobs/{job.id}/', {
        'execution_budget_seconds': 120,
    }, format='json')
    assert response.status_code == 200
    job.refresh_from_db()
    assert job.next_run_at == previous_next_run
    assert job.sync_scope['schedule']['local_times'] == ['08:00', '12:00', '16:00', '22:00']


def test_local_times_are_removed_when_switching_to_non_daily(context):
    client, job = context
    job.schedule_type = 'daily'
    job.sync_scope = {'schedule': {'local_time': '09:00', 'local_times': ['08:00', '12:00']}}
    job.save()
    response = client.patch(f'/api/internal/integrations/sync-jobs/{job.id}/', {
        'schedule_type': 'interval', 'interval_minutes': 60,
    }, format='json')
    assert response.status_code == 200
    job.refresh_from_db()
    assert 'local_times' not in job.sync_scope['schedule']


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


@pytest.mark.parametrize('policy,expected', [('skip', 0), ('run_once', 1)])
def test_daily_missed_multitime_slot_advances_to_next_time(context, policy, expected):
    _, job = context
    job.schedule_type = 'daily'
    job.sync_scope = {'schedule': {'timezone': 'Asia/Shanghai', 'local_times': ['08:00', '12:00', '16:00', '22:00'], 'catch_up': policy}}
    job.next_run_at = datetime(2026, 9, 14, 0, 0, tzinfo=UTC)
    job.save()
    queue = Mock()
    dispatch_due_jobs(queue, datetime(2026, 9, 14, 10, 0, tzinfo=UTC))
    assert queue.call_count == expected
    job.refresh_from_db()
    assert job.next_run_at == datetime(2026, 9, 14, 14, 0, tzinfo=UTC)


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
    def execute(job, **kwargs):
        return run_sync_job(job, adapter=MockPlatformAdapter(), **kwargs)
    with patch('apps.integrations.tasks.validate_manual_sync_job'), patch('apps.integrations.tasks.run_sync_job', side_effect=execute) as execute_mock:
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
    assert run_readonly_sync_job.run(job.id, f'scheduled:{job.id}:{dispatch.id}')['status'] == 'not_executed'
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


def _old_automatic_dispatch(job, now):
    job.schedule_type = 'interval'
    job.sync_scope = {'schedule': {'interval_minutes': 15, 'catch_up': 'skip'}}
    job.next_run_at = now + timedelta(hours=2)
    job.save()
    return SyncScheduleDispatch.objects.create(
        tenant=job.tenant, sync_job=job, scheduled_at=now - timedelta(hours=1),
        enqueued_at=now - timedelta(minutes=31), status='queued',
    )


def test_orphan_recovery_defaults_off_before_database_or_broker_access(monkeypatch):
    from apps.integrations.sync_delivery import read_delivery_snapshot

    monkeypatch.setattr(scheduler, "settings", SimpleNamespace())
    with patch.object(SyncScheduleDispatch.objects, "filter", side_effect=AssertionError("database query attempted")):
        with patch("apps.integrations.sync_delivery.read_delivery_snapshot", wraps=read_delivery_snapshot) as read:
            assert scheduler.recover_orphan_queued_dispatches(NOW, 20) == 0
    read.assert_not_called()


@pytest.mark.parametrize("flag", [False, None, 0, 1, "true", "false"])
def test_orphan_recovery_requires_explicit_boolean_true_before_database_or_broker_access(monkeypatch, flag):
    monkeypatch.setattr(scheduler, "settings", SimpleNamespace(SYNC_ORPHAN_QUEUED_DISPATCH_RECOVERY_ENABLED=flag))
    with patch.object(SyncScheduleDispatch.objects, "filter", side_effect=AssertionError("database query attempted")):
        with patch("apps.integrations.sync_delivery.read_delivery_snapshot") as read:
            assert scheduler.recover_orphan_queued_dispatches(NOW, 20) == 0
    read.assert_not_called()


@override_settings(SYNC_ORPHAN_QUEUED_DISPATCH_RECOVERY_ENABLED=False)
def test_periodic_maintenance_leaves_orphan_queued_dispatch_untouched_while_recovery_off(context):
    _, job = context
    dispatch = _old_automatic_dispatch(job, NOW)
    with patch("apps.integrations.sync_delivery.read_delivery_snapshot") as read:
        dispatch_due_jobs(Mock(), NOW)
    read.assert_not_called()
    dispatch.refresh_from_db()
    assert dispatch.status == "queued"


@override_settings(SYNC_ORPHAN_QUEUED_DISPATCH_RECOVERY_ENABLED=True)
def test_orphan_interval_queued_dispatch_recovers_and_fences_late_worker(context):
    from apps.integrations.sync_delivery import DeliverySnapshot
    _, job = context
    dispatch = _old_automatic_dispatch(job, NOW)
    snapshot = DeliverySnapshot(complete=True)
    with patch('apps.integrations.sync_delivery.read_delivery_snapshot', return_value=snapshot) as read:
        dispatch_due_jobs(Mock(), NOW)
    assert read.call_count == 2
    dispatch.refresh_from_db()
    job.refresh_from_db()
    assert dispatch.status == 'dispatch_failed'
    assert job.next_run_at == NOW + timedelta(hours=2)
    assert run_readonly_sync_job.run(job.pk, f'scheduled:{job.pk}:{dispatch.pk}')['status'] == 'not_executed'
    assert not SyncRun.objects.exists()


@pytest.mark.parametrize('snapshot_state', ['incomplete', 'present'])
@override_settings(SYNC_ORPHAN_QUEUED_DISPATCH_RECOVERY_ENABLED=True)
def test_orphan_recovery_requires_two_complete_absent_snapshots(context, snapshot_state):
    from apps.integrations.sync_delivery import DeliverySnapshot
    _, job = context
    dispatch = _old_automatic_dispatch(job, NOW)
    snapshot = DeliverySnapshot(complete=snapshot_state != 'incomplete')
    if snapshot_state == 'present':
        snapshot.fences.add((job.pk, f'scheduled:{job.pk}:{dispatch.pk}', 0))
    with patch('apps.integrations.sync_delivery.read_delivery_snapshot', return_value=snapshot):
        dispatch_due_jobs(Mock(), NOW)
    dispatch.refresh_from_db()
    assert dispatch.status == 'queued'


@pytest.mark.parametrize('second_state', ['present', 'unknown'])
@override_settings(SYNC_ORPHAN_QUEUED_DISPATCH_RECOVERY_ENABLED=True)
def test_orphan_recovery_requires_both_snapshots_absent(context, second_state):
    from apps.integrations.sync_delivery import DeliverySnapshot
    _, job = context
    dispatch = _old_automatic_dispatch(job, NOW)
    first = DeliverySnapshot(complete=True)
    second = DeliverySnapshot(complete=second_state != 'unknown')
    if second_state == 'present':
        second.fences.add((job.pk, f'scheduled:{job.pk}:{dispatch.pk}', 0))
    with patch('apps.integrations.sync_delivery.read_delivery_snapshot', side_effect=[first, second]):
        dispatch_due_jobs(Mock(), NOW)
    dispatch.refresh_from_db()
    assert dispatch.status == 'queued'



@override_settings(SYNC_ORPHAN_QUEUED_DISPATCH_RECOVERY_ENABLED=True)
def test_orphan_recovery_skips_associated_run_and_disabled_or_paused_jobs(context):
    from apps.integrations.sync_delivery import DeliverySnapshot
    _, job = context
    dispatch = _old_automatic_dispatch(job, NOW)
    SyncRun.objects.create(tenant=job.tenant, sync_job=job, run_id='linked-terminal',
                           idempotency_key=f'scheduled:{job.pk}:{dispatch.pk}', status='failed')
    snapshot = DeliverySnapshot(complete=True)
    with patch('apps.integrations.sync_delivery.read_delivery_snapshot', return_value=snapshot):
        dispatch_due_jobs(Mock(), NOW)
    dispatch.refresh_from_db()
    assert dispatch.status == 'queued'

    SyncRun.objects.filter(sync_job=job).delete()
    job.is_enabled = False
    job.save(update_fields=['is_enabled'])
    with patch('apps.integrations.sync_delivery.read_delivery_snapshot', return_value=snapshot):
        dispatch_due_jobs(Mock(), NOW)
    dispatch.refresh_from_db()
    assert dispatch.status == 'queued'


@override_settings(SYNC_ORPHAN_QUEUED_DISPATCH_RECOVERY_ENABLED=True)
def test_orphan_recovery_skips_any_active_run_and_started_dispatch(context):
    from apps.integrations.sync_delivery import DeliverySnapshot
    _, job = context
    dispatch = _old_automatic_dispatch(job, NOW)
    SyncRun.objects.create(tenant=job.tenant, sync_job=job, run_id='other-active',
                           idempotency_key='manual-active', status='running')
    snapshot = DeliverySnapshot(complete=True)
    with patch('apps.integrations.sync_delivery.read_delivery_snapshot', return_value=snapshot):
        dispatch_due_jobs(Mock(), NOW)
    dispatch.refresh_from_db()
    assert dispatch.status == 'queued'

    SyncRun.objects.filter(sync_job=job).delete()
    dispatch.started_at = NOW - timedelta(minutes=31)
    dispatch.save(update_fields=['started_at'])
    with patch('apps.integrations.sync_delivery.read_delivery_snapshot', return_value=snapshot):
        dispatch_due_jobs(Mock(), NOW)
    dispatch.refresh_from_db()
    assert dispatch.status == 'queued'


@override_settings(SYNC_ORPHAN_QUEUED_DISPATCH_RECOVERY_ENABLED=True)
def test_orphan_recovery_fails_closed_when_snapshot_reader_raises(context):
    _, job = context
    dispatch = _old_automatic_dispatch(job, NOW)
    with patch('apps.integrations.sync_delivery.read_delivery_snapshot', side_effect=RuntimeError('broker unavailable')):
        dispatch_due_jobs(Mock(), NOW)
    dispatch.refresh_from_db()
    assert dispatch.status == 'queued'


@override_settings(SYNC_ORPHAN_QUEUED_DISPATCH_RECOVERY_ENABLED=True)
def test_orphan_recovery_skips_recent_paused_and_locked_jobs(context):
    from apps.integrations.sync_delivery import DeliverySnapshot
    _, job = context
    snapshot = DeliverySnapshot(complete=True)

    recent = _old_automatic_dispatch(job, NOW)
    recent.enqueued_at = NOW - timedelta(minutes=29)
    recent.save(update_fields=['enqueued_at'])
    with patch('apps.integrations.sync_delivery.read_delivery_snapshot', return_value=snapshot) as read:
        dispatch_due_jobs(Mock(), NOW)
    recent.refresh_from_db()
    assert recent.status == 'queued' and not read.called

    paused = recent
    paused.enqueued_at = NOW - timedelta(minutes=31)
    paused.save(update_fields=['enqueued_at'])
    job.sync_scope = {'schedule': {'interval_minutes': 15, 'catch_up': 'skip',
                                   'pause_until': (NOW + timedelta(hours=1)).isoformat()}}
    job.save(update_fields=['sync_scope'])
    with patch('apps.integrations.sync_delivery.read_delivery_snapshot', return_value=snapshot):
        dispatch_due_jobs(Mock(), NOW)
    paused.refresh_from_db()
    assert paused.status == 'queued'

    job.sync_scope = {'schedule': {'interval_minutes': 15, 'catch_up': 'skip'}}
    job.lock_token = 'test-active-lock'
    job.lock_expires_at = NOW + timedelta(hours=1)
    job.save(update_fields=['sync_scope', 'lock_token', 'lock_expires_at'])
    with patch('apps.integrations.sync_delivery.read_delivery_snapshot', return_value=snapshot):
        dispatch_due_jobs(Mock(), NOW)
    paused.refresh_from_db()
    assert paused.status == 'queued'


@override_settings(SYNC_ORPHAN_QUEUED_DISPATCH_RECOVERY_ENABLED=True)
def test_orphan_recovery_then_run_once_uses_new_slot(context):
    from apps.integrations.sync_delivery import DeliverySnapshot
    _, job = context
    dispatch = _old_automatic_dispatch(job, NOW)
    job.sync_scope = {'schedule': {'interval_minutes': 15, 'catch_up': 'run_once'}}
    job.next_run_at = NOW - timedelta(minutes=20)
    job.save(update_fields=['sync_scope', 'next_run_at'])
    snapshot = DeliverySnapshot(complete=True)
    queue = Mock()
    with patch('apps.integrations.sync_delivery.read_delivery_snapshot', return_value=snapshot):
        dispatch_due_jobs(queue, NOW)
    dispatch.refresh_from_db()
    assert dispatch.status == 'dispatch_failed'
    assert queue.call_count == 1
    assert queue.call_args.args[1] != f'scheduled:{job.pk}:{dispatch.pk}'
    assert run_readonly_sync_job.run(job.pk, f'scheduled:{job.pk}:{dispatch.pk}')['status'] == 'not_executed'


@pytest.mark.parametrize('expired_lease,expected_error', [(True, 'LEASE_EXPIRED'), (False, 'RUN_TIMEOUT')])
@override_settings(SYNC_JOB_LEASE_SECONDS=900, SYNC_JOB_MAX_RUNTIME_SECONDS=1200)
def test_periodic_dispatch_recovers_zero_data_manual_run(context, expired_lease, expected_error):
    _, job = context
    run = SyncRun.objects.create(
        tenant=job.tenant, sync_job=job, run_id='abandoned-manual',
        idempotency_key='abandoned-manual', status='running', started_at=NOW,
    )
    job.status = 'running'
    job.last_run_at = NOW
    job.lock_token = run.run_id
    job.lock_expires_at = NOW + timedelta(minutes=5 if expired_lease else 25)
    job.save(update_fields=['status', 'last_run_at', 'lock_token', 'lock_expires_at'])

    result = dispatch_due_jobs(Mock(), NOW + timedelta(minutes=21))

    job.refresh_from_db()
    run.refresh_from_db()
    assert result['recovered'] == 1
    assert job.status == 'failed' and not job.lock_token and job.lock_expires_at is None
    assert run.status == 'failed' and run.error_code == expected_error
    assert run.fetched_count == run.created_count == 0
    assert run.finished_at is not None


@override_settings(SYNC_JOB_LEASE_SECONDS=900, SYNC_JOB_MAX_RUNTIME_SECONDS=1200)
def test_periodic_dispatch_preserves_active_manual_run(context):
    _, job = context
    run = SyncRun.objects.create(
        tenant=job.tenant, sync_job=job, run_id='active-manual',
        idempotency_key='active-manual', status='running', started_at=NOW,
    )
    job.status = 'running'
    job.last_run_at = NOW
    job.lock_token = run.run_id
    job.lock_expires_at = NOW + timedelta(minutes=25)
    job.save(update_fields=['status', 'last_run_at', 'lock_token', 'lock_expires_at'])

    result = dispatch_due_jobs(Mock(), NOW + timedelta(minutes=10))

    job.refresh_from_db()
    run.refresh_from_db()
    assert result['recovered'] == 0
    assert job.status == run.status == 'running'


@override_settings(SYNC_JOB_LEASE_SECONDS=3)
def test_execution_heartbeat_renews_active_lease():
    renewed = Event()
    with patch('apps.integrations.sync_services.connection') as db_connection, \
            patch('apps.integrations.sync_services.close_old_connections'), \
            patch('apps.integrations.sync_services.connections'), \
            patch('apps.integrations.sync_services._renew_lease', side_effect=lambda *_: renewed.set()) as renew:
        db_connection.vendor = 'postgresql'
        with _lease_heartbeat(Mock(), Mock()):
            assert renewed.wait(2)
    renew.assert_called()


def test_expired_lease_cannot_be_renewed(context):
    from django.utils import timezone
    from rest_framework.exceptions import ValidationError
    _, job = context
    run = SyncRun.objects.create(tenant=job.tenant, sync_job=job,
        run_id='expired-renewal', idempotency_key='expired-renewal', status=SyncRun.Status.RUNNING)
    job.status = 'running'
    job.lock_token = run.run_id
    job.lock_expires_at = timezone.now() - timedelta(seconds=1)
    job.save(update_fields=['status', 'lock_token', 'lock_expires_at'])
    with pytest.raises(ValidationError, match='lease was lost'):
        _renew_lease(job, run)
    job.refresh_from_db()
    assert job.lock_expires_at < timezone.now()


def test_expired_worker_cannot_resume_writing_after_recovery(context):
    from django.utils import timezone
    from rest_framework.exceptions import ValidationError
    _, job = context

    class LostLeaseAdapter(MockPlatformAdapter):
        def fetch_page(self, sync_job, cursor_value=None):
            _recover_expired_lease(sync_job, timezone.now())
            return super().fetch_page(sync_job, cursor_value)

    with pytest.raises(ValidationError, match='lease was lost'):
        run_sync_job(job, adapter=LostLeaseAdapter(), idempotency_key='lost-lease')
    run = SyncRun.objects.get(sync_job=job)
    job.refresh_from_db()
    assert run.status == SyncRun.Status.FAILED and run.error_code == 'LEASE_EXPIRED'
    assert job.status == 'failed' and not job.lock_token


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


def test_incremental_product_preview_and_save_use_collection_range(context):
    client, job = context
    job.resource_type = 'platform_product'
    job.sync_scope = {}
    job.save()
    payload = {
        'schedule_type': 'manual',
        'product_full_sync': False,
        'query_mode': 'incremental',
        'lookback_days': 7,
    }
    preview = client.post(f'/api/internal/integrations/sync-jobs/{job.id}/schedule-preview/', payload, format='json')
    assert preview.status_code == 200
    assert preview.data['data']['collection_range']['time_from'] < preview.data['data']['collection_range']['time_to']
    saved = client.patch(f'/api/internal/integrations/sync-jobs/{job.id}/', payload, format='json')
    assert saved.status_code == 200
    job.refresh_from_db()
    assert job.sync_scope['product_full_sync'] is False
    assert job.sync_scope['query'] == {'mode': 'incremental', 'lookback_days': 7}


def test_full_product_preview_has_no_collection_range(context):
    client, job = context
    job.resource_type = 'platform_product'
    job.save()
    preview = client.post(
        f'/api/internal/integrations/sync-jobs/{job.id}/schedule-preview/',
        {'schedule_type': 'manual', 'product_full_sync': True},
        format='json',
    )
    assert preview.status_code == 200
    assert preview.data['data']['collection_range'] is None


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
