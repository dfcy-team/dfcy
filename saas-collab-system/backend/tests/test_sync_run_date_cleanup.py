from datetime import datetime, timezone as dt_timezone

import pytest
from django.utils import timezone

from apps.integrations.models import HistorySyncBatch, HistorySyncSegment, IntegrationAuditLog, SyncRun, SyncScheduleDispatch
from tests.test_phase2_sync_framework import authenticated_client, create_sync_job, create_user, grant_integration_access
from apps.tenants.models import Tenant


@pytest.mark.django_db
def test_cleanup_preview_is_read_only_and_delete_is_confirmed_audited_and_scoped():
    tenant = Tenant.objects.create(name="Cleanup", code="cleanup")
    user = create_user(tenant, "cleanup-admin")
    grant_integration_access(user)
    job = create_sync_job(tenant, user)
    boundary = datetime(2025, 1, 1, tzinfo=dt_timezone.utc)
    old = SyncRun.objects.create(tenant=tenant, sync_job=job, run_id="old", idempotency_key="old",
        status="success", finished_at=boundary.replace(year=2024))
    edge = SyncRun.objects.create(tenant=tenant, sync_job=job, run_id="edge", idempotency_key="edge",
        status="success", finished_at=boundary)
    failed = SyncRun.objects.create(tenant=tenant, sync_job=job, run_id="failed", idempotency_key="failed",
        status="failed", finished_at=boundary.replace(year=2024))
    client = authenticated_client(user)
    preview = client.post("/api/internal/integrations/sync-runs/date-cleanup/preview/",
        {"cutoff_date": "2025-01-01", "status": "success"}, format="json").json()["data"]
    assert preview["delete_count"] == 1
    assert SyncRun.objects.filter(pk=old.pk).exists()
    response = client.post("/api/internal/integrations/sync-runs/date-cleanup/delete/",
        {"cutoff_date": "2025-01-01", "status": "success", "confirmation": preview["confirmation"]}, format="json")
    assert response.status_code == 200
    assert not SyncRun.objects.filter(pk=old.pk).exists()
    assert SyncRun.objects.filter(pk=edge.pk, status="success").exists()
    assert SyncRun.objects.filter(pk=failed.pk, status="failed").exists()
    audit = IntegrationAuditLog.objects.get(action="delete_sync_runs_by_date")
    assert audit.actor_id == user.pk and audit.masked_detail["deleted_count"] == 1


@pytest.mark.django_db
def test_cleanup_preserves_linked_run_and_rejects_stale_confirmation():
    tenant = Tenant.objects.create(name="Cleanup links", code="cleanup-links")
    user = create_user(tenant, "cleanup-links-admin")
    grant_integration_access(user)
    job = create_sync_job(tenant, user)
    run = SyncRun.objects.create(tenant=tenant, sync_job=job, run_id="linked", idempotency_key="linked",
        status="success", finished_at=timezone.now().replace(year=2024))
    from apps.integrations.models import SyncCheckpoint
    SyncCheckpoint.objects.create(tenant=tenant, sync_job=job, last_success_run=run)
    client = authenticated_client(user)
    preview = client.post("/api/internal/integrations/sync-runs/date-cleanup/preview/",
        {"cutoff_date": "2025-01-01", "status": "success"}, format="json").json()["data"]
    assert preview["delete_count"] == 0
    assert client.post("/api/internal/integrations/sync-runs/date-cleanup/delete/",
        {"cutoff_date": "2025-01-01", "status": "success", "confirmation": "bad-token"}, format="json").status_code == 400
    assert SyncRun.objects.filter(pk=run.pk).exists()


@pytest.mark.django_db
def test_cleanup_scope_permissions_signed_range_and_batch_limit():
    tenant = Tenant.objects.create(name="Scope cleanup", code="scope-cleanup")
    user = create_user(tenant, "scope-cleanup-admin")
    grant_integration_access(user)
    job = create_sync_job(tenant, user)
    cutoff = datetime(2025, 1, 1, tzinfo=dt_timezone.utc)
    runs = [SyncRun(tenant=tenant, sync_job=job, run_id=f"batch-{i}", idempotency_key=f"batch-{i}",
        status="success", finished_at=cutoff.replace(year=2024)) for i in range(202)]
    SyncRun.objects.bulk_create(runs)
    client = authenticated_client(user)
    body = {"cutoff_date": "2025-01-01", "status": "success"}
    preview = client.post("/api/internal/integrations/sync-runs/date-cleanup/preview/", body, format="json").json()["data"]
    assert preview["delete_count"] == 200 and preview["has_more"] is True
    foreign = create_user(Tenant.objects.create(name="Foreign", code="foreign-cleanup"), "foreign-cleanup-admin")
    grant_integration_access(foreign)
    foreign_client = authenticated_client(foreign)
    assert foreign_client.post("/api/internal/integrations/sync-runs/date-cleanup/delete/",
        {**body, "confirmation": preview["confirmation"]}, format="json").status_code == 400
    assert SyncRun.objects.count() == 202

    viewer = create_user(tenant, "cleanup-viewer")
    from tests.test_phase2_sync_framework import grant_integration_view_only
    grant_integration_view_only(viewer)
    assert authenticated_client(viewer).post("/api/internal/integrations/sync-runs/date-cleanup/preview/",
        body, format="json").status_code == 403
    deleted = client.post("/api/internal/integrations/sync-runs/date-cleanup/delete/",
        {**body, "confirmation": preview["confirmation"]}, format="json")
    assert deleted.status_code == 200
    assert deleted.json()["data"]["deleted_count"] == 200
    assert SyncRun.objects.filter(tenant=tenant).count() == 2
    assert client.post("/api/internal/integrations/sync-runs/date-cleanup/delete/",
        {**body, "confirmation": preview["confirmation"]}, format="json").status_code == 400


