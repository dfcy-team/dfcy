"""BEST configuration uses the existing integration custody and warehouse binding."""
from urllib.parse import urlsplit

from django.db import transaction
from django.conf import settings
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.common.exceptions import get_scoped_object_or_404, StateConflict
from apps.common.responses import success_response
from apps.masterdata.models import WarehouseMaster
from apps.permissions.services import check_user_permission
from apps.permissions.ui_p6_scopes import integration_values_allowed
from apps.tenants.models import Tenant
from .credential_service import rotate_config_secrets
from .custody import CustodyError
from .models import PlatformIntegrationConfig, WarehouseAuthorization, SyncJob, IntegrationAuditLog
from .subject_access_service import _warehouse_provider
from .warehouse_authorization_service import bind_warehouse_authorization


def validate_gateway(value):
    from .best_glink import GATEWAYS
    if value not in GATEWAYS.values():
        raise ValidationError("百世网关由后台按环境维护；旧仓配2.0配置须重新保存并验证。")
    return value


class BestAccessInput(serializers.Serializer):
    partner_id = serializers.CharField(max_length=64)
    partner_key = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=4096, trim_whitespace=False)
    customer_code = serializers.CharField(max_length=64)
    version = serializers.IntegerField(min_value=0)
    idempotency_key = serializers.CharField(min_length=8, max_length=120)

    def validate_partner_key(self, value):
        if value and not value.strip():
            raise ValidationError("密钥不能只包含空白字符。")
        return value


def access_payload(binding):
    config = binding.integration_config if binding else None
    values = config.platform_config if config else {}
    return {"partner_id": values.get("partner_id", ""), "customer_code": values.get("customer_code", ""),
        "gateway": values.get("api_host", ""), "warehouse_code": binding.external_warehouse_code if binding else "",
        "key_configured": bool(config and config.credential_id), "version": config.config_version if config else 0,
        "authorization_id": binding.pk if binding else None,
        "status": binding.validation_status if binding else "incomplete",
        "last_verified_at": binding.last_verified_at if binding else None,
        "network_enabled": bool(config and config.network_enabled),
        "execution_enabled": getattr(settings, "BEST_ECAPI_ENABLED", False) is True,
        "message": "配置保存不代表已连接；不会自动执行仓库同步。"}


@sensitive_variables()
@transaction.atomic
def save_access(*, actor, warehouse, data):
    Tenant.objects.select_for_update().get(pk=actor.tenant_id)
    current = WarehouseAuthorization.objects.select_for_update().filter(tenant_id=actor.tenant_id,
        warehouse=warehouse, status="active").select_related("integration_config").first()
    if current and current.provider != "best_ecapi":
        raise StateConflict("仓库仍绑定其他服务商，请先在原接入中解除绑定。")
    config = PlatformIntegrationConfig.objects.select_for_update().get(pk=current.integration_config_id) if current else None
    if config and WarehouseAuthorization.objects.filter(integration_config=config, status="active").exclude(warehouse=warehouse).exists():
        raise StateConflict("该百世配置正被其他仓库共享，请先拆分配置后再修改。")
    if data["version"] != (config.config_version if config else 0):
        raise StateConflict("接入配置已更新，请刷新后重试。")
    if not config and not data.get("partner_key"):
        raise ValidationError("首次配置必须填写 partnerKey。")
    if config and config.platform_config.get("partner_id") != data["partner_id"] and not data.get("partner_key"):
        raise ValidationError("更换 partnerID 时必须填写对应的 partnerKey。")
    if not config:
        config = PlatformIntegrationConfig.objects.create(tenant_id=actor.tenant_id, platform="best_ecapi",
            account_alias=f"BEST-WH-{warehouse.pk}", environment="production", status="draft", created_by=actor)
    from .best_glink import gateway_for
    values = {"api_type": "inventory", "partner_id": data["partner_id"], "customer_code": data["customer_code"],
        "api_host": gateway_for(config.environment), "site_code": warehouse.country_code}
    if config.platform_config.get("business_time_zone") == "Asia/Shanghai":
        values["business_time_zone"] = "Asia/Shanghai"
    if data.get("partner_key"):
        config, _ = rotate_config_secrets(config, credentials={"secret": data["partner_key"]},
            version=config.config_version, reason="维护百世仓库接入", actor=actor,
            idempotency_key=data["idempotency_key"])
    config.platform_config = values
    config.regions = [warehouse.country_code]
    config.contract_version = "glink"
    config.status = "configured"
    config.network_enabled = config.sync_read_enabled = config.sync_write_enabled = False
    config.last_verified_at = None
    config.config_version += 1
    config.save()
    binding, _, _ = bind_warehouse_authorization(actor=actor, warehouse=warehouse, integration_config=config,
        external_warehouse_code="", replace=bool(current),
        expected_authorization_id=current.pk if current else None)
    binding.validation_status = "pending"
    binding.last_verified_at = None
    binding.last_error_code = ""
    binding.save(update_fields=["validation_status", "last_verified_at", "last_error_code", "updated_at"])
    SyncJob.objects.filter(warehouse_authorization=binding).update(is_enabled=False, status="disabled", next_run_at=None)
    IntegrationAuditLog.objects.create(tenant_id=actor.tenant_id, integration_config=config, actor=actor,
        action="best_warehouse_configure", result="success", masked_detail={"warehouse_id": warehouse.pk, "network_called": False})
    binding.integration_config = config
    return binding


