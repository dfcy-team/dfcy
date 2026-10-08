import base64
import json
from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
from django.utils import timezone

from apps.integrations.models import SyncRun
from apps.integrations.scheduler import resume_due_sync_runs
from apps.integrations.sync_delivery import DeliverySnapshot, SYNC_TASK, _fence, read_delivery_snapshot
from tests.test_mock_sync_isolation import context


def message(sequence=2, positional=False):
    body = [[3, "key", sequence], {}, {}] if positional else [[3], {"idempotency_key": "key", "resume_sequence": sequence}, {}]
    return {"headers": {"task": SYNC_TASK}, "body": base64.b64encode(json.dumps(body).encode()).decode()}


@pytest.mark.parametrize("positional", [False, True])
def test_fence_matches_sequence_and_positional_legacy_task(positional):
    assert _fence(message(positional=positional)) == (3, "key", 2)
    snapshot = DeliverySnapshot({(3, "key", 2)}, complete=False)
    assert snapshot.state(3, "key", 2) == "present"
    assert snapshot.state(3, "key", 3) == "unknown"


def test_broker_exception_is_unknown_not_empty_and_never_exposed():
    with patch("apps.integrations.sync_delivery.current_app.connection_for_read", side_effect=RuntimeError("secret")):
        snapshot = read_delivery_snapshot()
    assert snapshot.state(3, "key", 2) == "unknown"
    assert "secret" not in repr(snapshot)


def test_poison_message_does_not_hide_valid_fences_or_authorize_absence():
    snapshot = DeliverySnapshot()
    assert not snapshot.collect("invalid")
    assert snapshot.collect(json.dumps(message()))
    assert snapshot.state(3, "key", 2) == "present"
    assert snapshot.state(3, "missing", 2) == "unknown"
    assert snapshot.issue == "unreadable_message"


@pytest.mark.parametrize("location", ["broker", "unacked"])
def test_priority_and_reserved_messages_are_found_without_control_broadcast(location):
    connection = Mock()
    channel = connection.channel.return_value
    connection.transport.driver_type = "redis"
    channel.priority_steps = [0, 3, 6, 9]
    channel._q_for_pri.side_effect = lambda queue, priority: f"{queue}:{priority}"
    channel.unacked_key = "unacked"
    client = channel.client
    client.llen.side_effect = lambda key: int(location == "broker" and key == "sync:3")
    client.lrange.return_value = [json.dumps(message())]
    client.hscan.return_value = (0, {"delivery": json.dumps([message(), "exchange", "sync"])} if location == "unacked" else {})
    with patch("apps.integrations.sync_delivery.current_app.connection_for_read") as factory:
        factory.return_value.__enter__.return_value = connection
        snapshot = read_delivery_snapshot()
    assert snapshot.complete and snapshot.state(3, "key", 2) == "present"
    assert snapshot.state(3, "key", 1) == "absent"


def test_bounded_partial_scan_cannot_authorize_absent_retry():
    connection = Mock()
    channel = connection.channel.return_value
    connection.transport.driver_type = "redis"
    channel.priority_steps = [0]
    channel._q_for_pri.side_effect = lambda queue, priority: queue
    channel.client.llen.return_value = 5001
    channel.client.lrange.return_value = []
    channel.client.hscan.return_value = (0, {})
    with patch("apps.integrations.sync_delivery.current_app.connection_for_read") as factory:
        factory.return_value.__enter__.return_value = connection
        snapshot = read_delivery_snapshot()
    assert not snapshot.complete and snapshot.state(3, "key", 2) == "unknown"


@pytest.mark.django_db
@pytest.mark.parametrize("state", ["present", "unknown", "absent"])
def test_continuation_republish_requires_confirmed_absence_and_keeps_progress(context, state):
    _, job = context
    now = timezone.now()
    run = SyncRun.objects.create(tenant=job.tenant, sync_job=job, run_id="durable",
        status="queued", idempotency_key="durable-key", fetched_count=19,
        masked_log={"runtime_budget": {"pending": True, "sequence": 3, "submitted_at": (now - timedelta(hours=2)).isoformat()}})
    snapshot = DeliverySnapshot({(job.id, run.idempotency_key, 3)} if state == "present" else set(), complete=state == "absent")
    enqueue = Mock()
    assert resume_due_sync_runs(enqueue, now=now, delivery_snapshot=snapshot) == (1 if state == "absent" else 0)
    if state == "absent":
        assert enqueue.call_args.args == (job.id, "durable-key", 3)
        assert resume_due_sync_runs(enqueue, now=now, delivery_snapshot=snapshot) == 0
    run.refresh_from_db()
    assert run.fetched_count == 19 and run.status == "queued" and run.masked_log["runtime_budget"]["sequence"] == 3
    assert run.masked_log["delivery"]["state"] == state
