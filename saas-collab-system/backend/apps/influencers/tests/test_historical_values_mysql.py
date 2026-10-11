"""Real two-connection tests; skipped explicitly when not on local MySQL."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone as dt_timezone
import re
from threading import Barrier, Event, current_thread

import pytest
from django.db import close_old_connections, connection, connections
from django.test.utils import CaptureQueriesContext

from apps.audit.models import OperationLog
from apps.influencers import services
from apps.influencers.models import BdSampleAttributionSnapshot, FulfillmentStatusEvent, Influencer, SampleFulfillment, SampleItem
from apps.influencers.tests.test_import_compatibility import sample_records, _personnel_kwargs

pytestmark = pytest.mark.django_db(transaction=True)


def _payload(records, *, inactive=False):
    actor = records["user"]
    actor.is_superuser = True
    actor.save(update_fields=["is_superuser"])
    if inactive:
        creator = records["influencer"]
        creator.status = Influencer.Status.INACTIVE
        creator.code = "handoff-20261009-" + "a" * 24
        creator.save(update_fields=["status", "code"])
    payload = {
        "user": actor, "tenant": records["tenant"], "actor": actor,
        "source": services.FEISHU_FULL_SAMPLE_STATUS_SOURCE,
        "source_row": {"source": "飞书", "external_id": "MYSQL-HISTORY-ROW-1",
                       "status": "shipped", "video_deadline_at": None},
        "validated_data": {"fulfillment_no": "MYSQL-HISTORY-1", "link_type": "direct",
                           "influencer": records["influencer"], "store": records["store"],
                           "owner": actor, "external_product_id": "PRODUCT-COMPAT-1",
                           "product_name_snapshot": "Synthetic historical sample"},
        "item_payloads": [{"requested_sku": "MYSQL-TEST-SKU", "site_code": "PH",
                           "quantity": 1, "currency": "", "unit_cost": None, "cost_amount": None}],
        "status": "shipped", "sample_sent_at": datetime(2026, 8, 28, tzinfo=dt_timezone.utc),
        "shipped_at": None, "preserve_historical_values": True, "return_metadata": True,
        **_personnel_kwargs(actor),
    }
    if inactive:
        payload["historical_inactive_manifest_sha256"] = services.HISTORICAL_INACTIVE_SAMPLE_MANIFEST
    return payload


def _thread_import(payload, barrier=None):
    close_old_connections()
    try:
        if barrier is not None:
            barrier.wait(timeout=20)
        with CaptureQueriesContext(connection) as queries:
            result = services.import_sample_fulfillment_snapshot(**payload)
        writes = sum(bool(re.match(r"\s*(INSERT|UPDATE|DELETE|REPLACE|ALTER|CREATE|DROP)\b", q["sql"], re.I))
                     for q in queries.captured_queries)
        return {"created": result["created"], "outcome": result["outcome"],
                "pk": result["fulfillment"].pk, "writes": writes}
    finally:
        connections.close_all()


def _assert_one_complete_history_row(records):
    samples = SampleFulfillment.objects.filter(tenant=records["tenant"], fulfillment_no="MYSQL-HISTORY-1")
    assert samples.count() == 1
    sample = samples.get()
    assert sample.status == "shipped" and sample.video_deadline_at is None and sample.shipped_at is None
    assert sample.calculated_cost is None
    assert SampleItem.objects.filter(fulfillment=sample, currency="", unit_cost=None, cost_amount=None).count() == 1
    assert FulfillmentStatusEvent.objects.filter(fulfillment=sample).count() == 2
    assert FulfillmentStatusEvent.objects.filter(
        fulfillment=sample, source=services.FEISHU_FULL_SAMPLE_STATUS_SOURCE
    ).count() == 1
    assert BdSampleAttributionSnapshot.objects.filter(fulfillment=sample, cost_amount=None).count() == 1
    assert OperationLog.objects.filter(tenant=records["tenant"], action="feishu_import_historical_values").count() == 1
    expected_status = records["influencer"].status
    records["influencer"].refresh_from_db()
    assert records["influencer"].status == expected_status


def test_mysql_two_connections_create_once_and_readonly_replay(sample_records):
    if connection.vendor != "mysql":
        pytest.skip("Requires real isolated MySQL lock semantics")
    payload = _payload(sample_records)
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_thread_import, payload, barrier) for _ in range(2)]
        results = [future.result(timeout=40) for future in futures]
    assert sorted(row["created"] for row in results) == [False, True]
    assert len({row["pk"] for row in results}) == 1
    assert next(row for row in results if not row["created"])["writes"] == 0
    _assert_one_complete_history_row(sample_records)


def test_mysql_failed_writer_rolls_back_and_waiting_writer_can_create(sample_records, monkeypatch):
    if connection.vendor != "mysql":
        pytest.skip("Requires real isolated MySQL rollback/lock semantics")
    payload = _payload(sample_records, inactive=True)
    first_locked = Event()
    release_first = Event()
    second_attempting_lock = Event()
    original_lock = services._lock_tenant
    original_audit = services._audit

    def controlled_lock(actor):
        if current_thread().name == "history-success-writer":
            second_attempting_lock.set()
        locked = original_lock(actor)
        if current_thread().name == "history-failing-writer":
            first_locked.set()
            assert release_first.wait(timeout=20)
        return locked

    def failing_audit(user, action, *args, **kwargs):
        if current_thread().name == "history-failing-writer" and action == "feishu_import_historical_values":
            raise RuntimeError("Synthetic historical audit failure")
        return original_audit(user, action, *args, **kwargs)

    monkeypatch.setattr(services, "_lock_tenant", controlled_lock)
    monkeypatch.setattr(services, "_audit", failing_audit)

    def run_named(name):
        current_thread().name = name
        return _thread_import(payload)

    with ThreadPoolExecutor(max_workers=2) as pool:
        failing = pool.submit(run_named, "history-failing-writer")
        assert first_locked.wait(timeout=20)
        succeeding = pool.submit(run_named, "history-success-writer")
        assert second_attempting_lock.wait(timeout=20)
        release_first.set()
        with pytest.raises(RuntimeError, match="Synthetic historical audit failure"):
            failing.result(timeout=40)
        result = succeeding.result(timeout=40)
    assert result["created"] is True
    _assert_one_complete_history_row(sample_records)