@sensitive_post_parameters("partner_key")
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def access(request, pk):
    warehouse = get_scoped_object_or_404(WarehouseMaster.objects.filter(tenant_id=request.user.tenant_id)
        .select_related("service_platform"), pk=pk)
    current = WarehouseAuthorization.objects.filter(tenant_id=request.user.tenant_id, warehouse=warehouse,
        provider="best_ecapi", status="active").first()
    permissions = ["integrations.view", "integrations.warehouse.view"]
    if request.method == "POST":
        permissions += ["integrations.manage", "integrations.warehouse.authorize"]
    for permission in permissions:
        if not check_user_permission(request.user, permission) or not integration_values_allowed(request.user, permission,
                platform="best_ecapi", regions=[warehouse.country_code], warehouse_id=warehouse.pk, environment="production",
                config_id=current.integration_config_id if current else None):
            raise PermissionDenied("没有该仓库接入配置的操作权限。")
    try:
        provider = _warehouse_provider(warehouse)
    except ValueError:
        raise ValidationError("请先将仓库绑定到启用的百世仓储服务平台。") from None
    if provider != "best_ecapi" or warehouse.status != "active":
        raise ValidationError("仅启用的百世仓库支持此接入方式。")
    if request.method == "POST":
        serializer = BestAccessInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            binding = save_access(actor=request.user, warehouse=warehouse, data=serializer.validated_data)
        except CustodyError:
            raise ValidationError("密钥托管保存失败，配置未更改。") from None
    else:
        binding = WarehouseAuthorization.objects.filter(tenant_id=request.user.tenant_id, warehouse=warehouse,
            provider="best_ecapi", status="active").select_related("integration_config").first()
    return success_response(access_payload(binding))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def check_connection(request, pk):
    return check_connection_for_warehouse(request, pk)


