from datetime import UTC, datetime, timedelta
from importlib import import_module
from unittest.mock import Mock, patch

import pytest
from django.apps import apps
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.integrations.history_sync import batch_action, batch_data, dispatch_history_segments
from apps.integrations.models import HistorySyncSegment, IntegrationAuditLog, SyncCheckpoint, SyncCursor, SyncJob, SyncRun
from apps.permissions.models import DataScope, Permission, Role
from apps.integrations.models import marketplace_identity_key, marketplace_store_binding_key
from apps.integrations.store_authorization_service import authorization_service_write
from tests.test_history_sync_batches import ctx, create, payload
from tests.test_phase2_sync_framework import authenticated_client

pytestmark = pytest.mark.django_db


def adjustment(batch, job_ids, start="2025-09-01", end="2026-02-28"):
    return {"start_date": start, "end_date": end,
            "expected_revision": batch_data(batch, job_ids, job_ids)["range_adjustment"]["revision"]}


def paused(user, jobs):
    batch = create(user, jobs)
    return batch_action(batch, user, "pause")


def assert_coverage(batch, job, start, end):
    segments = sorted(batch.segments.filter(sync_job=job), key=lambda segment: segment.scope["time_from"])
    assert segments[0].scope["time_from"] == int(datetime.fromisoformat(f"{start}T00:00:00+08:00").timestamp())
    assert segments[-1].scope["time_to"] == int(datetime.fromisoformat(f"{end}T23:59:59+08:00").timestamp())
    assert all(0 <= segment.scope["time_to"] - segment.scope["time_from"] < 15 * 86400 for segment in segments)
    for first, second in zip(segments, segments[1:]):
        assert second.scope["time_from"] == first.scope["time_to"] + 1


def test_unused_range_can_shrink_atomically_and_stays_paused(ctx):
    user, job, _ = ctx
    batch = paused(user, [job])
    original_scope, original_schedule, original_hash = job.sync_scope, job.schedule_type, batch.request_hash
    old_ids = list(batch.segments.values_list("pk", flat=True))
    data = adjustment(batch, [job.pk], "2025-11-01", "2025-12-31")
    result = batch_action(batch, user, "adjust_range", data)
    assert result.status == "paused" and result.finished_at is None
    assert result.request_hash == original_hash and result.created_by_id == user.pk
    assert result.segments.count() == 5
    assert not HistorySyncSegment.objects.filter(pk__in=old_ids).exists()
    assert_coverage(batch, job, data["start_date"], data["end_date"])
    assert dispatch_history_segments(Mock()) == 0
    job.refresh_from_db()
    assert (job.sync_scope, job.schedule_type) == (original_scope, original_schedule)
    # The old creation idempotency key still returns this adjusted batch.
    assert create(user, [job]).pk == result.pk
    detail = IntegrationAuditLog.objects.get(action="history_sync_adjust_range").masked_detail
    assert detail["old_range"] == {"start_date": "2025-10-01", "end_date": "2026-01-31"}
    assert detail["new_range"] == {"start_date": "2025-11-01", "end_date": "2025-12-31"}
    assert detail["replaced_pending_segments"] == 9 and detail["new_pending_segments"] == 5
    assert detail["preserved_segments"] == 0 and detail["auto_resumed"] is False and detail["platform_write"] is False


def test_expansion_preserves_success_failure_queued_and_all_checkpoints(ctx):
    user, job, _ = ctx
    batch = paused(user, [job])
    protected = list(batch.segments.order_by("sequence")[:3])
    originals = {}
    for segment, state in zip(protected, ["success", "failed", "queued"]):
        segment.status, segment.submitted_at = state, timezone.now()
        segment.save()
        run = SyncRun.objects.create(tenant=job.tenant, sync_job=job, history_segment=segment,
            run_id=f"preserved-{segment.pk}", idempotency_key=f"history:{segment.pk}:1", status=state, fetched_count=12,
            masked_log={"runtime_budget": {"resolved_scope": segment.scope, "sequence": 3}})
        SyncCursor.objects.create(tenant=job.tenant, sync_job=job, cursor_key=f"history:{segment.pk}", cursor_value="saved-page")
        originals[segment.pk] = (segment.scope, segment.sequence, segment.attempt, run.pk, run.masked_log)
    default = SyncCursor.objects.create(tenant=job.tenant, sync_job=job, cursor_key="default", cursor_value="daily-page")
    checkpoint = SyncCheckpoint.objects.create(tenant=job.tenant, sync_job=job, version=7, cursor_json={"default": "daily-page"})
    data = adjustment(batch, [job.pk])
    assert batch_data(batch, [job.pk], [job.pk])["range_adjustment"]["allowed"]
    batch_action(batch, user, "adjust_range", data)
    for segment in protected:
        segment.refresh_from_db()
        run = segment.runs.get()
        assert (segment.scope, segment.sequence, segment.attempt, run.pk, run.masked_log) == originals[segment.pk]
        assert job.cursors.get(cursor_key=f"history:{segment.pk}").cursor_value == "saved-page"
    default.refresh_from_db()
    checkpoint.refresh_from_db()
    assert default.cursor_value == "daily-page" and checkpoint.version == 7
    assert checkpoint.cursor_json == {"default": "daily-page"}
    assert batch_data(batch, [job.pk])["fetched_count"] == 36
    assert_coverage(batch, job, data["start_date"], data["end_date"])
    assert IntegrationAuditLog.objects.get(action="history_sync_adjust_range").masked_detail["preserved_segments"] == 3
    assert dispatch_history_segments(Mock()) == 0


