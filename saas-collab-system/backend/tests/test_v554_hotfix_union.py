from datetime import timedelta

import pytest
from django.db import DatabaseError
from django.utils import timezone
from unittest.mock import Mock, patch

from django.db import DatabaseError
from apps.integrations.adapters import MockPlatformAdapter
from apps.integrations.models import SyncCursor, SyncJob, SyncRun
from apps.integrations.sync_services import run_sync_job
from apps.integrations.sync_services import _creator_rate_wait, _mysql_lock_error
from apps.integrations.models import HistorySyncBatch, HistorySyncSegment
from apps.integrations.history_sync import dispatch_history_segments
from apps.integrations.sync_delivery import DeliverySnapshot
from tests.test_history_sync_batches import create as create_history_batch_for_test, ctx as history_context
from tests.test_mock_sync_isolation import context

pytestmark = pytest.mark.django_db


def test_video_mysql_contention_wait_is_bounded_to_original_24_hour_window():
    now = timezone.now()
    first_seen = (now - timedelta(hours=23, minutes=59)).isoformat()
    delay, preserved_first_seen = _creator_rate_wait(first_seen, now, 120)
    assert 60 <= delay <= 60
    assert preserved_first_seen == first_seen
    assert _creator_rate_wait(first_seen, now + timedelta(minutes=2), 300) is None


@pytest.mark.parametrize("code", [1205, 1213])
def test_mysql_lock_classifier_recognizes_database_lock_errors(code):
    assert _mysql_lock_error(DatabaseError(code, "lock contention")) == code
    assert _mysql_lock_error(ValueError(code, "not a database error")) is None


class VideoLockAdapter(MockPlatformAdapter):
    def __init__(self):
        self.calls = []

    def fetch_page(self, sync_job, cursor_value=None):
        self.calls.append(cursor_value)
        raise DatabaseError(1205, "synthetic lock timeout")


def test_video_lock_contention_persists_same_run_cursor_and_120_second_ready(context):
    _, job = context
    job.resource_type = "video_metrics"
    job.sync_scope = {"query": {"time_from": "frozen-start", "time_to": "frozen-end"}}
    job.save(update_fields=["resource_type", "sync_scope"])
    adapter = VideoLockAdapter()
    with patch("apps.integrations.sync_services.timezone.now", return_value=timezone.now()), \
         patch("apps.integrations.sync_services.monotonic", return_value=0):
        run, created = run_sync_job(job, adapter=adapter, idempotency_key="video-lock")
    run.refresh_from_db()
    job.refresh_from_db()
    cursor = SyncCursor.objects.get(sync_job=job)
    budget = run.masked_log["runtime_budget"]
    assert created and run.status == SyncRun.Status.QUEUED
    assert job.status == SyncJob.Status.IDLE and not job.lock_token
    assert cursor.cursor_value in ("", None)
    assert adapter.calls == [cursor.cursor_value]
    assert (timezone.datetime.fromisoformat(budget["ready_at"]) - timezone.now()).total_seconds() <= 120
    assert budget["wait_reason"] == "video_database_lock"
    assert budget.get("last_page_committed_at") is None
    assert run.error_code == "VIDEO_LOCK_WAIT"


def test_history_dispatch_bounded_reconciles_locked_terminal_batch_then_selects_pending(history_context, monkeypatch):
    user, job, _ = history_context
    other = SyncJob.objects.create(tenant=job.tenant, integration_config=job.integration_config,
        store_authorization=job.store_authorization, resource_type="refund_return", is_enabled=True)
    def make_batch(selected, key):
        return create_history_batch_for_test(user, [selected], key)
    pending_batch = make_batch(other, "v554-pending-dispatch")
    terminal_batch = make_batch(job, "v554-terminal-reconcile")
    terminal_segments = list(terminal_batch.segments.all())
    for segment in terminal_segments:
        segment.status = "success"
        segment.save(update_fields=["status"])
        SyncRun.objects.create(tenant=job.tenant, sync_job=job, history_segment=segment,
            idempotency_key=f"terminal:{segment.pk}", run_id=f"terminal-{segment.pk}", status="success")
    monkeypatch.setattr("apps.integrations.history_sync.is_module_enabled", lambda *_: True)
    monkeypatch.setattr("apps.integrations.sync_delivery.read_delivery_snapshot",
        lambda: DeliverySnapshot(complete=True))
    enqueue = Mock()
    assert dispatch_history_segments(enqueue, limit=1) == 1
    terminal_batch.refresh_from_db()
    assert terminal_batch.status == "completed"
    assert all(s.status == "success" for s in terminal_batch.segments.all())
    assert pending_batch.segments.filter(status="queued").exists()
    assert enqueue.call_count == 1


