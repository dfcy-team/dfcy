from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.common.responses import success_response
from apps.permissions.api_permissions import IsWarehouseAuthorizationAuthorizer, IsIntegrationLiveReadonlyRunner
from apps.common.exceptions import get_scoped_object_or_404
from apps.permissions.services import check_user_permission
from apps.permissions.ui_p6_scopes import integration_values_allowed

from .custody import CustodyError
from .models import WarehouseAuthorization
from .oauth_errors import OAUTH_AUTH_REJECTED, OAuthFlowError
from .readonly_clients import JifengWmsReadonlyClient
from .serializers import WarehouseAuthorizationSerializer
from .views import _warehouse_authorization_queryset, _get_config_for_user
from .warehouse_credential_service import save_warehouse_credentials, authorize_warehouse, refresh_warehouse_authorization


class WarehouseCredentialsInput(serializers.Serializer):
    email = serializers.EmailField()
    token = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=4096, trim_whitespace=False)


@api_view(["POST"])
@permission_classes([IsWarehouseAuthorizationAuthorizer])
def warehouse_credentials(request, pk):
    record = get_scoped_object_or_404(_warehouse_authorization_queryset(request, "integrations.warehouse.authorize"), pk=pk)
    serializer = WarehouseCredentialsInput(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        record = save_warehouse_credentials(actor=request.user, authorization=record, **serializer.validated_data)
    except CustodyError:
        raise ValidationError("仓库凭据加密保存失败，原配置未更改。") from None
    return success_response(WarehouseAuthorizationSerializer(record).data)


@api_view(["POST"])
@permission_classes([IsWarehouseAuthorizationAuthorizer])
def warehouse_first_authorization(request, pk):
    if request.data.get("confirmed") is not True:
        raise ValidationError("首次授权将消耗一次性 Token，请明确确认。")
    record = get_scoped_object_or_404(_warehouse_authorization_queryset(request, "integrations.warehouse.authorize"), pk=pk)
    record = authorize_warehouse(actor=request.user, authorization=record)
    return success_response({"authorization": WarehouseAuthorizationSerializer(record).data, "connected": False})


@api_view(["POST"])
@permission_classes([IsIntegrationLiveReadonlyRunner])
def warehouse_readonly_check(request, pk):
    if not check_user_permission(request.user, "integrations.warehouse.view"):
        raise PermissionDenied("当前角色没有查看仓库 API 授权的权限。")
    record = get_scoped_object_or_404(_warehouse_authorization_queryset(request, "integrations.warehouse.view"), pk=pk)
    config = _get_config_for_user(request, record.integration_config_id, "integrations.run_live_readonly")
    if record.status != WarehouseAuthorization.Status.ACTIVE:
        raise ValidationError("仓库授权已失效，请刷新页面。")
    if not integration_values_allowed(request.user, "integrations.run_live_readonly", platform=config.platform,
            environment=config.environment, regions=[record.external_warehouse_region], config_id=config.pk,
            resource_type="inventory_snapshot", warehouse_id=record.warehouse_id):
        raise PermissionDenied("该仓库超出只读连接校验的数据范围。")
    # No job is needed: validation must precede task creation. Do not exchange
    # or consume the bootstrap token here. Only the inventory read is allowed.
    try:
        client = JifengWmsReadonlyClient(config, record)
        page = client.fetch_inventory(None, {"page_size": 1})
    except Exception as exc:
        WarehouseAuthorization.objects.filter(pk=record.pk, bootstrap_credential_id=record.bootstrap_credential_id,
            token_id=record.token_id, integration_config__config_version=config.config_version).update(
            validation_status=WarehouseAuthorization.ValidationStatus.FAILED,
            last_verified_at=None, last_error_code="JIFENG_READONLY_CHECK_FAILED",
        )
        if isinstance(exc, ValidationError):
            raise
        if isinstance(exc, OAuthFlowError) and exc.controlled_code == OAUTH_AUTH_REJECTED:
            raise ValidationError("极风认证失败或账号无访问权限，请核对仓库授权。") from None
        raise ValidationError("连接校验失败：网络异常或凭据无法读取，请检查网络白名单及授权。") from None
    checked_at = timezone.now()
    updated = WarehouseAuthorization.objects.filter(
        pk=record.pk, status=WarehouseAuthorization.Status.ACTIVE,
        bootstrap_credential_id=record.bootstrap_credential_id, token_id=record.token_id,
        integration_config__config_version=config.config_version,
    ).update(validation_status=WarehouseAuthorization.ValidationStatus.VERIFIED, last_verified_at=checked_at, last_error_code="")
    if not updated:
        raise ValidationError("校验期间仓库授权已变化，请重新校验。")
    return success_response({"connected": True, "checked_at": checked_at, "sample_count": len(page["records"])})


@api_view(["POST"])
@permission_classes([IsWarehouseAuthorizationAuthorizer])
def warehouse_refresh_authorization(request, pk):
    record = get_scoped_object_or_404(_warehouse_authorization_queryset(request, "integrations.warehouse.authorize"), pk=pk)
    record = refresh_warehouse_authorization(actor=request.user, authorization=record)
    return success_response({"authorization": WarehouseAuthorizationSerializer(record).data, "connected": False})
