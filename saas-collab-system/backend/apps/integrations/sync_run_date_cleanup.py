"""Bounded, tenant-scoped deletion of unreferenced successful sync run history."""
import hashlib
import json
import re
from datetime import datetime, time, timezone as datetime_timezone

from django.core import signing
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import IntegrationAuditLog, PlatformIntegrationConfig, SyncJob, SyncRun

MAX_DELETE = 200
TOKEN_MAX_AGE = 600


def _cutoff(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValidationError("截止日期必须为 YYYY-MM-DD。")
    try:
        day = datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise ValidationError("截止日期必须为 YYYY-MM-DD。")
    # UTC exclusive boundary: remove only completed_at < 00:00 UTC on selected day.
    return datetime.combine(day, time.min, tzinfo=datetime_timezone.utc)


def _fingerprint(run):
    fields = ("pk", "tenant_id", "sync_job_id", "status", "idempotency_key", "finished_at")
    raw = json.dumps({key: str(getattr(run, key)) for key in fields}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def preview(tenant_id, actor_id, cutoff_date, status="success", scope_queryset=None, _internal=False):
    if status != "success":
        raise ValidationError("仅支持清理成功记录。")
    cutoff = _cutoff(cutoff_date)
    if cutoff.date() >= timezone.now().date():
        raise ValidationError("截止日期必须早于今天（UTC）。")
    qs = (scope_queryset if scope_queryset is not None else SyncRun.objects.filter(tenant_id=tenant_id))
    qs = qs.filter(tenant_id=tenant_id, status="success", finished_at__lt=cutoff, history_segment__isnull=True)
    scoped_old_count = (scope_queryset if scope_queryset is not None else SyncRun.objects.filter(tenant_id=tenant_id)).filter(
        tenant_id=tenant_id, status="success", finished_at__lt=cutoff).count()
    # SQL-level exclusion for every reverse FK/one-to-one relation; no per-row probes.
    for relation in SyncRun._meta.related_objects:
        query_name = relation.field.related_query_name()
        qs = qs.exclude(**{f"{query_name}__isnull": False})
    eligible_count = qs.count()
    rows = list(qs.order_by("pk")[:MAX_DELETE + 1])
    candidates = rows[:MAX_DELETE]
    plan = {"tenant_id": tenant_id, "actor_id": actor_id, "cutoff_date": cutoff_date,
            "status": status, "limit": MAX_DELETE,
            "runs": [{"id": r.pk, "fingerprint": _fingerprint(r)} for r in candidates[:MAX_DELETE]]}
    token = signing.dumps(plan, salt="sync-run-date-cleanup-v1")
    result = {"candidate_count": eligible_count, "delete_count": len(plan["runs"]),
              "protected_count": scoped_old_count - eligible_count, "has_more": eligible_count > MAX_DELETE,
              "confirmation": token}
    if _internal:
        result["plan"] = plan
    return result


def delete_confirmed(tenant_id, actor, cutoff_date, confirmation, scope_queryset=None):
    first = preview(tenant_id, actor.pk, cutoff_date, scope_queryset=scope_queryset, _internal=True)
    if not isinstance(confirmation, str) or not confirmation:
        raise ValidationError("预览已过期或确认信息无效，请重新预览。")
    try:
        token_plan = signing.loads(confirmation, salt="sync-run-date-cleanup-v1", max_age=TOKEN_MAX_AGE)
    except signing.BadSignature:
        raise ValidationError("预览已过期或确认信息无效，请重新预览。")
    if token_plan != first["plan"]:
        raise ValidationError("预览已变化，请重新预览。")
    ids = [item["id"] for item in first["plan"]["runs"]]
    if not ids:
        return {"deleted_count": 0}
    with transaction.atomic():
        job_ids = list(SyncRun.objects.filter(tenant_id=tenant_id, pk__in=ids).values_list("sync_job_id", flat=True))
        list(SyncJob.objects.select_for_update(of=("self",)).filter(tenant_id=tenant_id, pk__in=job_ids).order_by("pk"))
        runs = list(SyncRun.objects.select_for_update(of=("self",)).filter(
            tenant_id=tenant_id, pk__in=ids).select_related("sync_job", "sync_job__integration_config").order_by("pk"))
        fresh = preview(tenant_id, actor.pk, cutoff_date, scope_queryset=scope_queryset, _internal=True)
        if fresh["plan"] != first["plan"]:
            raise ValidationError("记录或关联已变化，未删除任何记录，请重新预览。")
        if len(runs) > MAX_DELETE or len(runs) != len(ids):
            raise ValidationError("待删除记录已变化，请重新预览。")
        by_config = {}
        for run in runs:
            config_id = run.sync_job.integration_config_id
            if config_id:
                by_config[config_id] = by_config.get(config_id, 0) + 1
        # Audit each affected config before deleting, in the same transaction.
        for config_id, config_count in by_config.items():
            config = PlatformIntegrationConfig.objects.get(pk=config_id, tenant_id=tenant_id)
            IntegrationAuditLog.objects.create(tenant_id=tenant_id, integration_config=config,
                action="delete_sync_runs_by_date", actor=actor, result=IntegrationAuditLog.Result.SUCCESS,
                masked_detail={"cutoff_date": cutoff_date, "deleted_count": config_count, "status": "success"})
        count = 0
        for run in runs:
            run.delete()
            count += 1
    return {"deleted_count": count}
