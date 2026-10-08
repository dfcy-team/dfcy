import base64
import json
from pathlib import Path
from unittest.mock import Mock, patch

from apps.integrations.sync_delivery import SYNC_TASK, read_delivery_snapshot


ROOT = Path(__file__).resolve().parents[2]


def test_sync_and_history_consumers_have_independent_single_slot_topology():
    compose_files = (
        ROOT / "docker-compose.yml",
        ROOT / "deploy/production-control/production-compose.yml",
        ROOT / "deploy/pilot/application/docker-compose.pilot-app.yml",
    )
    for path in compose_files:
        text = path.read_text(encoding="utf-8")
        assert "--queues=sync --concurrency=1" in text
        assert "celery-history:\n    <<: *sync-worker\n    command: celery -A config worker --queues=sync-history --concurrency=1" in text
        assert "--queues=celery --concurrency=1 --prefetch-multiplier=1 --hostname=background@%h" in text
        assert "--queues=sync-control --concurrency=1 --prefetch-multiplier=1 --hostname=control@%h" in text


def test_production_release_pins_history_image_and_requires_history_service():
    deploy = (ROOT / "deploy/production-control/bin/production-deploy").read_text(encoding="utf-8")
    common = (ROOT / "deploy/production-control/lib/production-common.sh").read_text(encoding="utf-8")
    pilot = (ROOT / "deploy/pilot/application/install-app.sh").read_text(encoding="utf-8")
    assert '"$service" = celery-history ]] && has_history=1' in deploy
    assert "  celery-history:\n    image: ${PRODUCTION_BACKEND_IMAGE" in deploy
    assert "for optional in celery-credentials celery-background celery-history; do" in common
    assert "backend celery celery-history celery-background" in pilot


def test_delivery_snapshot_scans_sync_history_priority_buckets():
    connection = Mock()
    channel = connection.channel.return_value
    connection.transport.driver_type = "redis"
    channel.priority_steps = [0, 3, 6, 9]
    channel._q_for_pri.side_effect = lambda queue, priority: f"{queue}:{priority}"
    channel.unacked_key = "unacked"
    client = channel.client
    target = (17, "history-idempotency-key", 4)
    body = [[17], {"idempotency_key": target[1], "resume_sequence": target[2]}, {}]
    message = {"headers": {"task": SYNC_TASK}, "body": base64.b64encode(json.dumps(body).encode()).decode()}
    client.llen.side_effect = lambda key: int(key == "sync-history:6")
    client.lrange.side_effect = lambda key, start, end: [json.dumps(message)] if key == "sync-history:6" else []
    client.hscan.return_value = (0, {})

    with patch("apps.integrations.sync_delivery.current_app.connection_for_read") as factory:
        factory.return_value.__enter__.return_value = connection
        snapshot = read_delivery_snapshot()

    assert snapshot.complete
    assert snapshot.state(*target) == "present"
    assert {f"sync-history:{priority}" for priority in channel.priority_steps}.issubset(
        {call.args[0] for call in client.llen.call_args_list}
    )
