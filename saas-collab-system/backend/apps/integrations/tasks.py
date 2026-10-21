from celery import shared_task
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import SyncJob, SyncRun, SyncScheduleDispatch
from .scheduler import dispatch_due_jobs, paused_until, resume_due_sync_runs
from .sync_services import fail_queued_sync_run, run_sync_job, validate_manual_sync_job
from .sync_alerts import upsert_sync_failure_alert


@shared_task(soft_time_limit=540, time_limit=600)
def dispatch_feishu_deliveries():
    from .feishu_delivery import dispatch_feishu
    return dispatch_feishu()


@shared_task(soft_time_limit=540, time_limit=600)
def refresh_due_integration_credentials():
    from .automatic_refresh import refresh_due_authorizations
    return refresh_due_authorizations()


@shared_task(soft_time_limit=540, time_limit=600)
def cleanup_tiktok_shop_bindings():
    from .tiktok_shop_binding import cleanup_shop_bindings, cleanup_previous_shop_references
    return {"staged": cleanup_shop_bindings(limit=50), "previous": cleanup_previous_shop_references(limit=50)}


@shared_task(soft_time_limit=540, time_limit=600)
def cleanup_tiktok_ads_authorizations():
    from .tiktok_ads_oauth import cleanup_ads_authorizations
    return cleanup_ads_authorizations(limit=50)


