from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
from django.db import OperationalError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.integrations.models import ConnectionCapability, SyncJob, SyncRun
from apps.integrations.sync_runtime import run_runtime_state
from apps.integrations.sync_services import run_sync_job
from apps.integrations.adapters import MockPlatformAdapter
from apps.integrations.history_sync import dispatch_history_segments
from apps.integrations.sync_delivery import DeliverySnapshot
from tests.test_mock_sync_isolation import context
from tests.test_connection_capability_matrix import make_authorization, grant
from tests.test_history_sync_batches import ctx, create
from tests.test_sync_runtime_budget import empty_delivery_broker
from tests.test_credential_queue_isolation import service_block
from tests.test_sync_capability_gate import grant_workspace_view


@pytest.mark.django_db
def test_continuation_age_is_since_yield_and_delivery_evidence_expires(context):
    _, job = context
    now = timezone.now()
    run = SyncRun.objects.create(tenant=job.tenant, sync_job=job, run_id="age", idempotency_key="age", status="queued",
        enqueued_at=now-timedelta(days=2), started_at=now-timedelta(days=2),
        masked_log={"runtime_budget": {"pending": True, "sequence": 2, "last_page_committed_at": (now-timedelta(seconds=30)).isoformat()},
                    "delivery": {"state": "present", "sequence": 2, "checked_at": (now-timedelta(minutes=4)).isoformat()}})
    state = run_runtime_state(run)
    assert state["wait_seconds"] < 35 and state["delivery_state"] == "unknown"
    assert state["label"] == "等待分页续跑"
    run.error_code = "WAITING_CREDENTIAL_REFRESH"
    assert run_runtime_state(run)["state"] == "credential_wait"


@pytest.mark.django_db
def test_actual_run_workspace_exposes_continuation_runtime_without_mutation(context):
    client, job = context
    grant_workspace_view(job.integration_config.created_by)
    now = timezone.now()
    run = SyncRun.objects.create(tenant=job.tenant, sync_job=job, run_id="workspace-age", idempotency_key="workspace-age",
        status="queued", enqueued_at=now-timedelta(days=2), started_at=now-timedelta(days=2),
        masked_log={"runtime_budget": {"pending": True, "sequence": 2, "last_page_committed_at": (now-timedelta(seconds=30)).isoformat()}})
    response = client.get("/api/internal/integrations/workspace/", {"mode": "sync-runs", "sync_job_id": job.id})
    assert response.status_code == 200
    row = response.data["data"]["results"][0]
    assert row["runtime_state"]["label"] == "等待分页续跑"
    assert 0 <= row["runtime_state"]["wait_seconds"] < 35
    assert row["runtime_state"]["last_progress_at"]
    run.refresh_from_db()
    assert run.status == "queued" and run.enqueued_at == now-timedelta(days=2)


@pytest.mark.django_db
@pytest.mark.parametrize("visibility", [True, False])
def test_matrix_success_is_actual_matching_source_not_capability_guess(visibility):
    tenant, user, auth = make_authorization("phase1")
    grant(user, "integrations.store.view", *( ["integrations.view"] if visibility else [] ))
    ConnectionCapability.objects.create(authorization=auth, capability_code="ORDER", read_enabled=True, status="active", last_success_at=timezone.now())
    ConnectionCapability.objects.create(authorization=auth, capability_code="PRICE", read_enabled=True, status="active", last_success_at=timezone.now())
    job = SyncJob.objects.create(tenant=tenant, integration_config=auth.integration_config, store_authorization=auth, resource_type="sales_order")
    now = timezone.now()
    SyncRun.objects.create(tenant=tenant, sync_job=job, run_id="success", idempotency_key="success", status="success", finished_at=now,
                           masked_log={"execution_mode": "live_readonly"})
    SyncRun.objects.create(tenant=tenant, sync_job=job, run_id="later-fail", idempotency_key="later-fail", status="failed", finished_at=now+timedelta(minutes=2))
    client = APIClient(); client.force_authenticate(user)
    response = client.get(f"/api/internal/integrations/store-capability-matrix/{auth.store_id}/")
    assert response.status_code == 200
    rows = {row["capability_code"]: row for row in response.data["data"]["results"]}
    assert rows["ORDER"]["last_success_at"] == (now if visibility else None)
    assert rows["ORDER"]["execution_summary"]["jobs_count"] == (1 if visibility else 0)
    assert rows["PRICE"]["last_success_at"] is None


@pytest.mark.django_db
@pytest.mark.parametrize("present", [True, False, None])
def test_history_outbox_does_not_flood_busy_or_unknown_queue(ctx, present):
    user, job, _ = ctx
    batch = create(user, [job], "broker-evidence")
    now = timezone.now()
    assert dispatch_history_segments(Mock(), now=now, delivery_snapshot=DeliverySnapshot(complete=True)) == 1
    segment = batch.segments.get(sequence=1)
    run = segment.runs.get()
    snapshot = DeliverySnapshot({(job.id, run.idempotency_key, 0)} if present else set(), complete=present is not None)
    enqueue = Mock()
    assert dispatch_history_segments(enqueue, now=now+timedelta(hours=5), delivery_snapshot=snapshot) == (1 if present is False else 0)
    run.refresh_from_db()
    assert run.status == "queued" and segment.runs.count() == 1
    assert run_runtime_state(run)["delivery_state"] == "unknown"  # future synthetic probe is not live evidence


@pytest.mark.django_db
def test_product_page_lock_order_is_stable_across_cached_deadlock_retry(context):
    _, job = context
    job.resource_type = "platform_product"
    job.save(update_fields=["resource_type"])

    class Adapter(MockPlatformAdapter):
        def fetch_page(self, job, cursor_value=None):
            return {"records": [{"external_id": "b", "store_id": "1", "platform_product_id": "b"},
                                {"external_id": "a", "store_id": "1", "platform_product_id": "a"}], "next_cursor": ""}
        def normalize_record(self, record):
            return record
        def should_continue(self, page, previous_cursor):
            return False

    adapter = Adapter()
    adapter.fetch_page = Mock(wraps=adapter.fetch_page)
    orders = []
    def persist(job, rows):
        orders.append([row["external_id"] for row in rows])
        if len(orders) == 1:
            raise OperationalError(1213, "synthetic")
        return [{"action": "created"} for row in rows]
    adapter.persist_records = persist
    run, _ = run_sync_job(job, adapter=adapter, idempotency_key="stable", retry_wait=lambda _: None)
    assert run.status == "success" and run.created_count == run.fetched_count == 2
    assert orders == [["a", "b"], ["a", "b"]] and adapter.fetch_page.call_count == 1
    assert run.masked_log["runtime_budget"]["last_page_committed_at"]


@pytest.mark.parametrize("compose", ["docker-compose.yml", "deploy/production-control/production-compose.yml", "deploy/pilot/application/docker-compose.pilot-app.yml"])
def test_background_and_sync_consumers_are_disjoint_and_keep_runtime(compose):
    root = Path(__file__).resolve().parents[2]
    source = (root / compose).read_text(encoding="utf-8")
    assert "  celery: &sync-worker\n" in source
    assert "--queues=sync " in service_block(source, "celery")
    background = service_block(source, "celery-background")
    assert "--queues=celery " in background and "<<: *sync-worker" in background
    assert "--queues=credential-refresh " in service_block(source, "celery-credentials")
