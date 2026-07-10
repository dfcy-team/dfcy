from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError

from apps.common.responses import success_response
from apps.permissions.api_permissions import IsIntegrationAdmin

from .credential_service import mask_credentials, rotate_credentials
from .models import IntegrationAuditLog, PlatformIntegrationConfig
from .serializers import PlatformIntegrationConfigSerializer, RotateCredentialsSerializer


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
@permission_classes([IsIntegrationAdmin])
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
@permission_classes([IsIntegrationAdmin])
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
@permission_classes([IsIntegrationAdmin])
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
@permission_classes([IsIntegrationAdmin])
def disable_integration_config(request, pk):
    config = _get_config_for_user(request, pk)
    config.status = PlatformIntegrationConfig.Status.DISABLED
    config.save(update_fields=["status", "updated_at"])
    _write_audit_log(config, request.user, "disable", detail={"status": config.status})
    return success_response(PlatformIntegrationConfigSerializer(config).data)


@api_view(["POST"])
@permission_classes([IsIntegrationAdmin])
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