@shared_task(bind=True, soft_time_limit=840, time_limit=900, acks_late=True)
def run_readonly_sync_job(self, sync_job_id, idempotency_key=None, resume_sequence=0):
    sync_job = SyncJob.objects.select_related("tenant", "integration_config").get(pk=sync_job_id)
    dispatch = None
    existing = SyncRun.objects.filter(sync_job=sync_job, idempotency_key=idempotency_key).first() if idempotency_key else None
    segment = existing.history_segment if existing and existing.history_segment_id else None
    if segment and segment.batch.status != "running":
        return {"status": "paused", "created": False}
    if segment:
        from apps.common.module_gate import is_module_enabled
        if not is_module_enabled("api_integrations"):
            return {"status": "blocked", "created": False}
        from .history_sync import history_execution_allowed
        from .history_schedule import history_task_gate, pause_for_permission
        gate = history_task_gate(segment.batch, sync_job.pk)
        if not gate["allowed"]:
            return {"status": gate["state"], "created": False, "next_eligible_at": gate["next_eligible_at"]}
        if not history_execution_allowed(segment):
            pause_for_permission(segment)
            SyncRun.objects.filter(pk=existing.pk).update(masked_error_message="批次提交人的权限或店铺范围已变化，已暂停，请管理员重新核对权限。")
            return {"status": "paused", "created": False}
    if existing:
        budget = (existing.masked_log or {}).get("runtime_budget") or {}
        if existing.status != SyncRun.Status.QUEUED or int(budget.get("sequence", 0)) != resume_sequence:
            return {"status": "not_executed", "created": False}
    delivery = getattr(self.request, "delivery_info", None) or {}
    if segment and delivery.get("routing_key") in {"sync", "celery"}:
        # Legacy messages already on a normal queue only relay their durable
        # run/segment fence; provider work belongs to the dedicated consumer.
        # Do not purge Redis, replace keys, or create another SyncRun.
        try:
            run_readonly_sync_job.apply_async(
                args=(sync_job_id,),
                kwargs={"idempotency_key": idempotency_key, "resume_sequence": resume_sequence},
                queue="sync-history", priority=5,
            )
        except Exception as exc:
            raise self.retry(exc=exc, countdown=5, max_retries=3)
        return {"status": "rerouted", "queue": "sync-history", "created": False}
    if str(idempotency_key or "").startswith("scheduled:"):
        with transaction.atomic():
            sync_job = SyncJob.objects.select_for_update(of=("self",)).select_related("tenant", "integration_config").get(pk=sync_job_id)
            dispatch = SyncScheduleDispatch.objects.filter(pk=str(idempotency_key).split(":")[-1], sync_job=sync_job).first()
            if not dispatch or dispatch.status != "queued":
                return {"status": "not_executed", "created": False}
            if dispatch.sync_run_id:
                linked = dispatch.sync_run
                budget = (linked.masked_log or {}).get("runtime_budget") or {}
                if linked.status != SyncRun.Status.QUEUED or int(budget.get("sequence", 0)) != resume_sequence:
                    return {"status": "not_executed", "created": False}
            pause = paused_until(sync_job)
            if not sync_job.is_enabled or (pause and pause > timezone.now()):
                if dispatch.sync_run_id and resume_sequence:
                    # A reserved continuation may arrive after an operator
                    # pauses the job. Keep its durable outbox eligible on resume.
                    return {"status": "queued", "created": False}
                dispatch.status, dispatch.reason = "skipped", "任务已停用或暂停，未执行"
                dispatch.finished_at = timezone.now()
                dispatch.save(update_fields=["status", "reason", "finished_at"])
                return {"status": "skipped", "created": False}
            dispatch.status, dispatch.started_at = "running", dispatch.started_at or timezone.now()
            dispatch.save(update_fields=["status", "started_at"])
    if existing and resume_sequence:
        frozen = ((existing.masked_log or {}).get("runtime_budget") or {}).get("resolved_scope")
        if isinstance(frozen, dict):
            # Scheduled claims reload the job under lock; attach the persisted
            # window AFTER that reload, including preflight of very old slices.
            sync_job._frozen_sync_scope = frozen
    preflight_rejected = False
    try:
        from .credential_coordination import defer_queued_for_refresh
        deferred = defer_queued_for_refresh(
            sync_job, existing=existing, key=idempotency_key, dispatch=dispatch, history_segment=segment,
        )
        if deferred:
            return {"run_id": deferred.pk, "status": deferred.status, "created": False, "waiting_for_refresh": True}
        if segment:
            from .history_sync import history_validation_job
            try:
                validate_manual_sync_job(history_validation_job(sync_job, segment), live_only=True)
            except ValidationError:
                preflight_rejected = True
                raise
        else:
            try:
                validate_manual_sync_job(sync_job, live_only=True)
            except ValidationError:
                preflight_rejected = True
                raise
        kwargs = {"idempotency_key": idempotency_key, "dispatch": dispatch}
        if segment:
            kwargs["history_segment"] = segment
        if resume_sequence:
            kwargs["resume_sequence"] = resume_sequence
        run, created = run_sync_job(sync_job, **kwargs)
        if dispatch:
            SyncScheduleDispatch.objects.filter(pk=dispatch.pk, status="running").update(
                status=run.status, finished_at=run.finished_at,
                reason=(run.masked_error_message if run.error_code == "ADS_LEASE_BUSY" else "本段时间预算已用完，分页进度已保存，等待续跑。") if run.status == "queued" else "",
            )
    except Exception as exc:
        fail_queued_sync_run(
            sync_job,
            idempotency_key,
            error_code="SYNC_PREFLIGHT_FAILED",
            message=str(exc),
        )
        if dispatch:
            SyncScheduleDispatch.objects.filter(pk=dispatch.pk, status="running").update(
                status="blocked", reason="执行校验或执行阶段失败，请核对授权、能力和只读准入，并查看同步异常。",
                finished_at=timezone.now(),
            )
        upsert_sync_failure_alert(
            sync_job,
            error_code="SYNC_PREFLIGHT_FAILED",
            message=str(exc),
        )
        if preflight_rejected:
            return {"status": "blocked", "created": False, "error_code": "SYNC_PREFLIGHT_FAILED"}
        raise
    return {"run_id": run.id, "status": run.status, "created": created}
