from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import ValidationError

from apps.common.responses import success_response
from apps.workflows.models import CollaborationEvent
from apps.workflows.serializers import CollaborationEventSerializer
from apps.workflows.services import receive_mock_collaboration_event
from apps.permissions.api_permissions import (
    IsIntegrationCredentialRotator,
    IsIntegrationManager,
    IsIntegrationReadOrManage,
    IsIntegrationRunner,
    IsIntegrationViewer,
)

from .credential_service import mask_credentials, rotate_credentials
from .models import IntegrationAuditLog, PlatformIntegrationConfig, SyncJob, SyncRun
from .serializers import (
    PlatformIntegrationConfigSerializer,
    RotateCredentialsSerializer,
    SyncJobSerializer,
    SyncRunSerializer,
)
from .sync_services import run_sync_job


def health_response(service):
    return success_response({"status": "ok", "service": service})


@api_view(["GET"])
def platform_health(request):
    return health_response("platform")


@api_view(["GET"])
def wechat_health(request):
    return health_response("wechat")


@api_view(["GET"])
def feishu_health(request):
    return health_response("feishu")


def _mock_collaboration_callback(request, channel):
    event, created = receive_mock_collaboration_event(
        channel=channel,
        headers=request.headers,
        payload=request.data,
    )
    return success_response(
        {
            "created": created,
            "duplicate": not created,
            "event": CollaborationEventSerializer(event).data,
            "business_write": False,
        },
        status=201 if created else 200,
    )


@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
def wechat_mock_callback(request):
    return _mock_collaboration_callback(request, CollaborationEvent.Channel.WECHAT)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
def feishu_mock_callback(request):
    return _mock_collaboration_callback(request, CollaborationEvent.Channel.FEISHU)


def _write_audit_log(config, actor, action, result=IntegrationAuditLog.Result.SUCCESS, detail=None):
    return IntegrationAuditLog.objects.create(
        tenant=config.tenant,
        integration_config=config,
        action=action,
        actor=actor,
        result=result,
        masked_detail=detail or {},
    )


def _get_config_for_user(request, pk):
    return get_object_or_404(PlatformIntegrationConfig, pk=pk, tenant=request.user.tenant)


@api_view(["GET", "POST"])
@permission_classes([IsIntegrationReadOrManage])
def integration_config_collection(request):
    if request.method == "GET":
        queryset = PlatformIntegrationConfig.objects.filter(tenant=request.user.tenant)
        serializer = PlatformIntegrationConfigSerializer(queryset, many=True)
        return success_response(serializer.data)

    serializer = PlatformIntegrationConfigSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    config = serializer.save(tenant=request.user.tenant, created_by=request.user)
    _write_audit_log(
        config,
        request.user,
        "create",
        detail={
            "platform": config.platform,
            "account_alias": config.account_alias,
            "environment": config.environment,
            "credential_mask": mask_credentials(request.data.get("credentials", {})),
        },
    )
    return success_response(PlatformIntegrationConfigSerializer(config).data, status=201)


@api_view(["GET", "PATCH"])
@permission_classes([IsIntegrationReadOrManage])
def integration_config_detail(request, pk):
    config = _get_config_for_user(request, pk)
    if request.method == "GET":
        return success_response(PlatformIntegrationConfigSerializer(config).data)

    serializer = PlatformIntegrationConfigSerializer(config, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    config = serializer.save()
    _write_audit_log(
        config,
        request.user,
        "update",
        detail={
            "platform": config.platform,
            "account_alias": config.account_alias,
            "environment": config.environment,
            "status": config.status,
        },
    )
    return success_response(PlatformIntegrationConfigSerializer(config).data)


@api_view(["POST"])
@permission_classes([IsIntegrationCredentialRotator])
def rotate_integration_credentials(request, pk):
    config = _get_config_for_user(request, pk)
    serializer = RotateCredentialsSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    rotate_credentials(
        config,
        serializer.validated_data["credentials"],
        serializer.validated_data["credential_key_version"],
        request.user,
    )
    _write_audit_log(
        config,
        request.user,
        "rotate_credentials",
        detail={
            "credential_key_version": config.credential_key_version,
            "credential_fingerprint": config.credential_fingerprint,
            "credential_mask": mask_credentials(serializer.validated_data["credentials"]),
        },
    )
    return success_response(PlatformIntegrationConfigSerializer(config).data)


@api_view(["POST"])
@permission_classes([IsIntegrationManager])
def disable_integration_config(request, pk):
    config = _get_config_for_user(request, pk)
    config.status = PlatformIntegrationConfig.Status.DISABLED
    config.save(update_fields=["status", "updated_at"])
    _write_audit_log(config, request.user, "disable", detail={"status": config.status})
    return success_response(PlatformIntegrationConfigSerializer(config).data)


@api_view(["POST"])
@permission_classes([IsIntegrationManager])
def verify_integration_config(request, pk):
    config = _get_config_for_user(request, pk)
    if config.environment == PlatformIntegrationConfig.Environment.PRODUCTION:
        _write_audit_log(
            config,
            request.user,
            "verify",
            result=IntegrationAuditLog.Result.BLOCKED,
            detail={"environment": config.environment, "reason": "production_verify_blocked"},
        )
        raise ValidationError("Production connection verification is not allowed in phase 2.")
    return success_response({"status": "mock_only", "platform": config.platform})


@api_view(["GET", "POST"])
@permission_classes([IsIntegrationReadOrManage])
def sync_job_collection(request):
    if request.method == "GET":
        queryset = SyncJob.objects.filter(tenant=request.user.tenant).select_related("integration_config")
        return success_response(SyncJobSerializer(queryset, many=True, context={"request": request}).data)

    serializer = SyncJobSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    job = serializer.save(tenant=request.user.tenant)
    return success_response(SyncJobSerializer(job, context={"request": request}).data, status=201)


@api_view(["GET"])
@permission_classes([IsIntegrationViewer])
def sync_run_collection(request):
    queryset = SyncRun.objects.filter(tenant=request.user.tenant).select_related("sync_job")
    return success_response(SyncRunSerializer(queryset, many=True).data)


@api_view(["GET"])
@permission_classes([IsIntegrationViewer])
def sync_run_detail(request, pk):
    sync_run = get_object_or_404(SyncRun, pk=pk, tenant=request.user.tenant)
    return success_response(SyncRunSerializer(sync_run).data)


@api_view(["POST"])
@permission_classes([IsIntegrationRunner])
def run_mock_sync_job(request, pk):
    sync_job = get_object_or_404(SyncJob, pk=pk, tenant=request.user.tenant)
    run, created = run_sync_job(sync_job, idempotency_key=request.data.get("idempotency_key"))
    return success_response({"created": created, "run": SyncRunSerializer(run).data})


@api_view(["POST"])
@permission_classes([IsIntegrationManager])
def disable_sync_job(request, pk):
    sync_job = get_object_or_404(SyncJob, pk=pk, tenant=request.user.tenant)
    sync_job.is_enabled = False
    sync_job.status = SyncJob.Status.DISABLED
    sync_job.save(update_fields=["is_enabled", "status", "updated_at"])
    return success_response(SyncJobSerializer(sync_job, context={"request": request}).data)
