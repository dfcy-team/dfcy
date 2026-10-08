"""Bounded read-only broker evidence; task IDs alone cannot deduplicate Celery."""
import base64
import json
from dataclasses import dataclass, field

from celery import current_app

SYNC_TASK = "apps.integrations.tasks.run_readonly_sync_job"
SCAN_LIMIT = 5000


@dataclass
class DeliverySnapshot:
    fences: set = field(default_factory=set)
    complete: bool = False
    issue: str = ""

    def collect(self, raw, unacked=False):
        try:
            message = json.loads(raw)
            fence = _fence(message[0] if unacked else message)
            if fence:
                self.fences.add(fence)
            return True
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            self.issue = "unreadable_message"
            return False

    def state(self, job_id, key, sequence):
        if (job_id, key, sequence) in self.fences:
            return "present"
        return "absent" if self.complete else "unknown"


def _fence(message):
    if message.get("headers", {}).get("task") != SYNC_TASK:
        return None
    body = message.get("body")
    if isinstance(body, str):
        body = json.loads(base64.b64decode(body, validate=True))
    args, kwargs = body[:2]
    job_id = kwargs.get("sync_job_id", args[0] if args else None)
    key = kwargs.get("idempotency_key", args[1] if len(args) > 1 else None)
    sequence = kwargs.get("resume_sequence", args[2] if len(args) > 2 else 0)
    return int(job_id), str(key), int(sequence)


def read_delivery_snapshot():
    """Scan Redis priority lists and unacked, never emitting payloads/secrets.

Unknown/partial results cannot authorize redelivery. First delivery remains
possible during an outage; committed timestamps bound uncertain retries.
"""
    snapshot = DeliverySnapshot()
    try:
        with current_app.connection_for_read(connect_timeout=2) as connection:
            channel = connection.channel()
            if connection.transport.driver_type != "redis":
                snapshot.issue = "unsupported_transport"
                return snapshot
            client = channel.client
            seen, complete = 0, True
            for queue in ("sync", "sync-history", "celery"):
                for priority in channel.priority_steps:
                    key = channel._q_for_pri(queue, priority)
                    length = client.llen(key)
                    allowance = max(0, SCAN_LIMIT - seen)
                    complete &= length <= allowance
                    if length and allowance:
                        for raw in client.lrange(key, 0, min(length, allowance) - 1):
                            complete &= snapshot.collect(raw)
                            seen += 1
            cursor = 0
            while seen < SCAN_LIMIT:
                cursor, values = client.hscan(channel.unacked_key, cursor=cursor, count=100)
                for raw in values.values():
                    complete &= snapshot.collect(raw, unacked=True)
                    seen += 1
                if cursor == 0:
                    break
            else:
                complete = False
            snapshot.complete = complete
            if not complete and not snapshot.issue:
                snapshot.issue = "scan_limit"
    except Exception:
        snapshot.complete = False
        snapshot.issue = "broker_unavailable"
    return snapshot


def observe_delivery(run, snapshot, sequence, now):
    state = snapshot.state(run.sync_job_id, run.idempotency_key, sequence)
    previous = (run.masked_log or {}).get("delivery") or {}
    run.masked_log = {**(run.masked_log or {}), "delivery": {
        "state": state, "checked_at": now.isoformat(), "sequence": sequence,
        "issue": snapshot.issue if state == "unknown" else "",
    }}
    run.save(update_fields=["masked_log"])
    if state == "unknown" and (previous.get("state") != "unknown" or previous.get("issue") != snapshot.issue):
        from .sync_alerts import upsert_sync_failure_alert
        upsert_sync_failure_alert(run.sync_job, sync_run=run, error_code="SYNC_DELIVERY_UNCONFIRMED",
            message="队列巡检不可确认，已暂停重复投递并保留采集断点。请管理员检查消费者、Redis 连通性、扫描上限及损坏消息；恢复完整巡检后自动重评，不要清空队列或新建重复任务。")
    return state