@pytest.mark.parametrize("protection", ["success", "failed", "queued", "run", "cursor", "submitted", "attempt"])
def test_every_started_or_reserved_window_is_protected_from_truncation(ctx, protection):
    user, job, _ = ctx
    batch = paused(user, [job])
    segment = batch.segments.get(sequence=1)
    if protection in {"success", "failed", "queued"}:
        segment.status = protection
    elif protection == "run":
        SyncRun.objects.create(tenant=job.tenant, sync_job=job, history_segment=segment,
            run_id="protected-run", idempotency_key="protected-run", status="failed")
    elif protection == "cursor":
        SyncCursor.objects.create(tenant=job.tenant, sync_job=job, cursor_key=f"history:{segment.pk}", cursor_value="")
    elif protection == "submitted":
        segment.submitted_at = timezone.now()
    else:
        segment.attempt = 2
    segment.save()
    original = list(batch.segments.values("pk", "scope", "status", "attempt"))
    metadata = batch_data(batch, [job.pk], [job.pk])["range_adjustment"]
    assert metadata["protected_start_date"] == "2025-10-01" and metadata["protected_end_date"] == "2025-10-15"
    with pytest.raises(ValidationError, match="不能裁掉"):
        batch_action(batch, user, "adjust_range", adjustment(batch, [job.pk], "2025-11-01", "2026-01-31"))
    batch.refresh_from_db()
    assert str(batch.start_date) == "2025-10-01" and batch.status == "paused"
    assert list(batch.segments.values("pk", "scope", "status", "attempt")) == original
    assert not IntegrationAuditLog.objects.filter(action="history_sync_adjust_range").exists()


@pytest.mark.parametrize("busy", ["job", "lease", "run"])
def test_running_or_inflight_execution_must_settle_before_adjustment(ctx, busy):
    user, job, _ = ctx
    batch = paused(user, [job])
    data = adjustment(batch, [job.pk])
    if busy == "job":
        job.status = "running"
        job.save()
    elif busy == "lease":
        job.lock_expires_at = timezone.now() + timedelta(minutes=5)
        job.save()
    else:
        SyncRun.objects.create(tenant=job.tenant, sync_job=job, history_segment=batch.segments.first(),
            run_id="inflight", idempotency_key="inflight", status="running")
    metadata = batch_data(batch, [job.pk], [job.pk])["range_adjustment"]
    assert not metadata["allowed"] and "在途" in metadata["blocked_reason"]
    with pytest.raises(ValidationError, match="在途"):
        batch_action(batch, user, "adjust_range", data)
    assert batch.segments.count() == 9


def test_running_batch_requires_pause_and_stale_revision_requires_reopen(ctx):
    user, job, _ = ctx
    batch = create(user, [job])
    data = adjustment(batch, [job.pk])
    with pytest.raises(ValidationError, match="先暂停"):
        batch_action(batch, user, "adjust_range", data)
    batch = batch_action(batch, user, "pause")
    with pytest.raises(ValidationError, match="已变化"):
        batch_action(batch, user, "adjust_range", data)
    data = adjustment(batch, [job.pk])
    batch_action(batch, user, "adjust_range", data)
    count = batch.segments.count()
    with pytest.raises(ValidationError, match="已变化"):
        batch_action(batch, user, "adjust_range", data)
    assert batch.segments.count() == count
    assert IntegrationAuditLog.objects.filter(action="history_sync_adjust_range").count() == 1


