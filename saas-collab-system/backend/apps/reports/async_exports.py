"""Short-lived asynchronous preparation for the existing audited export service."""
import hashlib
import json
from datetime import timedelta

from celery import shared_task
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, Throttled, ValidationError

from apps.common.responses import success_response
from apps.common.exceptions import DataScopeDenied
from apps.tenants.models import Tenant
from .export_services import REPORT_CATALOG, _scope_snapshot, _self_service_access, create_export_request, validate_export_access
from .models import ReportAnalysisJob
from .permissions import IsReportExporter, IsReportViewer
from .serializers import ReportExportCreateSerializer, ReportExportRequestSerializer


def _export_scope(user, report_type, filters):
    """Capture current relevant scopes so a stale job cannot reveal its result."""
    codes = {"reports.view", "reports.export", REPORT_CATALOG[report_type]["required_permission"]}
    scopes = {code: _scope_snapshot(user, code) for code in sorted(codes)}
    if report_type == "sales_details":
        scopes["sales_management.export"] = _scope_snapshot(user, "sales_management.export", "sales_management.sales")
    elif report_type == "self_service":
        # This validates the current dataset permissions and includes their exact scope snapshots.
        _, _, scopes = _self_service_access(user, (filters or {}).get("config", {}))
    return scopes


def export_fingerprint(user, report_type, filters):
    config = {"kind": "export", "report_type": report_type, "filters": filters or {}}
    scope = _export_scope(user, report_type, filters or {})
    payload = ["export-v1", user.tenant_id, user.pk, config, scope]
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
    return config, fingerprint


def serialize_export_job(job):
    result = job.result or {}
    return {
        "id": job.pk,
        "status": job.status,
        "error": job.error,
        "export": result.get("export") if job.status == "completed" else None,
        "expires_at": job.expires_at,
    }


@api_view(["GET", "POST"])
@permission_classes([IsReportExporter])
def export_job_collection(request):
    if request.method == "GET":
        jobs = ReportAnalysisJob.objects.filter(tenant=request.user.tenant, requested_by=request.user, config__kind="export", expires_at__gt=timezone.now()).order_by("-id")[:20]
        visible = []
        for job in jobs:
            try:
                if export_fingerprint(request.user, job.config["report_type"], job.config.get("filters", {}))[1] == job.fingerprint:
                    visible.append({**serialize_export_job(job), "report_type": job.config["report_type"]})
            except PermissionDenied:
                continue
        return success_response(visible)
    serializer = ReportExportCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    report_type = serializer.validated_data["report_type"]
    filters = serializer.validated_data.get("filters", {})
    if not isinstance(filters, dict):
        raise ValidationError("导出筛选条件必须为对象。")
    validate_export_access(request.user, report_type)
    config, fingerprint = export_fingerprint(request.user, report_type, filters)
    now = timezone.now()
    with transaction.atomic():
        Tenant.objects.select_for_update().get(pk=request.user.tenant_id)
        active = ReportAnalysisJob.objects.filter(tenant=request.user.tenant, expires_at__gt=now)
        existing = active.filter(requested_by=request.user, fingerprint=fingerprint, status__in=["queued", "running"]).order_by("-pk").first()
        if existing:
            return success_response(serialize_export_job(existing), status=202)
        pending = active.filter(Q(status__in=["queued", "running"]) | Q(worker_active=True))
        if pending.filter(requested_by=request.user).count() >= 3 or pending.count() >= 20:
            raise Throttled(detail="后台导出任务较多，请等待已有任务完成或取消后重试。")
        job = ReportAnalysisJob.objects.create(
            tenant=request.user.tenant,
            requested_by=request.user,
            config=config,
            fingerprint=fingerprint,
            expires_at=now + timedelta(minutes=15),
        )

        def enqueue():
            try:
                run_export.apply_async(args=[job.pk], retry=False)
            except Exception:
                ReportAnalysisJob.objects.filter(pk=job.pk, status="queued").update(
                    status="failed", error="导出队列暂不可用，请稍后重试。"
                )

        transaction.on_commit(enqueue)
    job.refresh_from_db()
    return success_response(serialize_export_job(job), status=202)


@api_view(["GET", "DELETE"])
@permission_classes([IsReportViewer])
def export_job_detail(request, pk):
    job = get_object_or_404(
        ReportAnalysisJob.objects.filter(config__kind="export"),
        pk=pk,
        tenant=request.user.tenant,
        requested_by=request.user,
    )
    if request.method == "DELETE":
        ReportAnalysisJob.objects.filter(pk=job.pk, status__in=["queued", "running"]).update(
            status="cancelled", result=None, error=""
        )
        job.refresh_from_db()
        return success_response(serialize_export_job(job))
    config = job.config
    current = export_fingerprint(request.user, config["report_type"], config.get("filters", {}))[1]
    if current != job.fingerprint:
        raise PermissionDenied("导出权限或数据范围已变化，请重新提交导出。")
    if job.expires_at <= timezone.now():
        return success_response({"id": job.pk, "status": "expired", "result": None, "error": "导出任务已过期，请重新提交。"})
    return success_response(serialize_export_job(job))


@shared_task(soft_time_limit=110, time_limit=120, ignore_result=True)
def run_export(job_id):
    claimed = ReportAnalysisJob.objects.filter(
        pk=job_id, config__kind="export", status="queued", expires_at__gt=timezone.now()
    ).update(status="running", worker_active=True)
    if not claimed:
        return
    job = ReportAnalysisJob.objects.select_related("requested_by", "tenant").get(pk=job_id)
    try:
        config = job.config
        report_type, filters = config["report_type"], config.get("filters", {})
        validate_export_access(job.requested_by, report_type)
        if export_fingerprint(job.requested_by, report_type, filters)[1] != job.fingerprint:
            raise PermissionDenied()
        export_request = create_export_request(user=job.requested_by, report_type=report_type, filters=filters)
        if export_fingerprint(job.requested_by, report_type, filters)[1] != job.fingerprint:
            raise PermissionDenied()
        result = {"export": ReportExportRequestSerializer(export_request).data}
        result = json.loads(json.dumps(result, cls=DjangoJSONEncoder))
        ReportAnalysisJob.objects.filter(pk=job_id, status="running", expires_at__gt=timezone.now()).update(
            status="completed", result=result
        )
    except Exception as exc:
        message = "导出未完成，请稍后重试。"
        if isinstance(exc, DataScopeDenied):
            message = str(exc.detail)[:240]
        elif isinstance(exc, PermissionDenied):
            message = "权限已变化，请重新提交导出。"
        elif hasattr(exc, "detail"):
            message = str(exc.detail)[:240]
        ReportAnalysisJob.objects.filter(pk=job_id, status="running").update(status="failed", error=message)
    finally:
        ReportAnalysisJob.objects.filter(pk=job_id, worker_active=True).update(worker_active=False)