@shared_task
def dispatch_due_readonly_sync_jobs(limit=20):
    from .sync_dispatch_policy import DispatchAdmission, fair_resource_order, queue_for_run
    from .affiliate_sync import dispatch_pending_affiliate_refreshes
    affiliate_refreshed = dispatch_pending_affiliate_refreshes(limit=max(1, min(int(limit), 100)))
    def enqueue(job_id, key, resume_sequence=0):
        priority = 0 if SyncJob.objects.filter(pk=job_id, resource_type="inventory_snapshot").exists() else 5
        return run_readonly_sync_job.apply_async(
            args=(job_id,), kwargs={"idempotency_key": key, "resume_sequence": resume_sequence}, priority=priority,
            queue=queue_for_run(job_id, key),
        )
    from .history_sync import dispatch_history_segments
    from .sync_delivery import read_delivery_snapshot
    delivery_snapshot = read_delivery_snapshot()
    limit = max(1, min(int(limit), 100))
    now = timezone.now()
    admission = DispatchAdmission(delivery_snapshot, now, limit)
    result = dispatch_due_jobs(
        enqueue, now=now, limit=limit, admission=admission, resource_type="",
    )
    pending = SyncRun.objects.filter(status="queued", history_segment__isnull=True,
                                    masked_log__runtime_budget__pending=True, sync_job__is_enabled=True)
    resources = set(pending.values_list("sync_job__resource_type", flat=True).distinct())
    resources.update(SyncJob.objects.filter(is_enabled=True, next_run_at__lte=now)
                     .exclude(schedule_type__in=["manual", "cron"]).values_list("resource_type", flat=True).distinct())
    continued = 0
    # Daily continuations and new due jobs compete in the SAME persisted
    # resource order; otherwise a long order run can starve same-store finance.
    for resource in fair_resource_order(resources, "daily"):
        continued += resume_due_sync_runs(enqueue, now=now, limit=limit, delivery_snapshot=delivery_snapshot,
                                         admission=admission, resource_type=resource)
        part = dispatch_due_jobs(enqueue, now=now, limit=limit, admission=admission,
                                 resource_type=resource, maintenance=False)
        for key in ("dispatched", "failed", "skipped"):
            result[key] += part[key]
    result["continued"] = continued
    # Daily dispatch cannot spend the history tick budget. Each queue retains
    # its own bounded slots; common job locks still prevent same-job overlap.
    history_admission = DispatchAdmission(delivery_snapshot, now, min(limit, 2))
    result["history_submitted"] = dispatch_history_segments(
        enqueue, limit=min(limit, 2), delivery_snapshot=delivery_snapshot, admission=history_admission,
    )
    result["admission"] = admission.summary()
    result["history_admission"] = history_admission.summary()
    result["affiliate_refresh_submitted"] = affiliate_refreshed
    return result


@shared_task
def refresh_affiliate_ingestion_day(sync_run_id, business_day, generation=None):
    from apps.influencers.tasks import refresh_affiliate_order_attributions_task
    run = SyncRun.objects.select_related("sync_job").filter(
        pk=sync_run_id, sync_job__resource_type="affiliate_order",
    ).first()
    entry = ((run.masked_log or {}).get("affiliate_refresh") or {}).get(business_day) if run else None
    if not entry or not entry.get("pending"):
        return {"status": "not_pending"}
    expected_generation = entry.get("generation", 0)
    if generation is not None and generation != expected_generation:
        return {"status": "superseded"}
    ids = sorted(set(entry["ids"]))
    # Ack only after every chunk succeeds. A retry may safely repeat earlier chunks.
    for offset in range(0, len(ids), 5000):
        result = refresh_affiliate_order_attributions_task.run(tenant_id=run.tenant_id, order_ids=ids[offset:offset + 5000])
        if not isinstance(result, dict) or result.get("status") != "completed":
            raise RuntimeError("AFFILIATE_REFRESH_NOT_COMPLETED")
    with transaction.atomic():
        locked = SyncRun.objects.select_for_update().get(pk=run.pk, tenant_id=run.tenant_id)
        log = dict(locked.masked_log or {})
        current = (log.get("affiliate_refresh") or {}).get(business_day, {})
        if current.get("generation", 0) != expected_generation or current.get("ids") != entry["ids"]:
            return {"status": "superseded"}
        log["affiliate_refresh"][business_day] = {**log["affiliate_refresh"][business_day], "pending": False}
        log["affiliate_refresh_pending"] = any(item.get("pending") for item in log["affiliate_refresh"].values())
        locked.masked_log = log
        locked.save(update_fields=["masked_log"])
    return {"status": "completed", "snapshot_count": len(ids)}
