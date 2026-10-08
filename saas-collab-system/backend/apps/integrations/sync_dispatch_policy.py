"""Bounded admission and persisted resource rotation, without broker mutation."""
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

from django.utils.dateparse import parse_datetime

from .models import SyncJob, SyncRun, SyncScheduleDispatch, SyncSchedulerHeartbeat

SCAN_LIMIT = 5000
LANE_CAPACITY = 2  # one active worker + one waiting slice, per queue


def execution_lane(run):
    return "history" if run.history_segment_id else "daily"


def queue_for_run(job_id, key):
    # A caller-controlled prefix is not authorization to enter the history lane.
    return "sync-history" if SyncRun.objects.filter(
        sync_job_id=job_id, idempotency_key=key, history_segment__isnull=False).exists() else "sync"


def _subject(job):
    if job.store_authorization_id:
        return job.tenant_id, job.integration_config.platform, "store", job.store_authorization.store_id
    if job.warehouse_authorization_id:
        return job.tenant_id, job.integration_config.platform, "warehouse", job.warehouse_authorization.warehouse_id
    return job.tenant_id, job.integration_config.platform, "job", job.pk


def fair_resource_order(resources, lane):
    served = dict(SyncSchedulerHeartbeat.objects.filter(key__startswith=f"fair:{lane}:")
                  .values_list("key", "last_seen_at"))
    never = datetime.min.replace(tzinfo=UTC)
    return sorted(set(resources), key=lambda resource: (served.get(f"fair:{lane}:{resource}", never), resource))


def fair_job_ids(queryset, lane, limit):
    """Each resource supplies its own bounded FIFO so blocked IDs cannot monopolize a tick."""
    per_resource = min(500, max(100, limit * 5))
    groups = {}
    for resource in SyncJob.ResourceType.values:
        ids = list(queryset.filter(resource_type=resource).order_by("next_run_at", "pk")
                   .values_list("pk", flat=True)[:per_resource])
        if ids:
            groups[resource] = deque(ids)
    ordered = fair_resource_order(groups, lane)
    result = []
    while groups:
        for resource in ordered:
            if resource in groups:
                result.append(groups[resource].popleft())
                if not groups[resource]:
                    del groups[resource]
    return result


def mark_served(job, lane, now):
    SyncSchedulerHeartbeat.objects.update_or_create(
        key=f"fair:{lane}:{job.resource_type}", defaults={"last_seen_at": now})


class DispatchAdmission:
    """A control-tick budget, not a claimed provider rate-limit or worker mutex."""
    def __init__(self, snapshot, now, limit):
        self.remaining = limit
        self.occupied = defaultdict(int)
        self.subjects = set()
        self.complete = True
        runs = list(SyncRun.objects.filter(status__in=["queued", "running"])
                    .exclude(history_segment__batch__status="paused")
                    .select_related("sync_job__integration_config", "sync_job__store_authorization",
                                    "sync_job__warehouse_authorization", "history_segment")
                    .order_by("pk")[:SCAN_LIMIT + 1])
        dispatches = list(SyncScheduleDispatch.objects.filter(status__in=["queued", "running"], sync_run__isnull=True)
                          .select_related("sync_job__integration_config", "sync_job__store_authorization",
                                          "sync_job__warehouse_authorization")
                          .order_by("pk")[:max(1, SCAN_LIMIT + 1 - len(runs))])
        if len(runs) + len(dispatches) > SCAN_LIMIT:
            self.complete = False
            return
        for run in runs:
            budget = (run.masked_log or {}).get("runtime_budget") or {}
            segment = run.history_segment if run.history_segment_id else None
            last = segment.submitted_at if segment else parse_datetime(str(budget.get("submitted_at") or ""))
            if not budget.get("pending"):
                last = last or run.enqueued_at
            state = snapshot.state(run.sync_job_id, run.idempotency_key, int(budget.get("sequence", 0)))
            if (run.status == "running" or state == "present"
                    or (last and (state == "unknown" or last > now - timedelta(seconds=180)))):
                self._occupy(run.sync_job, execution_lane(run))
        for dispatch in dispatches:
            state = snapshot.state(dispatch.sync_job_id, f"scheduled:{dispatch.sync_job_id}:{dispatch.pk}", 0)
            if (dispatch.status == "running" or state == "present"
                    or not dispatch.enqueued_at or state == "unknown"
                    or dispatch.enqueued_at > now - timedelta(seconds=180)):
                self._occupy(dispatch.sync_job, "daily")

    def _occupy(self, job, lane):
        self.occupied[lane] += 1
        self.subjects.add((lane, _subject(job)))

    def claim(self, job, lane):
        if (not self.complete or not self.remaining or self.occupied[lane] >= LANE_CAPACITY
                or (lane, _subject(job)) in self.subjects):
            return False
        self.remaining -= 1
        self._occupy(job, lane)
        return True

    def summary(self):
        return {"scan_complete": self.complete, "daily_slots_occupied": self.occupied["daily"],
                "history_slots_occupied": self.occupied["history"], "remaining_tick_budget": self.remaining,
                "notice": "有界派发；资源公平轮转；历史与日常独立队列。不是平台限流额度或取数成功证明。"}
