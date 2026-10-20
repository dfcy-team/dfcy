"""Bounded collection serialization and scoped pagination for production runs."""
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.integrations.models import SyncRun
from apps.integrations.serializers import SyncRunSerializer
from apps.integrations.sync_run_maintenance import ARCHIVED_INVALID_QUEUE
from tests.test_phase2_sync_framework import (
    authenticated_client, create_sync_job, create_user, grant_integration_view_only,
)
from apps.tenants.models import Tenant


@pytest.fixture
def collection():
    tenant = Tenant.objects.create(name="Run tenant", code="run-pagination")
    user = create_user(tenant, "run-viewer")
    grant_integration_view_only(user)
    job = create_sync_job(tenant, user)
    now = timezone.now()
    SyncRun.objects.bulk_create([
        SyncRun(tenant=tenant, sync_job=job, run_id=f"run-{i}", idempotency_key=f"key-{i}",
                status="success", enqueued_at=now)
        for i in range(105)
    ])
    return user, job


@pytest.mark.django_db
def test_default_page_is_bounded_and_pages_are_stable(collection):
    user, job = collection
    client = authenticated_client(user)
    first = client.get("/api/internal/integrations/sync-runs/")
    assert first.status_code == 200
    first = first.json()["data"]
    assert first["count"] == 105
    assert len(first["results"]) == 50
    assert "page=2" in first["next"]
    assert first["previous"] is None
    second = client.get("/api/internal/integrations/sync-runs/", {"page": 2}).json()["data"]
    ids1 = [r["id"] for r in first["results"]]
    ids2 = [r["id"] for r in second["results"]]
    assert not set(ids1) & set(ids2)
    assert ids1 + ids2 == sorted(ids1 + ids2, reverse=True)
    assert all(r["tenant_id"] == job.tenant_id for r in first["results"])


@pytest.mark.django_db
def test_filters_tenant_scope_and_archived_rows(collection):
    user, job = collection
    other = Tenant.objects.create(name="Other", code="run-other")
    other_user = create_user(other, "other-viewer")
    other_job = create_sync_job(other, other_user)
    SyncRun.objects.create(tenant=other, sync_job=other_job, run_id="hidden", idempotency_key="hidden")
    hidden = SyncRun.objects.filter(sync_job=job).first()
    hidden.error_code = ARCHIVED_INVALID_QUEUE
    hidden.save(update_fields=["error_code"])
    client = authenticated_client(user)
    response = client.get("/api/internal/integrations/sync-runs/", {
        "integration_config_id": job.integration_config_id, "sync_job_id": job.id,
        "platform": "mock", "resource_type": "mock_record", "status": "success", "page_size": 100,
    })
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["count"] == 104
    assert len(data["results"]) == 100
    assert hidden.pk not in {r["id"] for r in data["results"]}
    foreign = client.get("/api/internal/integrations/sync-runs/", {"integration_config_id": other_job.integration_config_id})
    assert foreign.json()["data"]["count"] == 0
    assert client.get("/api/internal/integrations/sync-runs/", {"status": "failed"}).json()["data"]["count"] == 0


@pytest.mark.django_db
@pytest.mark.parametrize("params", [{"page_size": 101}, {"page": 0}, {"page_size": "bad"}, {"sync_job_id": -1}, {"unexpected": 1}])
def test_invalid_paging_or_filters_are_rejected(collection, params):
    user, _ = collection
    assert authenticated_client(user).get("/api/internal/integrations/sync-runs/", params).status_code == 400


@pytest.mark.django_db
def test_out_of_range_page_is_not_found(collection):
    user, _ = collection
    assert authenticated_client(user).get("/api/internal/integrations/sync-runs/", {"page": 9}).status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize("limit", [1, 50])
def test_serializer_query_count_does_not_grow_with_rows(collection, limit):
    _, job = collection
    queryset = SyncRun.objects.filter(sync_job=job).select_related(
        "sync_job", "sync_job__integration_config", "history_segment__batch",
    )[:limit]
    with CaptureQueriesContext(connection) as captured:
        rows = SyncRunSerializer(queryset, many=True).data
    assert len(rows) == limit
    assert len(captured) == 1
    assert all(row["tenant_id"] == job.tenant_id for row in rows)
