"""Asynchronous, bounded report work; polling never executes a fact-table query."""
import hashlib
import json
from datetime import timedelta
from types import SimpleNamespace

from celery import shared_task
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, Throttled, ValidationError

from apps.common.responses import success_response
from apps.tenants.models import Tenant
from .datasets import DATASETS, scope_fingerprint, selected_permission
from .models import ReportAnalysisJob
from .period_analysis import METRICS, build_analysis, normalize_analysis
from .permissions import IsReportViewer


def authorization_key(user, config):
    dataset = DATASETS[config["dataset"]]
    permission = selected_permission(user, dataset)
    scope = scope_fingerprint(user, dataset, permission, config["dataset"])
    return hashlib.sha256(json.dumps(["period-v1", user.tenant_id, user.pk, config, scope], sort_keys=True, default=str).encode()).hexdigest()


def serialize_job(job):
    return {"id": job.pk, "status": job.status, "error": job.error, "result": job.result if job.status == "completed" else None, "expires_at": job.expires_at, "snapshot_id": job.pk}


@api_view(["POST"])
@permission_classes([IsReportViewer])
def analysis_collection(request):
    config = normalize_analysis(request.data, user=request.user)
    fingerprint = authorization_key(request.user, config)
    now = timezone.now()
    with transaction.atomic():
        # Serialize submissions per tenant, including duplicate clicks across workers.
        Tenant.objects.select_for_update().get(pk=request.user.tenant_id)
        active = ReportAnalysisJob.objects.filter(tenant=request.user.tenant, expires_at__gt=now)
        existing = active.filter(requested_by=request.user, fingerprint=fingerprint).filter(Q(status__in=["queued","running"]) | Q(status="completed",created_at__gte=now-timedelta(seconds=60))).order_by("-pk").first()
        if existing:
            return success_response(serialize_job(existing))
        pending = active.filter(Q(status__in=["queued", "running"]) | Q(worker_active=True))
        if pending.filter(requested_by=request.user).count() >= 3 or pending.count() >= 20:
            raise Throttled(detail="后台分析任务较多，请等待已有任务完成或取消后重试。")
        job = ReportAnalysisJob.objects.create(tenant=request.user.tenant, requested_by=request.user, config=config, fingerprint=fingerprint, expires_at=now + timedelta(minutes=15))
        def enqueue():
            try:
                run_analysis.apply_async(args=[job.pk], retry=False)
            except Exception:
                ReportAnalysisJob.objects.filter(pk=job.pk, status="queued").update(status="failed", error="分析队列暂不可用，请稍后重试。")
        transaction.on_commit(enqueue)
    job.refresh_from_db()
    return success_response(serialize_job(job), status=202)


@api_view(["GET", "DELETE"])
@permission_classes([IsReportViewer])
def analysis_detail(request, pk):
    job = get_object_or_404(ReportAnalysisJob.objects.filter(config__dataset__in=list(METRICS)), pk=pk, tenant=request.user.tenant, requested_by=request.user)
    if request.method == "DELETE":
        ReportAnalysisJob.objects.filter(pk=job.pk).update(status="cancelled", result=None)
        job.refresh_from_db()
        return success_response(serialize_job(job))
    if authorization_key(request.user, job.config) != job.fingerprint:
        raise PermissionDenied("授权范围已变化，请重新生成报表。")
    if job.expires_at <= timezone.now():
        return success_response({"id": job.pk, "status": "expired", "result": None, "error": "报表批次已过期，请重新查询。"})
    return success_response(serialize_job(job))


@shared_task(soft_time_limit=110, time_limit=120, ignore_result=True)
def run_analysis(job_id):
    claimed = ReportAnalysisJob.objects.filter(pk=job_id, config__dataset__in=list(METRICS), status="queued", worker_active=False, expires_at__gt=timezone.now()).update(status="running", worker_active=True)
    if not claimed:
        return
    job = ReportAnalysisJob.objects.select_related("requested_by", "tenant").get(pk=job_id)
    def check_active():
        if not ReportAnalysisJob.objects.filter(pk=job_id, status="running", expires_at__gt=timezone.now()).exists():
            raise RuntimeError("Report analysis job was cancelled or expired.")
    try:
        if authorization_key(job.requested_by, job.config) != job.fingerprint:
            raise PermissionDenied()
        request = SimpleNamespace(user=job.requested_by, check_active=check_active)
        check_active()
        result = build_analysis(request, job.config)
        if authorization_key(job.requested_by, job.config) != job.fingerprint:
            raise PermissionDenied()
        result = json.loads(json.dumps(result, cls=DjangoJSONEncoder))
        result["snapshot_id"] = job.pk
        ReportAnalysisJob.objects.filter(pk=job_id, status="running", expires_at__gt=timezone.now()).update(status="completed", result=result)
    except Exception as exc:
        message = "分析未完成，请缩小范围后重试。"
        if isinstance(exc, PermissionDenied):
            message = "权限已变化，请重新查询。"
        elif isinstance(exc, ValidationError):
            message = str(exc.detail)[:240]
        ReportAnalysisJob.objects.filter(pk=job_id, status="running").update(status="failed", error=message)
    finally:
        ReportAnalysisJob.objects.filter(pk=job_id, worker_active=True).update(worker_active=False)


@shared_task(ignore_result=True)
def purge_analysis_jobs():
    # Bounded batches keep cleanup short, even after downtime.
    ids = list(ReportAnalysisJob.objects.filter(expires_at__lte=timezone.now()).values_list("pk", flat=True)[:500])
    ReportAnalysisJob.objects.filter(pk__in=ids).delete()
    from .models import ReportAggregateBlock
    blocks = list(ReportAggregateBlock.objects.filter(expires_at__lte=timezone.now()).values_list("pk", flat=True)[:500])
    ReportAggregateBlock.objects.filter(pk__in=blocks).delete()
