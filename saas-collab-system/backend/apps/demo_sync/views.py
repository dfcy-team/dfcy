import io
import json
import zipfile
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated, AllowAny

from apps.common.responses import success_response, error_response
from apps.permissions.services import check_user_permission
from .contracts import enabled, RESOURCES, MAX_WINDOW_DAYS
from .models import SyncEnvironment, SnapshotBatch, SyncAudit
from .serializers import EnvironmentSerializer, BatchSerializer, BatchInputSerializer


def require(user, action):
    if not user.is_active or user.user_type != "internal" or not check_user_permission(user, f"system.demo_sync.{action}"):
        raise PermissionDenied("没有开发环境数据同步权限。")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def local_authorize(request):
    if not getattr(settings, "DEMO_LOCAL_UPDATE_ENABLED", False):
        return error_response("LOCAL_UPDATE_DISABLED", "本实例不提供本地更新。", status=404)
    require(request.user, "run")
    require(request.user, "download")
    if (request.user.pk != getattr(settings, "DEMO_LOCAL_ACTOR_ID", None)
            or request.user.tenant_id != getattr(settings, "DEMO_LOCAL_TENANT_ID", None)):
        raise PermissionDenied("只允许已配置的本地开发者更新。")
    return success_response({"enabled": True})


@api_view(["GET"])
@permission_classes([AllowAny])
def local_health(request):
    if not getattr(settings, "DEMO_LOCAL_UPDATE_ENABLED", False):
        return error_response("LOCAL_UPDATE_DISABLED", "本实例不提供本地更新。", status=404)
    from django.db import connection
    from .models import ImportedSnapshotReceipt
    # Exercise the actual DB/schema instead of accepting a process-only health response.
    ImportedSnapshotReceipt.objects.exists()
    if not str(connection.settings_dict["NAME"]).startswith("saas_collab_demo_"):
        return error_response("LOCAL_DATABASE_REJECTED", "不是本地 Demo 数据库。", status=503)
    return success_response({"generation": getattr(settings, "DEMO_LOCAL_GENERATION", "")})


def environments_for(user):
    require(user, "view")
    qs = SyncEnvironment.objects.filter(tenant_id=user.tenant_id).select_related("owner")
    return qs if check_user_permission(user, "system.demo_sync.manage") else qs.filter(owner=user)


def batches_for(user):
    return SnapshotBatch.objects.filter(tenant_id=user.tenant_id, environment__in=environments_for(user)).select_related("environment")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def options(request):
    require(request.user, "view")
    return success_response({"enabled": enabled(), "resources": [{"code": k, "label": v} for k, v in RESOURCES.items()], "max_window_days": MAX_WINDOW_DAYS})


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def environments(request):
    if request.method == "GET":
        return success_response({"results": EnvironmentSerializer(environments_for(request.user)[:200], many=True).data})
    require(request.user, "manage")
    form = EnvironmentSerializer(data=request.data, context={"request": request})
    form.is_valid(raise_exception=True)
    with transaction.atomic():
        env = form.save(tenant_id=request.user.tenant_id)
        SyncAudit.objects.create(tenant_id=request.user.tenant_id, actor=request.user, event="environment.created")
    return success_response(EnvironmentSerializer(env).data, status=201)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def environment_status(request, pk):
    require(request.user, "manage")
    if set(request.data) != {"active"} or type(request.data["active"]) is not bool:
        raise ValidationError("仅允许设置 active 布尔值；修改范围请创建新环境。")
    with transaction.atomic():
        env = get_object_or_404(SyncEnvironment.objects.select_for_update(), pk=pk, tenant_id=request.user.tenant_id)
        env.active = request.data["active"]
        env.save(update_fields=["active"])
        if not env.active:
            queued = list(env.batches.filter(status="queued"))
            for batch in queued:
                batch.status, batch.error_code, batch.finished_at = "failed", "ENVIRONMENT_REVOKED", timezone.now()
                batch.save(update_fields=["status", "error_code", "finished_at"])
                SyncAudit.objects.create(tenant_id=batch.tenant_id, batch=batch, actor=request.user, event="batch.revoked")
        SyncAudit.objects.create(tenant_id=request.user.tenant_id, actor=request.user, event="environment.enabled" if env.active else "environment.revoked")
    return success_response(EnvironmentSerializer(env).data)


