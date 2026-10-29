from unittest.mock import patch
import pytest
from rest_framework.exceptions import ValidationError
from apps.integrations.history_sync import create_history_batch
from apps.integrations.models import HistorySyncBatch
from tests.test_history_sync_batches import ctx, payload
from tests import test_history_sync_batches as existing
from tests.test_sync_runtime_budget import empty_delivery_broker
from tests.test_phase2_sync_framework import authenticated_client

pytestmark = pytest.mark.django_db

@pytest.fixture
def tkctx(ctx):
    user, job, role = ctx
    job.integration_config.platform = 'tiktok'
    job.integration_config.save(update_fields=['platform'])
    return user, job, role

@pytest.mark.parametrize('resource', ['sales_order','refund_return','settlement_bill'])
def test_tiktok_contiguous_bounded_frozen_scope_and_idempotency(tkctx, resource):
    user,job,_=tkctx
    job.resource_type=resource;job.save(update_fields=['resource_type'])
    original=job.sync_scope.copy()
    data=payload([job]);data.update(start_date='2026-09-01',end_date='2026-09-15')
    with patch('apps.integrations.history_sync.validate_manual_sync_job'):
        batch=create_history_batch(user,data)
        assert create_history_batch(user,data).pk==batch.pk
    segs=list(batch.segments.order_by('sequence'))
    assert len(segs)==3
    assert all(s.scope['page_size']==50 and s.scope['time_basis']=='created' for s in segs)
    assert sum(s.scope['time_to']-s.scope['time_from']+1 for s in segs)==15*86400
    assert all(s.scope['time_to']-s.scope['time_from']+1<=7*86400 for s in segs)
    assert all(b.scope['time_from']==a.scope['time_to']+1 for a,b in zip(segs,segs[1:]))
    job.refresh_from_db();assert job.sync_scope==original
    with pytest.raises(ValidationError):
        create_history_batch(user,{**data,'idempotency_key':'different'})

@pytest.mark.parametrize('resource',['advertising_report','platform_product','affiliate_order'])
def test_tiktok_unsupported_resource_atomic(tkctx,resource):
    user,job,_=tkctx;job.resource_type=resource;job.save(update_fields=['resource_type'])
    with patch('apps.integrations.history_sync.validate_manual_sync_job'),pytest.raises(ValidationError):
        create_history_batch(user,payload([job]))
    assert not HistorySyncBatch.objects.exists()

def test_tiktok_api_capability_and_job_option(tkctx):
    user,job,_=tkctx
    response=authenticated_client(user).get('/api/internal/integrations/history-batches/')
    assert response.status_code==200
    assert 'tiktok_backfill' in response.data['data']['features']
    assert any(j['id']==job.pk for j in response.data['data']['jobs'])

def test_tiktok_outbox_pause_resume(tkctx):
    existing.test_outbox_resubmits_same_key_and_pause_blocks_worker(tkctx)

def test_tiktok_permission_revocation(tkctx):
    existing.test_permission_revocation_blocks_queued_background_execution(tkctx)

def test_tiktok_history_cursor_kept_when_daily_changes(tkctx):
    existing.test_paused_history_preserves_cursor_when_editing_or_disabling_daily_job(tkctx)


def test_tiktok_budget_resume_and_daily_checkpoint_isolation(tkctx):
    existing.test_history_budget_resume_scope_and_default_checkpoint_isolation(tkctx)