def test_queued_paused_outbox_survives_adjustment_and_only_explicit_resume_dispatches(ctx):
    user, job, _ = ctx
    batch = create(user, [job])
    dispatch_history_segments(Mock())
    first = batch.segments.get(sequence=1)
    key = first.runs.get().idempotency_key
    batch = batch_action(batch, user, "pause")
    batch_action(batch, user, "adjust_range", adjustment(batch, [job.pk]))
    assert dispatch_history_segments(Mock(), now=timezone.now() + timedelta(minutes=4)) == 0
    batch_action(batch, user, "resume")
    enqueue = Mock()
    assert dispatch_history_segments(enqueue, now=timezone.now() + timedelta(minutes=4)) == 1
    assert enqueue.call_args.args == (job.pk, key, 0)
    assert first.runs.count() == 1


@pytest.mark.parametrize("state", ["completed", "failed"])
def test_ended_batch_can_extend_but_cannot_overlap_another_active_batch(ctx, state):
    user, job, _ = ctx
    batch = create(user, [job])
    batch.status, batch.finished_at = state, timezone.now()
    batch.save()
    batch.segments.update(status="success" if state == "completed" else "failed")
    data = adjustment(batch, [job.pk])
    assert batch_data(batch, [job.pk], [job.pk])["range_adjustment"]["allowed"]
    other = create(user, [job], "other-active")
    assert not batch_data(batch, [job.pk], [job.pk])["range_adjustment"]["allowed"]
    with pytest.raises(ValidationError, match="其他未结束"):
        batch_action(batch, user, "adjust_range", data)
    other.status = "completed"
    other.save()
    batch_action(batch, user, "adjust_range", adjustment(batch, [job.pk]))
    assert batch.status == state  # Caller instance is not mutated; API returns the locked fresh instance.
    batch.refresh_from_db()
    assert batch.status == "paused" and batch.finished_at is None
    assert batch.segments.filter(status="success" if state == "completed" else "failed").count() == 9
    assert_coverage(batch, job, "2025-09-01", "2026-02-28")


@pytest.mark.parametrize("field,value", [("start_date", "bad"), ("end_date", "2099-01-01"),
    ("start_date", "2027-01-01"), ("start_date", "2000-01-01"), ("start_date", "20250901"),
    ("expected_revision", "invalid"), ("job_ids", [999])])
def test_invalid_or_injected_range_parameters_are_atomic(ctx, field, value):
    user, job, _ = ctx
    batch = paused(user, [job])
    data = adjustment(batch, [job.pk])
    data[field] = value
    with pytest.raises(ValidationError):
        batch_action(batch, user, "adjust_range", data)
    assert batch.segments.count() == 9
    batch.refresh_from_db()
    assert str(batch.start_date) == "2025-10-01"


def test_same_range_is_idempotent_without_replanning_or_audit(ctx):
    user, job, _ = ctx
    batch = paused(user, [job])
    original = list(batch.segments.values_list("pk", flat=True))
    batch_action(batch, user, "adjust_range", adjustment(batch, [job.pk], "2025-10-01", "2026-01-31"))
    assert list(batch.segments.values_list("pk", flat=True)) == original
    assert not IntegrationAuditLog.objects.filter(action="history_sync_adjust_range").exists()


def test_end_today_uses_beijing_day_and_stops_at_current_second(ctx):
    user, job, _ = ctx
    batch = paused(user, [job])
    now = datetime(2026, 10, 2, 18, 30, tzinfo=UTC)  # Beijing is already October 3.
    with patch("apps.integrations.history_sync.timezone.now", return_value=now):
        batch_action(batch, user, "adjust_range", adjustment(batch, [job.pk], "2025-10-01", "2026-10-03"))
    batch.refresh_from_db()
    assert str(batch.end_date) == "2026-10-03"
    assert max(segment.scope["time_to"] for segment in batch.segments.all()) == int(now.timestamp())


def test_adjustment_applies_identical_range_to_all_three_resource_jobs(ctx):
    user, job, _ = ctx
    jobs = [job] + [SyncJob.objects.create(tenant=job.tenant, integration_config=job.integration_config,
        store_authorization=job.store_authorization, resource_type=resource) for resource in ["sales_order", "refund_return"]]
    batch = paused(user, jobs)
    batch_action(batch, user, "adjust_range", adjustment(batch, [j.pk for j in jobs]))
    for selected in jobs:
        assert_coverage(batch, selected, "2025-09-01", "2026-02-28")
    assert IntegrationAuditLog.objects.filter(action="history_sync_adjust_range").count() == 3