def queue_batch(user, env, start, end):
    if not enabled():
        return error_response("DEMO_SYNC_DISABLED", "开发数据同步尚未启用，请先配置内网同步服务。", status=503)
    with transaction.atomic():
        env = SyncEnvironment.objects.select_for_update().get(pk=env.pk)
        if not env.active:
            raise ValidationError("开发环境已停用。")
        if env.batches.filter(status__in=["queued", "running"]).exists():
            raise ValidationError("此环境已有排队或执行中的任务。")
        batch = SnapshotBatch.objects.create(tenant_id=user.tenant_id, environment=env, requested_by=user, resources=env.resources, date_from=start, date_to=end)
        SyncAudit.objects.create(tenant_id=user.tenant_id, batch=batch, actor=user, event="batch.queued")
    return success_response(BatchSerializer(batch).data, status=202)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def batches(request):
    if request.method == "GET":
        return success_response({"results": BatchSerializer(batches_for(request.user)[:200], many=True).data})
    require(request.user, "run")
    form = BatchInputSerializer(data=request.data)
    form.is_valid(raise_exception=True)
    data = form.validated_data
    env = get_object_or_404(environments_for(request.user), pk=data["environment_id"])
    return queue_batch(request.user, env, data["date_from"], data["date_to"])


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def batch_detail(request, pk):
    batch = get_object_or_404(batches_for(request.user), pk=pk)
    data = BatchSerializer(batch).data
    data["audit"] = list(batch.audit.values("event", "created_at")[:100])
    return success_response(data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def retry(request, pk):
    require(request.user, "run")
    batch = get_object_or_404(batches_for(request.user), pk=pk)
    if batch.status == "running":
        with transaction.atomic():
            batch = SnapshotBatch.objects.select_for_update().select_related("environment").get(pk=batch.pk)
            heartbeat = batch.heartbeat_at or batch.started_at
            if batch.status == "running" and heartbeat and heartbeat < timezone.now() - timedelta(minutes=10):
                batch.status, batch.error_code, batch.finished_at = "failed", "WORKER_LEASE_EXPIRED", timezone.now()
                batch.save(update_fields=["status", "error_code", "finished_at"])
                SyncAudit.objects.create(tenant_id=batch.tenant_id, batch=batch, actor=request.user, event="batch.lease_expired")
    if batch.status != "failed":
        raise ValidationError("仅失败或超过 10 分钟无心跳的任务可重新创建快照。")
    return queue_batch(request.user, batch.environment, batch.date_from, batch.date_to)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def download(request, pk):
    require(request.user, "download")
    batch = get_object_or_404(batches_for(request.user), pk=pk)
    if not enabled() or not batch.environment.active or batch.status != "ready":
        raise ValidationError("批次未就绪或环境已停用。")
    from .service import artifact_path, verified_bundle_files, SyncFailure
    try:
        folder = artifact_path(batch.pk)
        files = verified_bundle_files(folder)
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("scope_key") != f"{batch.tenant_id}:{batch.environment_id}":
            raise SyncFailure("ARTIFACT_SCOPE_MISMATCH")
    except (SyncFailure, OSError, ValueError, TypeError):
        return error_response("ARTIFACT_INVALID", "快照文件校验失败，请重新创建批次。", status=409)
    # A bounded spool avoids retaining a complete snapshot in HTTP worker RAM.
    import tempfile
    stream = tempfile.SpooledTemporaryFile(max_size=4 * 1024 * 1024)
    try:
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                archive.write(path, arcname=path.name)
        stream.seek(0)
        SyncAudit.objects.create(tenant_id=batch.tenant_id, batch=batch, actor=request.user, event="batch.downloaded")
        return FileResponse(stream, as_attachment=True, filename=f"demo-snapshot-{batch.pk}.zip")
    except Exception:
        stream.close()
        raise
