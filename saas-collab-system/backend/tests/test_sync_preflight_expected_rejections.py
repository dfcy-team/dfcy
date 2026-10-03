from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.integrations.models import SyncAlertIncident, SyncRun, SyncScheduleDispatch
from apps.integrations.sync_services import enqueue_sync_run
from apps.integrations.tasks import run_readonly_sync_job
from apps.integrations.warehouse_credential_service import require_verified_warehouse
from tests.test_mock_sync_isolation import context

pytestmark = pytest.mark.django_db


def test_scheduled_preflight_rejection_marks_dispatch_blocked(context):
    _client, job = context
    dispatch = SyncScheduleDispatch.objects.create(tenant=job.tenant, sync_job=job,
        scheduled_at=timezone.now(), status='queued')
    key = f'scheduled:{job.id}:{dispatch.id}'
    with patch('apps.integrations.tasks.validate_manual_sync_job', side_effect=ValidationError('preflight blocked')), \
            patch('apps.integrations.tasks.run_sync_job') as execute:
        result = run_readonly_sync_job.run(job.id, key)
    dispatch.refresh_from_db()
    assert result['status'] == 'blocked'
    assert dispatch.status == 'blocked'
    assert dispatch.finished_at is not None
    assert dispatch.status != 'success'
    execute.assert_not_called()


def test_non_validation_preflight_error_is_reraised(context):
    _client, job = context
    with patch('apps.integrations.tasks.validate_manual_sync_job', side_effect=RuntimeError('unexpected')), \
            pytest.raises(RuntimeError, match='unexpected'):
        run_readonly_sync_job.run(job.id, 'unexpected-preflight-key')


def test_execution_validation_error_is_reraised(context):
    _client, job = context
    with patch('apps.integrations.tasks.validate_manual_sync_job'), \
            patch('apps.integrations.tasks.run_sync_job', side_effect=ValidationError('execution validation')), \
            pytest.raises(ValidationError, match='execution validation'):
        run_readonly_sync_job.run(job.id, 'execution-validation-key')


@pytest.mark.parametrize('case,email,validation_status,last_verified_at', [
    ('missing_field', '', 'incomplete', timezone.now()),
    ('pending_validation', 'synthetic@example.invalid', 'pending', None),
])
def test_real_warehouse_verification_rejection_blocks_task(
        case, email, validation_status, last_verified_at, context):
    _client, job = context
    key = f'warehouse-preflight-{case}'
    queued, _created = enqueue_sync_run(job, key)
    record = SimpleNamespace(
        provider='jifeng_wms',
        email=email,
        bootstrap_credential_id='synthetic-bootstrap-ref',
        oauth_user_id='synthetic-user-id',
        token_id='synthetic-token-ref',
        external_warehouse_code='SYNTHETIC-WH-001',
        validation_status=validation_status,
        last_verified_at=last_verified_at,
        last_error_code='',
    )

    with patch('apps.integrations.tasks.validate_manual_sync_job',
               side_effect=lambda *_args, **_kwargs: require_verified_warehouse(record)), \
            patch('apps.integrations.tasks.run_sync_job') as execute:
        result = run_readonly_sync_job.run(job.id, key)

    queued.refresh_from_db()
    assert result == {'status': 'blocked', 'created': False, 'error_code': 'SYNC_PREFLIGHT_FAILED'}
    assert queued.status == SyncRun.Status.FAILED
    assert queued.finished_at is not None
    assert queued.error_code == 'SYNC_PREFLIGHT_FAILED'
    assert SyncAlertIncident.objects.filter(sync_job=job, last_error_code='SYNC_PREFLIGHT_FAILED').exists()
    assert 'synthetic' not in str(result)
    execute.assert_not_called()


def test_repeated_preflight_rejection_does_not_execute_again(context):
    _client, job = context
    key = 'repeated-preflight-key'
    enqueue_sync_run(job, key)
    with patch('apps.integrations.tasks.validate_manual_sync_job', side_effect=ValidationError('synthetic rejection')), \
            patch('apps.integrations.tasks.run_sync_job') as execute:
        result = run_readonly_sync_job.run(job.id, key)
        repeated = run_readonly_sync_job.run(job.id, key)
    assert result['status'] == 'blocked'
    assert repeated['status'] == 'not_executed'
    execute.assert_not_called()