def test_module_disabled_rejects_adjustment_without_mutation(ctx):
    user, job, _ = ctx
    batch = paused(user, [job])
    data = adjustment(batch, [job.pk])
    with patch("apps.integrations.history_sync.is_module_enabled", return_value=False):
        assert not batch_data(batch, [job.pk], [job.pk])["range_adjustment"]["allowed"]
        with pytest.raises(ValidationError, match="模块已停用"):
            batch_action(batch, user, "adjust_range", data)
    assert batch.segments.count() == 9


@pytest.mark.parametrize("permission", ["integrations.history.manage", "integrations.run_live_readonly"])
def test_adjust_api_and_metadata_require_both_permissions(ctx, permission):
    user, job, role = ctx
    batch = paused(user, [job])
    data = adjustment(batch, [job.pk])
    role.permissions.remove(Permission.objects.get(code=permission))
    client = authenticated_client(user)
    response = client.post(f"/api/internal/integrations/history-batches/{batch.pk}/action/", {"action": "adjust_range", **data}, format="json")
    assert response.status_code == 403
    assert not client.get("/api/internal/integrations/history-batches/").data["data"]["batches"][0]["range_adjustment"]["allowed"]
    with pytest.raises(PermissionDenied):
        batch_action(batch, user, "adjust_range", data)


def test_batch_all_job_scope_enforced_with_partial_view(ctx):
    user, job, role = ctx
    other_store = type(job.store_authorization.store).objects.create(tenant=job.tenant, code="range-other", name="Other", platform=job.store_authorization.store.platform)
    identity = marketplace_identity_key("shopee", "PH", "other-external")
    other_auth = type(job.store_authorization)(tenant=job.tenant, integration_config=job.integration_config,
        store=other_store, platform="shopee", region="PH", platform_store_id="other-external",
        platform_identity_key=identity, active_platform_identity_key=identity,
        active_store_binding_key=marketplace_store_binding_key(job.tenant_id, "shopee", other_store.pk),
        merchant_subject_id="merchant", credential_id="fixture-credential", token_id="fixture-token",
        created_by=user, updated_by=user)
    with authorization_service_write():
        other_auth.save()
    second = SyncJob.objects.create(tenant=job.tenant, integration_config=job.integration_config, store_authorization=other_auth, resource_type="sales_order")
    batch = paused(user, [job, second])
    data = adjustment(batch, [job.pk, second.pk])
    scope = DataScope.objects.get(role=role)
    scope.scope_type, scope.config = "custom", {"store_ids": [job.store_authorization.store_id]}
    scope.save()
    client = authenticated_client(user)
    visible = client.get("/api/internal/integrations/history-batches/").data["data"]["batches"][0]
    assert len(visible["shops"]) == 1 and not visible["range_adjustment"]["allowed"]
    assert client.post(f"/api/internal/integrations/history-batches/{batch.pk}/action/", {"action": "adjust_range", **data}, format="json").status_code == 403
    assert batch.segments.count() == 18


def test_api_contract_accepts_only_adjustment_fields_and_returns_new_revision(ctx):
    user, job, _ = ctx
    batch = paused(user, [job])
    client = authenticated_client(user)
    data = adjustment(batch, [job.pk])
    url = f"/api/internal/integrations/history-batches/{batch.pk}/action/"
    assert client.post(url, {"action": "pause", "start_date": "2025-09-01"}, format="json").status_code == 400
    assert client.post(url, {"action": "adjust_range", **data, "job_ids": [job.pk]}, format="json").status_code == 400
    result = client.post(url, {"action": "adjust_range", **data}, format="json")
    assert result.status_code == 200, result.data
    assert result.data["data"]["status"] == "paused"
    assert result.data["data"]["range_adjustment"]["revision"] != data["expected_revision"]
    assert client.post(url, {"action": "adjust_range", **data}, format="json").status_code == 400


def test_permission_description_migration_never_grants_roles_or_scope(ctx):
    user, job, _ = ctx
    role = Role.objects.create(tenant=job.tenant, code="no-history", name="No history")
    permission = Permission.objects.get(code="integrations.history.manage")
    assignments = list(permission.roles.values_list("pk", flat=True))
    scopes = list(DataScope.objects.values("pk", "scope_type", "config"))
    import_module("apps.permissions.migrations.0051_history_range_permission_description").update_description(apps, None)
    permission.refresh_from_db()
    assert "调整范围" in permission.description
    assert list(permission.roles.values_list("pk", flat=True)) == assignments
    assert not role.permissions.exists() and list(DataScope.objects.values("pk", "scope_type", "config")) == scopes
