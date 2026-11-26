from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from apps.integrations.adapters import PlatformAdapter
from apps.integrations.models import (
    ConnectionCapability, SyncAlertIncident, SyncCheckpoint, SyncRun,
)
from apps.integrations.raw_services import load_raw_payload
from apps.integrations.sync_alerts import upsert_sync_failure_alert
from apps.integrations.sync_services import run_sync_job
from tests.test_affiliate_daily_ingestion import detail, order, trial
from tests.test_mock_sync_isolation import context  # noqa: F401

pytestmark = pytest.mark.django_db


def _prepare_affiliate_trial(trial):
    trial.job.integration_config.environment = "pilot"
    trial.job.integration_config.save(update_fields=["environment"])
    ConnectionCapability.objects.create(authorization=trial.adapter.authorization,
        capability_code="ORDER", read_enabled=True, write_enabled=False, status="active")
    trial.job.sync_scope = {"affiliate": trial.policy}
    trial.job.status = "idle"
    trial.job.lock_token = ""
    trial.job.lock_expires_at = None
    trial.job.save(update_fields=["sync_scope", "status", "lock_token", "lock_expires_at"])
    checkpoint = SyncCheckpoint.objects.create(tenant=trial.job.tenant, sync_job=trial.job,
        cursor_json={"default": ""}, watermark_utc=datetime(2026, 7, 30, tzinfo=UTC),
        last_success_run=trial.run, version=9)
    upsert_sync_failure_alert(trial.job, sync_run=trial.run, error_code="OLD_FAILURE")
    return checkpoint


def test_real_affiliate_run_keeps_partial_facts_raw_checkpoint_and_alert(trial):
    checkpoint = _prepare_affiliate_trial(trial)
    trial.client.preflight = Mock()
    missing = order(sku="sku-missing", creator_username="")
    missing["id"] = "order-missing"
    valid = order(sku="sku-valid")
    valid["id"] = "order-valid"
    trial.client._transport_request = Mock(side_effect=[
        {"data": {"orders": [missing, valid], "total_count": 2}},
        {"data": {"orders": [
            detail(id="order-missing", line_items=[{"id": "line-missing", "sku_id": "sku-missing", "quantity": 1, "sale_price": "10"}]),
            detail(id="order-valid", line_items=[{"id": "line-valid", "sku_id": "sku-valid", "quantity": 1, "sale_price": "10"}]),
        ]}},
    ])

    run, created = run_sync_job(trial.job, adapter=trial.adapter, idempotency_key="terminal-partial")

    checkpoint.refresh_from_db()
    assert created and run.status == SyncRun.Status.FAILED
    assert run.error_code == "AFFILIATE_IDENTITY_PARTIAL"
    assert run.failed_count == 1 and run.created_count == 1
    assert run.raw_envelopes.count() == 3
    raw_envelope = run.raw_envelopes.get(endpoint__contains="projected://affiliate/complete-day")
    raw = load_raw_payload(raw_envelope)
    assert raw["records"][0]["order_id"] == "order-missing"
    assert raw["records"][1]["order_id"] == "order-valid"
    from apps.influencers.models import AffiliateOrderSnapshot
    assert AffiliateOrderSnapshot.objects.filter(order_id="order-valid").exists()
    assert not AffiliateOrderSnapshot.objects.filter(order_id="order-missing").exists()
    assert checkpoint.last_success_run_id == trial.run.pk
    assert checkpoint.watermark_utc == datetime(2026, 7, 30, tzinfo=UTC)
    assert checkpoint.version == 9 and checkpoint.cursor_json == {"default": ""}
    assert SyncAlertIncident.objects.get(sync_job=trial.job).status == SyncAlertIncident.Status.OPEN


class FailedWarehouseAdapter(PlatformAdapter):
    adapter_name = "synthetic-warehouse-terminal"
    execution_mode = "mock"

    def __init__(self):
        self.source_run = None

    def bind_run(self, run):
        self.source_run = run

    def fetch_page(self, _job, cursor_value=None):
        return {"records": [{"warehouse_fact": "persisted"}] if not cursor_value else [],
                "next_cursor": ""}

    def normalize_record(self, record):
        return record

    def validate_record(self, record):
        return record.get("warehouse_fact") == "persisted"

    def persist_record(self, _job, _record):
        return {"action": "created", "idempotency_key": "warehouse-fact"}

    def get_next_cursor(self, page):
        return page["next_cursor"]

    def completion_outcome(self, _job):
        return {"failed": True, "error_code": "WAREHOUSE_LOOKUP_INCOMPLETE",
                "message": "Synthetic incomplete lookup."}


def test_real_warehouse_failed_completion_preserves_raw_and_failure_alert(trial, monkeypatch):
    checkpoint = _prepare_affiliate_trial(trial)
    trial.job.resource_type = "warehouse_order_lookup"
    trial.job.save(update_fields=["resource_type"])
    adapter = FailedWarehouseAdapter()
    monkeypatch.setattr("apps.integrations.sync_services.require_sync_read_capability", lambda *args, **kwargs: None)
    monkeypatch.setattr("apps.integrations.warehouse_order_admission.warehouse_slot_available",
                        lambda *args, **kwargs: True)

    run, created = run_sync_job(trial.job, adapter=adapter, idempotency_key="terminal-warehouse-failed")

    checkpoint.refresh_from_db()
    assert created and run.status == SyncRun.Status.FAILED
    assert run.error_code == "WAREHOUSE_LOOKUP_INCOMPLETE"
    assert run.created_count == 1 and run.raw_envelopes.count() == 1
    assert load_raw_payload(run.raw_envelopes.get())["records"] == [{"warehouse_fact": "persisted"}]
    assert checkpoint.last_success_run_id == trial.run.pk
    assert checkpoint.watermark_utc == datetime(2026, 7, 30, tzinfo=UTC)
    assert checkpoint.version == 9 and checkpoint.cursor_json == {"default": ""}
    assert SyncAlertIncident.objects.get(sync_job=trial.job).status == SyncAlertIncident.Status.OPEN