@pytest.mark.parametrize('code',[1205,1213])
def test_video_lock_resume_keeps_registered_first_seen_cursor_and_expires(context,code):
    _,job=context
    job.resource_type='video_metrics'
    job.save(update_fields=['resource_type'])
    now=timezone.now()
    adapter=VideoLockAdapter()
    with patch('apps.integrations.sync_services.timezone.now',return_value=now):
        run,_=run_sync_job(job,adapter=adapter,idempotency_key='resume-video-lock')
    cursor=SyncCursor.objects.get(sync_job=job)
    cursor.cursor_value='preserved-page-7'
    cursor.save(update_fields=['cursor_value'])
    first_seen=(now-timedelta(hours=23)).isoformat()
    run.masked_log['runtime_budget']['video_lock_first_seen_at']=first_seen
    run.save(update_fields=['masked_log'])
    original_pk=run.pk
    class LockAdapter(VideoLockAdapter):
        def fetch_page(self,sync_job,cursor_value=None):
            self.calls.append(cursor_value)
            raise DatabaseError(code,'synthetic lock')
    later=now+timedelta(minutes=3)
    retry=LockAdapter()
    with patch('apps.integrations.sync_services.timezone.now',return_value=later):
        resumed,_=run_sync_job(job,adapter=retry,idempotency_key='resume-video-lock',resume_sequence=1)
    resumed.refresh_from_db();cursor.refresh_from_db();job.refresh_from_db()
    assert resumed.pk==original_pk and retry.calls==['preserved-page-7']
    budget=resumed.masked_log['runtime_budget']
    assert budget['video_lock_first_seen_at']==first_seen
    assert timezone.datetime.fromisoformat(budget['ready_at'])==later+timedelta(seconds=120)
    assert resumed.status=='queued' and cursor.cursor_value=='preserved-page-7' and not job.lock_token
    expired=now+timedelta(hours=2)
    with patch('apps.integrations.sync_services.timezone.now',return_value=expired):
        final,_=run_sync_job(job,adapter=LockAdapter(),idempotency_key='resume-video-lock',resume_sequence=budget['sequence'])
    final.refresh_from_db();cursor.refresh_from_db();job.refresh_from_db()
    assert final.pk==original_pk and final.status=='failed'
    assert final.error_code=='VIDEO_LOCK_WAIT_TIMEOUT'
    assert cursor.cursor_value=='preserved-page-7' and not job.lock_token


from tests.test_order_warehouse_lookup import setup_order, binding, package, response, run as run_warehouse
from rest_framework.exceptions import ValidationError


@pytest.mark.parametrize('failure,expected',[(ValidationError('SECRET-UPSTREAM',code='warehouse_response_invalid'),'warehouse_response_invalid'),(RuntimeError('SECRET-UPSTREAM'),'warehouse_query_exception')])
def test_warehouse_failure_code_persisted_without_replacing_good_snapshot(setup_order,failure,expected):
    order,actor,warehouse=setup_order
    binding(order,actor,warehouse)
    with patch('apps.sales_management.warehouse_orders.execute_operation',return_value=response([package(order)])):
        state,row=run_warehouse(order,actor)
    assert state=='matched'
    snapshot=row.snapshot
    with patch('apps.sales_management.warehouse_orders.execute_operation',side_effect=failure):
        state,row=run_warehouse(order,actor)
    assert state=='partial' and row.snapshot==snapshot
    assert row.checks[0]['error_code']==expected
    assert 'SECRET-UPSTREAM' not in str(row.checks)