def check_connection_for_warehouse(request, pk, *, authorization_id=None):
    from django.utils import timezone
    from .best_glink import BestGlinkClient
    record = get_scoped_object_or_404(WarehouseAuthorization.objects.filter(tenant_id=request.user.tenant_id,
        warehouse_id=pk, provider="best_ecapi", status="active").select_related("warehouse", "integration_config"))
    if authorization_id is not None and record.pk != authorization_id:
        raise StateConflict("仓库授权已变化，请刷新后重新校验。")
    for permission in ("integrations.warehouse.view", "integrations.run_live_readonly",
                       "integrations.manage", "integrations.warehouse.authorize"):
        if not check_user_permission(request.user, permission) or not integration_values_allowed(request.user, permission,
                platform="best_ecapi", regions=[record.external_warehouse_region], warehouse_id=pk,
                config_id=record.integration_config_id, environment=record.integration_config.environment):
            raise PermissionDenied("没有该仓库只读验证权限。")
    selected = serializers.CharField(max_length=64, allow_blank=True).run_validation(request.data.get("warehouse_code", ""))
    client = BestGlinkClient(record.integration_config, record, verification_only=True)
    client.preflight()
    version = record.integration_config.config_version
    try:
        warehouses = client.discover_warehouses()
        if not warehouses:
            raise ValidationError("当前客户没有可绑定的百世仓库。")
    except Exception:
        with transaction.atomic():
            config = PlatformIntegrationConfig.objects.select_for_update().get(pk=record.integration_config_id)
            if config.config_version == version:
                WarehouseAuthorization.objects.filter(pk=record.pk, status="active").update(
                    validation_status="failed", last_verified_at=None, last_error_code="BEST_READ_CHECK_FAILED")
                config.status = "configured"
                config.last_verified_at = None
                config.save(update_fields=["status", "last_verified_at", "updated_at"])
        raise ValidationError("百世只读校验失败；未同步库存，请核对配置后重试。") from None
    if not selected and len(warehouses) > 1:
        return success_response({**access_payload(record), "warehouses": warehouses, "selection_required": True})
    selected = selected or warehouses[0]["code"]
    if selected not in {item["code"] for item in warehouses}:
        raise ValidationError("请选择当前授权返回的仓库。")
    chosen = next(item for item in warehouses if item["code"] == selected)
    mismatch = str(chosen.get("country") or "").upper() != record.warehouse.country_code.upper()
    if mismatch:
        confirmed = serializers.BooleanField().run_validation(request.data.get("confirm_country_mismatch", False))
        if not confirmed or request.data.get("version") != version or request.data.get("confirmed_country") != chosen.get("country"):
            return success_response({**access_payload(record), "warehouses": warehouses, "selection_required": True,
                "country_confirmation_required": True, "local_country": record.warehouse.country_code})
    with transaction.atomic():
        Tenant.objects.select_for_update().get(pk=request.user.tenant_id)
        config = PlatformIntegrationConfig.objects.select_for_update().get(pk=record.integration_config_id)
        if config.config_version != version:
            raise StateConflict("校验期间配置发生变化，请重新校验。")
        if WarehouseAuthorization.objects.filter(tenant_id=record.tenant_id, provider="best_ecapi", status="active",
                external_warehouse_region=record.external_warehouse_region, external_warehouse_code=selected).exclude(pk=record.pk).exists():
            raise StateConflict("该百世仓库已绑定其他本地仓库。")
        record, _, _ = bind_warehouse_authorization(actor=request.user, warehouse=record.warehouse,
            integration_config=config, external_warehouse_code=selected, replace=True, expected_authorization_id=record.pk)
        verified_at = timezone.now()
        updated = WarehouseAuthorization.objects.filter(pk=record.pk, status="active").update(
            validation_status="verified", last_verified_at=verified_at, last_error_code="")
        if not updated:
            raise StateConflict("校验期间授权发生变化，请重新校验。")
        config.status = "verified"
        config.last_verified_at = verified_at
        config.save(update_fields=["status", "last_verified_at", "updated_at"])
    IntegrationAuditLog.objects.create(tenant_id=record.tenant_id, integration_config=record.integration_config,
        actor=request.user, action="best_warehouse_check", result="success", masked_detail={"warehouse_id": pk,
            "warehouse_code": selected, "config_version": version, "local_country": record.warehouse.country_code,
            "provider_country": chosen.get("country", ""), "provider_time_zone": chosen.get("time_zone", ""),
            "country_mismatch_confirmed": mismatch})
    record.refresh_from_db()
    return success_response({**access_payload(record), "warehouses": warehouses, "selection_required": False})
