from datetime import timedelta
from unittest.mock import Mock

import pytest
from django.utils import timezone

from apps.integrations.history_sync import dispatch_history_segments
from apps.integrations.models import SyncCursor, SyncRun
from tests.test_history_sync_batches import create, ctx, execute
from tests.test_sync_runtime_budget import TwoPageAdapter, empty_delivery_broker

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("resource_type", ["sales_order", "refund_return", "settlement_bill"])
def test_pending_retry_prefers_later_queued_continuation_and_reuses_its_identity(ctx, resource_type):
    user, job, _ = ctx
    job.resource_type = resource_type
    job.save(update_fields=["resource_type"])
    batch = create(user, [job], f"continuation-{resource_type}")
    first, later = list(batch.segments.order_by("sequence")[:2])
    first.status, first.attempt = "pending", 2
    first.save(update_fields=["status", "attempt"])
    later.status, later.attempt = "running", 1
    later.submitted_at = timezone.now() - timedelta(minutes=10)
    later.save(update_fields=["status", "attempt", "submitted_at"])
    key = f"history:{later.pk}:1"
    continuation = SyncRun.objects.create(
        tenant=job.tenant, sync_job=job, history_segment=later, run_id="continuation-run",
        idempotency_key=key, status="queued",
        masked_log={"runtime_budget": {"pending": True, "ready_at": (timezone.now() - timedelta(hours=12)).isoformat(), "sequence": 1, "resolved_scope": later.scope}},
        fetched_count=1, created_count=1,
    )
    cursor = SyncCursor.objects.create(tenant=job.tenant, sync_job=job, cursor_key=f"history:{later.pk}", cursor_value="saved-page")
    enqueue = Mock()

    assert dispatch_history_segments(enqueue) == 1
    assert enqueue.call_args.args == (job.pk, key, 1)
    later.refresh_from_db()
    first.refresh_from_db()
    continuation.refresh_from_db()
    assert later.attempt == 1 and later.status == "queued"
    assert later.runs.count() == 1 and continuation.idempotency_key == key
    assert continuation.pk == SyncRun.objects.get(history_segment=later).pk
    assert continuation.fetched_count == continuation.created_count == 1
    cursor.refresh_from_db()
    assert cursor.cursor_value == "saved-page"
    assert first.status == "pending" and first.attempt == 2


def test_successful_continuation_reconciles_then_returns_to_earlier_retry(ctx):
    user, job, _ = ctx
    batch = create(user, [job], "continuation-then-retry")
    first, later = list(batch.segments.order_by("sequence")[:2])
    first.status, first.attempt = "pending", 2
    first.save(update_fields=["status", "attempt"])
    later.status, later.attempt = "running", 1
    later.submitted_at = timezone.now() - timedelta(minutes=10)
    later.save(update_fields=["status", "attempt", "submitted_at"])
    key = f"history:{later.pk}:1"
    run = SyncRun.objects.create(
        tenant=job.tenant, sync_job=job, history_segment=later, run_id="continuation-run-success",
        idempotency_key=key, status="queued",
        masked_log={"runtime_budget": {"pending": True, "ready_at": (timezone.now() - timedelta(hours=12)).isoformat(), "sequence": 1, "resolved_scope": later.scope}},
        fetched_count=1, created_count=1,
    )
    cursor = SyncCursor.objects.create(tenant=job.tenant, sync_job=job, cursor_key=f"history:{later.pk}", cursor_value="p1")
    resumed, _ = execute(job, later, TwoPageAdapter(), sequence=1)
    assert resumed.pk == run.pk and resumed.status == "success"

    enqueue = Mock()
    assert dispatch_history_segments(enqueue) == 1
    expected_key = f"history:{first.pk}:2"
    assert enqueue.call_args.args == (job.pk, expected_key, 0)
    first.refresh_from_db()
    later.refresh_from_db()
    assert first.status == "queued" and first.attempt == 2 and first.runs.count() == 1
    assert later.status == "success" and later.runs.count() == 1
    cursor.refresh_from_db()
    assert cursor.cursor_value == "p2"


def _pending_and_active(ctx, key):
    user, job, role = ctx
    batch = create(user, [job], key)
    first, active = list(batch.segments.order_by("sequence")[:2])
    first.status, first.attempt = "pending", 2
    first.save(update_fields=["status", "attempt"])
    active.status, active.attempt = "running", 1
    active.submitted_at = timezone.now() - timedelta(minutes=10)
    active.save(update_fields=["status", "attempt", "submitted_at"])
    run = SyncRun.objects.create(
        tenant=job.tenant, sync_job=job, history_segment=active, run_id=f"{key}-run",
        idempotency_key=f"history:{active.pk}:1", status="queued",
        masked_log={"runtime_budget": {"pending": True, "ready_at": (timezone.now() - timedelta(hours=12)).isoformat(), "sequence": 1, "resolved_scope": active.scope}},
        fetched_count=1, created_count=1,
    )
    return user, job, role, batch, first, active, run