@pytest.mark.django_db
def test_cleanup_preserves_schedule_dispatch_link_and_rechecks_status():
    tenant = Tenant.objects.create(name="Schedule cleanup", code="schedule-cleanup")
    user = create_user(tenant, "schedule-cleanup-admin")
    grant_integration_access(user)
    job = create_sync_job(tenant, user)
    run = SyncRun.objects.create(tenant=tenant, sync_job=job, run_id="scheduled", idempotency_key="scheduled",
        status="success", finished_at=timezone.now().replace(year=2024))
    SyncScheduleDispatch.objects.create(tenant=tenant, sync_job=job, scheduled_at=timezone.now(), sync_run=run)
    client = authenticated_client(user)
    body = {"cutoff_date": "2025-01-01", "status": "success"}
    result = client.post("/api/internal/integrations/sync-runs/date-cleanup/preview/", body, format="json").json()["data"]
    assert result["delete_count"] == 0
    dispatch = SyncScheduleDispatch.objects.get(sync_run=run)
    dispatch.delete()
    result = client.post("/api/internal/integrations/sync-runs/date-cleanup/preview/", body, format="json").json()["data"]
    SyncRun.objects.filter(pk=run.pk).update(status="running")
    response = client.post("/api/internal/integrations/sync-runs/date-cleanup/delete/",
        {**body, "confirmation": result["confirmation"]}, format="json")
    assert response.status_code == 400
    assert SyncRun.objects.filter(pk=run.pk, status="running").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("confirmation", [None, 123, [], {}])
def test_cleanup_rejects_malformed_confirmation_with_400(confirmation):
    tenant = Tenant.objects.create(name=f"Malformed {confirmation}", code=f"malformed-{str(confirmation)}")
    user = create_user(tenant, f"malformed-{str(confirmation)}")
    grant_integration_access(user)
    response = authenticated_client(user).post("/api/internal/integrations/sync-runs/date-cleanup/delete/",
        {"cutoff_date": "2025-01-01", "status": "success", "confirmation": confirmation}, format="json")
    assert response.status_code == 400


@pytest.mark.django_db
@pytest.mark.parametrize("endpoint", ["preview", "delete"])
@pytest.mark.parametrize("body", [[{"status": "success"}], 123, None])
def test_cleanup_rejects_non_object_json_body_without_deleting_runs(endpoint, body):
    tenant = Tenant.objects.create(name=f"Non-object {endpoint} {body}", code=f"non-object-{endpoint}-{str(body)}")
    user = create_user(tenant, f"non-object-{endpoint}-{str(body)}")
    grant_integration_access(user)
    job = create_sync_job(tenant, user)
    run = SyncRun.objects.create(tenant=tenant, sync_job=job, run_id="preserved", idempotency_key="preserved",
        status="success", finished_at=datetime(2024, 1, 1, tzinfo=dt_timezone.utc))

    response = authenticated_client(user).post(
        f"/api/internal/integrations/sync-runs/date-cleanup/{endpoint}/", body, format="json")

    assert response.status_code == 400
    assert SyncRun.objects.filter(pk=run.pk).exists()


@pytest.mark.django_db
def test_cleanup_preserves_history_progress_and_rejects_expired_preview():
    from unittest.mock import patch
    from django.core import signing
    tenant = Tenant.objects.create(name="History cleanup", code="history-cleanup")
    user = create_user(tenant, "history-cleanup-admin")
    grant_integration_access(user)
    job = create_sync_job(tenant, user)
    batch = HistorySyncBatch.objects.create(tenant=tenant, created_by=user, name="History",
        idempotency_key="history", request_hash="hash", start_date="2024-01-01", end_date="2024-02-01")
    segment = HistorySyncSegment.objects.create(batch=batch, sync_job=job, sequence=1, scope={}, status="success")
    run = SyncRun.objects.create(tenant=tenant, sync_job=job, history_segment=segment,
        run_id="history", idempotency_key="history", status="success",
        finished_at=datetime(2024, 2, 1, tzinfo=dt_timezone.utc))
    client = authenticated_client(user)
    body = {"cutoff_date": "2025-01-01", "status": "success"}
    preview = client.post("/api/internal/integrations/sync-runs/date-cleanup/preview/", body, format="json").json()["data"]
    assert preview["delete_count"] == 0 and preview["protected_count"] == 1
    with patch("apps.integrations.sync_run_date_cleanup.signing.loads", side_effect=signing.SignatureExpired()):
        response = client.post("/api/internal/integrations/sync-runs/date-cleanup/delete/",
            {**body, "confirmation": preview["confirmation"]}, format="json")
    assert response.status_code == 400
    assert SyncRun.objects.filter(pk=run.pk).exists()
    segment.refresh_from_db()
    assert segment.status == "success"