@pytest.mark.parametrize("gate", ["future_ready", "debounce", "job_lock", "paused_batch", "revoked_permission"])
def test_continuation_safety_gates_block_dispatch(ctx, gate):
    _, job, role, batch, _, active, run = _pending_and_active(ctx, f"gate-{gate}")
    now = timezone.now()
    if gate == "future_ready":
        log = run.masked_log
        log["runtime_budget"]["ready_at"] = (now + timedelta(minutes=1)).isoformat()
        run.masked_log = log
        run.save(update_fields=["masked_log"])
    elif gate == "debounce":
        active.submitted_at = now - timedelta(seconds=30)
        active.save(update_fields=["submitted_at"])
    elif gate == "job_lock":
        job.lock_expires_at = now + timedelta(minutes=1)
        job.save(update_fields=["lock_expires_at"])
    elif gate == "paused_batch":
        batch.status = "paused"
        batch.save(update_fields=["status"])
    elif gate == "revoked_permission":
        from apps.permissions.models import Permission
        role.permissions.remove(Permission.objects.get(code="integrations.run_live_readonly"))
    enqueue = Mock()

    assert dispatch_history_segments(enqueue, now=now) == 0
    enqueue.assert_not_called()
    assert active.runs.count() == 1 and run.idempotency_key == f"history:{active.pk}:1"


@pytest.mark.parametrize("other_active", ["nonhistory", "second_history"])
def test_multiple_or_nonhistory_active_runs_fail_closed(ctx, other_active):
    _, job, _, _, _, active, _ = _pending_and_active(ctx, f"active-{other_active}")
    another_segment = None
    if other_active == "second_history":
        batch = active.batch
        another_segment = batch.segments.exclude(pk=active.pk).order_by("sequence").first()
        another_segment.status = "running"
        another_segment.save(update_fields=["status"])
    SyncRun.objects.create(
        tenant=job.tenant, sync_job=job, history_segment=another_segment,
        run_id=f"other-{other_active}", idempotency_key=f"other-{other_active}", status="queued",
    )
    enqueue = Mock()

    assert dispatch_history_segments(enqueue) == 0
    enqueue.assert_not_called()


def test_stale_current_attempt_continuation_is_never_resubmitted(ctx):
    _, job, _, _, _, active, stale = _pending_and_active(ctx, "stale-attempt")
    active.attempt = 2
    active.save(update_fields=["attempt"])
    enqueue = Mock()

    assert dispatch_history_segments(enqueue) == 0
    enqueue.assert_not_called()
    assert stale.idempotency_key == f"history:{active.pk}:1"
    assert active.runs.count() == 1


@pytest.mark.parametrize("active_kind", ["history_running", "nonhistory_queued"])
def test_single_active_run_not_eligible_for_history_resume_blocks_dispatch(ctx, active_kind):
    _, _, _, _, _, active, run = _pending_and_active(ctx, f"single-{active_kind}")
    if active_kind == "history_running":
        run.status = "running"
        run.save(update_fields=["status"])
    else:
        run.history_segment = None
        run.save(update_fields=["history_segment"])
    enqueue = Mock()

    assert dispatch_history_segments(enqueue) == 0
    enqueue.assert_not_called()
    active.refresh_from_db()
    run.refresh_from_db()
    assert active.status == "running"
    assert run.status == ("running" if active_kind == "history_running" else "queued")


def test_revoked_shop_data_scope_pauses_continuation_without_new_run(ctx):
    from apps.permissions.models import DataScope

    _, job, role, batch, _, active, run = _pending_and_active(ctx, "revoked-shop-scope")
    scope = DataScope.objects.get(role=role)
    scope.scope_type = "custom"
    scope.config = {"store_ids": [job.store_authorization.store_id + 1000]}
    scope.save(update_fields=["scope_type", "config"])
    enqueue = Mock()

    assert dispatch_history_segments(enqueue) == 0
    enqueue.assert_not_called()
    batch.refresh_from_db()
    run.refresh_from_db()
    assert batch.status == "paused"
    assert run.status == "queued" and run.idempotency_key == f"history:{active.pk}:1"
    assert active.runs.count() == 1 and run.fetched_count == run.created_count == 1
