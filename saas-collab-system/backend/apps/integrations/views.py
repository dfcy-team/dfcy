import hashlib
import json
import uuid
from collections import defaultdict

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import connection, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.common.error_codes import ErrorCode
from apps.common.exceptions import DataScopeDenied, IdempotencyConflict, StateConflict, get_scoped_object_or_404
from apps.common.module_gate import is_module_enabled
from apps.common.responses import success_response
from apps.common.query import pagination_query, positive_int
from apps.common.responses import paginated_data
from apps.workflows.models import CollaborationEvent
from apps.workflows.serializers import CollaborationEventSerializer
from apps.workflows.services import receive_mock_collaboration_event
from apps.masterdata.models import WarehouseMaster
from apps.permissions.api_permissions import (
    IsIntegrationAuditViewer,
    IsIntegrationConfigCollectionUser,
    IsIntegrationConfigDetailUser,
    IsIntegrationConfigDisabler,
    IsIntegrationConfigVerifier,
    IsIntegrationCredentialClearer,
    IsIntegrationCredentialRotator,
    IsIntegrationManager,
    IsIntegrationReadOrManage,
    IsIntegrationRunner,
    IsIntegrationLiveReadonlyRunner,
    IsIntegrationViewer,
    IsMarketplaceCredentialRotator,
    IsMarketplaceCapabilityManager,
    IsMarketplaceStoreAuthorizer,
    IsMarketplaceStoreMappingManager,
    IsMarketplaceStoreRevoker,
    IsMarketplaceStoreViewer,
    IsWarehouseAuthorizationAuthorizer,
    IsWarehouseAuthorizationCollectionUser,
    IsWarehouseAuthorizationRevoker,
    IsWarehouseAuthorizationViewer,
)
from apps.permissions.ui_p6_scopes import (
    filter_integration_configs,
    filter_product_mappings,
    filter_store_mappings,
    filter_sync_jobs,
    filter_sync_runs,
    integration_values_allowed,
    filter_store_authorizations,
    filter_warehouse_authorizations,
)
from apps.permissions.services import check_user_permission, get_permission_data_scopes

from .credential_service import (
    clear_config_secrets,
    reject_raw_credential_fields,
    rotate_config_references,
    rotate_config_secrets,
)
from .capability_advice import capability_suggestions
from .custody import CustodyError, get_custody_backend
from .marketplace_oauth_service import (
    complete_marketplace_oauth_callback,
    refresh_marketplace_authorization,
    revoke_marketplace_authorization,
    start_marketplace_oauth,
)
from .models import (
    ConnectionCapability,
    IntegrationAuditLog,
    MarketplaceProductMapping,
    MarketplaceStoreAuthorization,
    MarketplaceStoreMapping,
    PlatformChoices,
    PlatformIntegrationConfig,
    SyncJob,
    SyncAlertIncident,
    SyncRun,
    WarehouseAuthorization,
)
from .platform_schema_service import get_platform_schema
from .readiness_service import (
    BLOCKER_LABELS,
    build_config_readiness,
    build_platform_readiness,
)
from .product_mapping_service import (
    confirm_product_mapping,
    create_product_mapping,
    deactivate_product_mapping,
    suggest_product_mapping,
)
from .serializers import (
    ConnectionCapabilitySerializer,
    ConnectionCapabilityWriteSerializer,
    CredentialClearSerializer,
    CredentialRotateWriteSerializer,
    IntegrationAuditLogSerializer,
    MarketplaceOAuthStartSerializer,
    MarketplaceProductMappingSerializer,
    MarketplaceStoreAuthorizationSerializer,
    MarketplaceStoreMappingSerializer,
    PlatformIntegrationConfigSerializer,
    ProductMappingCreateSerializer,
    ProductMappingUpdateSerializer,
    ReadinessContractRepairSerializer,
    ReadonlyApprovalSerializer,
    RotateCredentialsSerializer,
    StoreMappingCreateSerializer,
    StoreMappingUpdateSerializer,
    SyncJobSerializer,
    SyncAlertIncidentSerializer,
    SyncRunSerializer,
    WarehouseAuthorizationBindSerializer,
    WarehouseAuthorizationSerializer,
    validate_marketplace_callback_url,
)
from .store_mapping_service import create_store_mapping, update_store_mapping
from .adapters import MockPlatformAdapter, get_adapter_for_config
from .sync_services import run_sync_job
from .scheduler import calculate_next_run_at
from .tasks import run_readonly_sync_job
from .workspace_service import integration_workspace
from .subject_access_service import subject_api_access
from .warehouse_authorization_service import (
    bind_warehouse_authorization,
    revoke_warehouse_authorization as revoke_warehouse_authorization_record,
    validate_warehouse_binding,
)

# The dedicated product-mapping permission class is introduced alongside the
# permission catalog.  Keep this import compatible with the pre-catalog
# checkout so migrations and legacy tests can still be run in isolation.
try:
    from apps.permissions.api_permissions import IsMarketplaceProductMappingManager
except ImportError:  # pragma: no cover - removed once the permission catalog is migrated
    IsMarketplaceProductMappingManager = IsMarketplaceStoreMappingManager
from .sync_alerts import acknowledge_incident, add_incident_note, assign_incident, resolve_incident
from .production_settings import get_runtime_setting


def health_response(service):
    return success_response({"status": "ok", "service": service})


@api_view(["GET"])
@permission_classes([IsIntegrationViewer])
def subject_api_access_detail(request):
    subject_type = str(request.query_params.get("subject_type") or "")
    subject_id = positive_int(request.query_params.get("subject_id"), default=None, maximum=2147483647)
    if subject_id is None:
        raise ValidationError("业务主体 ID 不能为空")
    try:
        data = subject_api_access(request.user, subject_type, subject_id)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    return success_response(data)


def _warehouse_authorization_queryset(request, permission_code):
    return filter_warehouse_authorizations(
        request.user,
        WarehouseAuthorization.objects.filter(tenant=request.user.tenant).select_related(
            "warehouse", "integration_config"
        ),
        permission_code,
    )


def _warehouse_binding_request_data(request, *, current=None):
    if not isinstance(request.data, dict):
        raise ValidationError("仓库 API 接入请求必须是 JSON 对象。")
    reject_raw_credential_fields(request.data)
    allowed_fields = {
        "warehouse_id",
        "integration_config_id",
        "replace",
        "expected_authorization_id",
        "idempotency_key",
    }
    unsupported = set(request.data) - allowed_fields
    if unsupported:
        raise ValidationError("仓库 API 接入请求包含不支持的字段。")
    payload = dict(request.data)
    if current is not None:
        supplied_warehouse_id = payload.get("warehouse_id")
        if supplied_warehouse_id is not None:
            try:
                supplied_warehouse_id = int(supplied_warehouse_id)
            except (TypeError, ValueError):
                raise ValidationError({"warehouse_id": "仓库 ID 无效。"}) from None
            if supplied_warehouse_id != current.warehouse_id:
                raise ValidationError("换绑操作不能更改仓库主体。")
        payload["warehouse_id"] = current.warehouse_id
        payload["replace"] = True
        payload["expected_authorization_id"] = current.id
    serializer = WarehouseAuthorizationBindSerializer(data=payload)
    serializer.is_valid(raise_exception=True)
    header_key = str(request.headers.get("Idempotency-Key") or "").strip()
    body_key = str(serializer.validated_data.get("idempotency_key") or "").strip()
    if header_key and body_key and header_key != body_key:
        raise ValidationError("请求头与请求体中的幂等键不一致。")
    data = dict(serializer.validated_data)
    data["idempotency_key"] = header_key or body_key
    return data


def _perform_warehouse_binding(request, data):
    warehouse = get_object_or_404(
        WarehouseMaster.objects.filter(tenant=request.user.tenant),
        pk=data["warehouse_id"],
    )
    integration_config = get_object_or_404(
        PlatformIntegrationConfig.objects.filter(tenant=request.user.tenant),
        pk=data["integration_config_id"],
    )
    if not integration_values_allowed(
        request.user,
        "integrations.warehouse.authorize",
        platform=integration_config.platform,
        environment=integration_config.environment,
        regions=integration_config.regions or [warehouse.country_code],
        config_id=integration_config.id,
        resource_type=SyncJob.ResourceType.INVENTORY_SNAPSHOT,
        warehouse_id=warehouse.id,
    ):
        raise DataScopeDenied(
            "仓库 API 接入操作超出当前角色的数据范围。",
            error_code=ErrorCode.DATA_SCOPE_FORBIDDEN,
        )
    # Run validation before entering the transition so callers receive a
    # precise remediation message and no empty authorization is written.
    validate_warehouse_binding(
        actor=request.user,
        warehouse=warehouse,
        integration_config=integration_config,
    )
    authorization, idempotent, operation = bind_warehouse_authorization(
        actor=request.user,
        warehouse=warehouse,
        integration_config=integration_config,
        replace=data.get("replace", False),
        expected_authorization_id=data.get("expected_authorization_id"),
        idempotency_key=data.get("idempotency_key"),
    )
    return success_response(
        {
            "idempotent": idempotent,
            "operation": operation,
            "authorization": WarehouseAuthorizationSerializer(authorization).data,
        },
        status=200 if idempotent else 201,
    )


@api_view(["GET", "POST"])
@permission_classes([IsWarehouseAuthorizationCollectionUser])
def warehouse_authorization_collection(request):
    if request.method == "GET":
        allowed_query = {"page", "page_size", "warehouse_id", "integration_config_id", "status", "provider"}
        if set(request.query_params) - allowed_query:
            raise ValidationError("仓库 API 授权查询包含不支持的参数。")
        queryset = _warehouse_authorization_queryset(request, "integrations.warehouse.view")
        if request.query_params.get("warehouse_id"):
            warehouse_id = positive_int(request.query_params["warehouse_id"], default=None)
            if warehouse_id is None:
                raise ValidationError({"warehouse_id": "仓库 ID 无效。"})
            queryset = queryset.filter(warehouse_id=warehouse_id)
        if request.query_params.get("integration_config_id"):
            config_id = positive_int(request.query_params["integration_config_id"], default=None)
            if config_id is None:
                raise ValidationError({"integration_config_id": "接入配置 ID 无效。"})
            queryset = queryset.filter(integration_config_id=config_id)
        if request.query_params.get("status"):
            status_value = str(request.query_params["status"]).strip()
            if status_value not in WarehouseAuthorization.Status.values:
                raise ValidationError({"status": "仓库 API 授权状态无效。"})
            queryset = queryset.filter(status=status_value)
        if request.query_params.get("provider"):
            queryset = queryset.filter(provider=str(request.query_params["provider"]).strip())
        page, page_size = pagination_query(request)
        return success_response(
            paginated_data(
                request,
                queryset,
                WarehouseAuthorizationSerializer,
                page=page,
                page_size=page_size,
            )
        )

    data = _warehouse_binding_request_data(request)
    return _perform_warehouse_binding(request, data)


@api_view(["GET"])
@permission_classes([IsWarehouseAuthorizationViewer])
def warehouse_authorization_detail(request, pk):
    authorization = get_scoped_object_or_404(
        _warehouse_authorization_queryset(request, "integrations.warehouse.view"),
        pk=pk,
    )
    return success_response(WarehouseAuthorizationSerializer(authorization).data)


@api_view(["POST"])
@permission_classes([IsWarehouseAuthorizationAuthorizer])
def rebind_warehouse_authorization(request, pk):
    current = get_scoped_object_or_404(
        _warehouse_authorization_queryset(request, "integrations.warehouse.authorize").filter(
            status=WarehouseAuthorization.Status.ACTIVE,
        ),
        pk=pk,
    )
    data = _warehouse_binding_request_data(request, current=current)
    return _perform_warehouse_binding(request, data)


@api_view(["POST"])
@permission_classes([IsWarehouseAuthorizationRevoker])
def revoke_warehouse_authorization(request, pk):
    if not isinstance(request.data, dict):
        raise ValidationError("撤销仓库 API 授权请求必须是 JSON 对象。")
    reject_raw_credential_fields(request.data)
    if set(request.data) - {"idempotency_key"}:
        raise ValidationError("撤销仓库 API 授权请求包含不支持的字段。")
    authorization = get_scoped_object_or_404(
        _warehouse_authorization_queryset(request, "integrations.warehouse.revoke"),
        pk=pk,
    )
    record, idempotent = revoke_warehouse_authorization_record(
        actor=request.user,
        authorization=authorization,
    )
    return success_response(
        {
            "idempotent": idempotent,
            "authorization": WarehouseAuthorizationSerializer(record).data,
        }
    )


@api_view(["GET"])
@permission_classes([IsIntegrationViewer])
def integration_workspace_view(request):
    allowed_query = {
        "mode", "page", "page_size", "platform", "status", "environment", "api_type",
        "resource_type", "schedule_type", "job_state", "subject", "run_id", "started_from", "started_to",
    }
    if set(request.query_params) - allowed_query:
        raise ValidationError("Unknown integration workspace query parameter.")
    try:
        data = integration_workspace(request.user, request.query_params.get("mode", "configs"), request.query_params)
    except (TypeError, ValueError) as exc:
        raise ValidationError(str(exc)) from exc
    return success_response(data)


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


def _get_config_for_user(request, pk, permission_code):
    queryset = filter_integration_configs(
        request.user,
        PlatformIntegrationConfig.objects.filter(tenant=request.user.tenant),
        permission_code,
    )
    return get_scoped_object_or_404(queryset, pk=pk)


def _readiness_digest(payload):
    """Create a stable digest without retaining request secrets."""
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _readiness_operation_identity(request, action, config, payload):
    """Return operation and payload digests used for idempotent page actions."""
    payload_digest = _readiness_digest(payload)
    header_key = str(request.headers.get("Idempotency-Key") or "").strip()
    if header_key and not 8 <= len(header_key) <= 120:
        raise ValidationError({"Idempotency-Key": "Idempotency-Key must contain 8 to 120 characters."})
    if header_key:
        operation_digest = _readiness_digest({"source": "header", "key": header_key})
    else:
        # The UI does not need to manufacture a header: the explicit action
        # payload, including expected_version, is itself a deterministic key.
        operation_digest = _readiness_digest(
            {"source": "payload", "action": action, "config_id": config.id, "payload": payload}
        )
    return operation_digest, payload_digest


def _find_readiness_operation(config, action, operation_digest, payload_digest):
    """Find a previous page action while detecting reused keys with new data."""
    queryset = IntegrationAuditLog.objects.filter(
        tenant=config.tenant,
        integration_config=config,
        action=action,
    ).order_by("-id")
    for audit in queryset:
        detail = audit.masked_detail if isinstance(audit.masked_detail, dict) else {}
        if detail.get("idempotency_key_hash") != operation_digest:
            continue
        if detail.get("payload_digest") != payload_digest:
            raise IdempotencyConflict("The idempotency key was already used for a different readiness action.")
        return audit
    return None


def _readiness_action_response(config, *, operation, replay=False, target_contract=None, dry_run=False, changed=False):
    """Build the common response for a readiness mutation or dry-run."""
    row = build_config_readiness(config)
    data = {
        "config": row,
        "config_version": config.config_version,
        "idempotent_replay": bool(replay),
        "operation": operation,
        "dry_run": bool(dry_run),
        "changed": bool(changed),
    }
    if target_contract is not None:
        data["target_contract_version"] = target_contract
    return data


def _require_marketplace_readiness_config(config):
    platform = str(config.platform or "").lower()
    if platform not in {PlatformChoices.LAZADA, PlatformChoices.SHOPEE, PlatformChoices.TIKTOK}:
        raise ValidationError({"platform": "当前页面动作仅适用于 Lazada、Shopee 或 TikTok Shop 接入配置。"})
    try:
        return get_platform_schema(
            platform,
            environment=config.environment,
        )["contract_versions"][0]
    except Exception as exc:
        raise ValidationError({"contract_version": "无法读取当前平台批准的合同版本。"}) from exc


@api_view(["POST"])
@permission_classes([IsIntegrationConfigDetailUser])
def repair_readiness_contract(request, pk):
    """Dry-run or repair one tenant-scoped marketplace contract version."""
    config = _get_config_for_user(request, pk, "integrations.config.update")
    serializer = ReadinessContractRepairSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    payload = dict(serializer.validated_data)
    dry_run = bool(payload["dry_run"])
    if not dry_run and payload["confirm"] is not True:
        raise ValidationError({"confirm": "应用合同版本修复必须显式确认。"})
    target_contract = _require_marketplace_readiness_config(config)
    action = "repair_platform_contract"
    operation_digest, payload_digest = _readiness_operation_identity(request, action, config, payload)

    with transaction.atomic():
        locked = PlatformIntegrationConfig.objects.select_for_update().get(
            pk=config.pk,
            tenant=request.user.tenant,
        )
        existing = _find_readiness_operation(locked, action, operation_digest, payload_digest)
        if existing is not None:
            return success_response(
                _readiness_action_response(
                    locked,
                    operation=action,
                    replay=True,
                    target_contract=target_contract,
                    dry_run=bool((existing.masked_detail or {}).get("dry_run")),
                    changed=bool((existing.masked_detail or {}).get("changed")),
                ),
                message="合同版本修复操作已幂等完成。",
            )
        if not dry_run and payload["expected_version"] != locked.config_version:
            raise StateConflict("配置版本已变化，请刷新准备度后再修复合同版本。")
        before_version = locked.config_version
        before_contract = locked.contract_version
        changed = locked.contract_version != target_contract
        if not dry_run and changed:
            locked.contract_version = target_contract
            locked.config_version += 1
            locked.save(update_fields=["contract_version", "config_version", "updated_at"])
        _write_audit_log(
            locked,
            request.user,
            action,
            detail={
                "operation": "repair_contract",
                "dry_run": dry_run,
                "changed": changed,
                "contract_version_before": before_contract,
                "target_contract_version": target_contract,
                "config_version_before": before_version,
                "config_version_after": locked.config_version,
                "idempotency_key_hash": operation_digest,
                "payload_digest": payload_digest,
            },
        )
        # For a dry-run the current version is still the version the caller
        # supplied; expose whether an apply would be safe without changing it.
        response_data = _readiness_action_response(
            locked,
            operation=action,
            target_contract=target_contract,
            dry_run=dry_run,
            changed=changed,
        )
        response_data["can_apply"] = bool(
            dry_run and payload["expected_version"] == locked.config_version and changed
        ) if dry_run else False
    return success_response(
        response_data,
        message="合同版本预览完成。" if dry_run else ("合同版本已修复。" if changed else "合同版本已是最新版本。"),
    )


@api_view(["POST"])
@permission_classes([IsIntegrationConfigVerifier])
def set_readiness_readonly_approval(request, pk):
    """Approve or revoke only the tenant config's production-readonly flags."""
    config = _get_config_for_user(request, pk, "integrations.config.verify")
    serializer = ReadonlyApprovalSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    payload = dict(serializer.validated_data)
    if payload["confirm"] is not True:
        raise ValidationError({"confirm": "生产只读审批操作必须显式确认。"})
    reason = str(payload.get("reason") or "").strip()
    if len(reason) < 5:
        raise ValidationError({"reason": "请填写至少 5 个字符的审批或撤销原因。"})
    payload["reason"] = reason
    target_contract = _require_marketplace_readiness_config(config)
    action = "approve_platform_readonly" if payload["approved"] else "revoke_platform_readonly"
    operation_digest, payload_digest = _readiness_operation_identity(request, action, config, payload)

    with transaction.atomic():
        locked = PlatformIntegrationConfig.objects.select_for_update().get(
            pk=config.pk,
            tenant=request.user.tenant,
        )
        existing = _find_readiness_operation(locked, action, operation_digest, payload_digest)
        if existing is not None:
            return success_response(
                _readiness_action_response(
                    locked,
                    operation=action,
                    replay=True,
                    target_contract=target_contract,
                    changed=bool((existing.masked_detail or {}).get("changed")),
                ),
                message="生产只读审批操作已幂等完成。",
            )
        if payload["expected_version"] != locked.config_version:
            raise StateConflict("配置版本已变化，请刷新准备度后再执行生产只读审批。")
        before = {
            "network_enabled": bool(locked.network_enabled),
            "sync_read_enabled": bool(locked.sync_read_enabled),
            "sync_write_enabled": bool(locked.sync_write_enabled),
        }
        if payload["approved"]:
            row = build_config_readiness(locked)
            # network_not_approved is the single state this action is meant to
            # enable.  All other provider/global blockers must already pass.
            blockers = [
                code
                for code in row["blocker_codes"]
                if code not in {"network_not_approved", "readonly_not_approved"}
            ]
            if blockers:
                raise ValidationError(
                    {
                        "detail": "当前配置尚未满足生产只读审批条件。",
                        "blocker_codes": blockers,
                        "blocker_summary": "；".join(BLOCKER_LABELS.get(code, code) for code in blockers),
                    }
                )
            changed = not (locked.network_enabled and locked.sync_read_enabled)
            if changed:
                locked.network_enabled = True
                locked.sync_read_enabled = True
                # This action intentionally does not write sync_write_enabled.
                locked.config_version += 1
                locked.save(update_fields=["network_enabled", "sync_read_enabled", "config_version", "updated_at"])
        else:
            changed = bool(locked.network_enabled or locked.sync_read_enabled)
            if changed:
                locked.network_enabled = False
                locked.sync_read_enabled = False
                locked.config_version += 1
                locked.save(update_fields=["network_enabled", "sync_read_enabled", "config_version", "updated_at"])
        _write_audit_log(
            locked,
            request.user,
            action,
            detail={
                "operation": "approve_readonly" if payload["approved"] else "revoke_readonly",
                "approved": bool(payload["approved"]),
                "changed": changed,
                "reason_recorded": True,
                "config_version_before": payload["expected_version"],
                "config_version_after": locked.config_version,
                "before": before,
                "after": {
                    "network_enabled": bool(locked.network_enabled),
                    "sync_read_enabled": bool(locked.sync_read_enabled),
                    "sync_write_enabled": bool(locked.sync_write_enabled),
                },
                "idempotency_key_hash": operation_digest,
                "payload_digest": payload_digest,
            },
        )
        response_data = _readiness_action_response(
            locked,
            operation=action,
            target_contract=target_contract,
            changed=changed,
        )
    return success_response(
        response_data,
        message=("生产只读审批已完成。" if payload["approved"] else "生产只读审批已撤销。")
        if changed
        else ("生产只读审批已处于目标状态。" if payload["approved"] else "生产只读审批本来就是撤销状态。"),
    )


@api_view(["GET", "POST"])
@permission_classes([IsIntegrationConfigCollectionUser])
def integration_config_collection(request):
    if request.method == "GET":
        allowed_query = {"platform", "environment", "status", "region"}
        if set(request.query_params) - allowed_query:
            raise ValidationError("Unknown integration configuration query parameter.")
        queryset = filter_integration_configs(
            request.user,
            PlatformIntegrationConfig.objects.filter(tenant=request.user.tenant),
            "integrations.config.view",
        )
        for field in ("platform", "environment", "status"):
            if request.query_params.get(field):
                queryset = queryset.filter(**{field: request.query_params[field]})
        if request.query_params.get("region"):
            queryset = queryset.filter(regions__contains=[request.query_params["region"].upper()])
        serializer = PlatformIntegrationConfigSerializer(queryset, many=True)
        return success_response(serializer.data)

    reject_raw_credential_fields(request.data)
    serializer = PlatformIntegrationConfigSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    if not integration_values_allowed(
        request.user,
        "integrations.config.create",
        platform=serializer.validated_data["platform"],
        environment=serializer.validated_data["environment"],
        regions=serializer.validated_data.get("regions", []),
    ):
        raise DataScopeDenied(
            "Integration configuration is outside the authorized data scope.",
            error_code=ErrorCode.DATA_SCOPE_FORBIDDEN,
        )
    config = serializer.save(tenant=request.user.tenant, created_by=request.user)
    _write_audit_log(
        config,
        request.user,
        "create",
        detail={
            "platform": config.platform,
            "account_alias": config.account_alias,
            "environment": config.environment,
            "credential_mask": config.credential_mask,
        },
    )
    return success_response(PlatformIntegrationConfigSerializer(config).data, status=201)


@api_view(["GET"])
@permission_classes([IsIntegrationViewer])
def platform_integration_readiness(request):
    """Return the effective, tenant-scoped read-only platform readiness."""
    queryset = filter_integration_configs(
        request.user,
        PlatformIntegrationConfig.objects.filter(tenant=request.user.tenant),
        "integrations.view",
    )
    return success_response(build_platform_readiness(list(queryset)))


@api_view(["POST"])
@permission_classes([IsIntegrationConfigCollectionUser])
def create_handoff_integration_config(request):
    allowed = {"account_alias", "platform", "api_type", "environment", "regions"}
    if set(request.data) - allowed:
        raise ValidationError("接入配置包含不支持的字段。")
    alias = str(request.data.get("account_alias") or "").strip()
    platform = str(request.data.get("platform") or "").strip().lower()
    api_type = str(request.data.get("api_type") or "").strip().lower()
    environment = str(request.data.get("environment") or "").strip().lower()
    regions = [str(value).strip().upper() for value in (request.data.get("regions") or [])]
    if not alias or len(alias) > 120:
        raise ValidationError({"account_alias": "配置名称不能为空且不能超过 120 个字符。"})
    if platform not in {
        PlatformChoices.LAZADA,
        PlatformChoices.SHOPEE,
        PlatformChoices.TIKTOK,
        PlatformChoices.JIFENG_WMS,
    }:
        raise ValidationError({"platform": "平台无效。"})
    if api_type not in {"marketplace", "advertising", "inventory"}:
        raise ValidationError({"api_type": "API 类型无效。"})
    if (platform == PlatformChoices.JIFENG_WMS) != (api_type == "inventory"):
        raise ValidationError({"api_type": "极风 WMS 只支持库存 API，店铺平台不能使用库存 API。"})
    if platform == PlatformChoices.LAZADA and api_type != "marketplace":
        raise ValidationError({"api_type": "Lazada 当前只支持商城 API 授权。"})
    if environment not in {"sandbox", "pilot", "production"}:
        raise ValidationError({"environment": "环境无效。"})
    if not regions or len(regions) != len(set(regions)) or any(len(region) > 8 for region in regions):
        raise ValidationError({"regions": "请选择一个或多个不重复的适用站点。"})
    if platform == PlatformChoices.LAZADA:
        allowed_regions = {item["value"] for item in get_platform_schema("lazada")["regions"]}
        if not set(regions) <= allowed_regions:
            raise ValidationError({"regions": "Lazada 仅支持 SG、MY、TH、VN、ID、PH 站点。"})
    if not integration_values_allowed(
        request.user,
        "integrations.config.create",
        platform=platform,
        environment=environment,
        regions=regions,
    ):
        raise DataScopeDenied("Integration configuration is outside the authorized data scope.", error_code=ErrorCode.DATA_SCOPE_FORBIDDEN)
    if PlatformIntegrationConfig.objects.filter(
        tenant=request.user.tenant,
        platform=platform,
        account_alias=alias,
        environment=environment,
    ).exists():
        raise ValidationError("相同平台、名称和环境的配置已存在。")
    with transaction.atomic():
        config = PlatformIntegrationConfig.objects.create(
            tenant=request.user.tenant,
            platform=platform,
            account_alias=alias,
            environment=environment,
            status=PlatformIntegrationConfig.Status.PENDING_REVIEW,
            regions=regions,
            contract_version=(
                get_platform_schema(platform, environment=environment)["contract_versions"][0]
                if platform in {PlatformChoices.LAZADA, PlatformChoices.SHOPEE, PlatformChoices.TIKTOK}
                else "shopapi-local-v1"
            ),
            platform_config={"api_type": api_type},
            created_by=request.user,
        )
        with connection.cursor() as cursor:
            columns = {column.name for column in connection.introspection.get_table_description(cursor, PlatformIntegrationConfig._meta.db_table)}
            if "api_type" in columns:
                cursor.execute(
                    f"UPDATE {PlatformIntegrationConfig._meta.db_table} SET api_type=%s WHERE id=%s AND tenant_id=%s",
                    [api_type, config.id, request.user.tenant_id],
                )
        _write_audit_log(config, request.user, "create_integration_config", detail={"platform": platform, "api_type": api_type, "environment": environment, "regions": regions, "credential_source": "none"})
    return success_response(PlatformIntegrationConfigSerializer(config).data, status=201)


@api_view(["GET", "PATCH"])
@permission_classes([IsIntegrationConfigDetailUser])
def integration_config_detail(request, pk):
    permission_code = "integrations.config.view" if request.method == "GET" else "integrations.config.update"
    config = _get_config_for_user(request, pk, permission_code)
    if request.method == "GET":
        return success_response(PlatformIntegrationConfigSerializer(config).data)

    reject_raw_credential_fields(request.data)
    expected_version = request.data.get("version")
    if expected_version is None:
        raise ValidationError({"version": "Configuration version is required."})
    try:
        expected_version = int(expected_version)
    except (TypeError, ValueError):
        raise ValidationError({"version": "Configuration version must be an integer."})
    payload = {key: value for key, value in request.data.items() if key != "version"}
    with transaction.atomic():
        config = PlatformIntegrationConfig.objects.select_for_update().get(
            pk=config.pk,
            tenant=request.user.tenant,
        )
        if expected_version != config.config_version:
            raise StateConflict("The configuration version changed; reload before saving.")
        serializer = PlatformIntegrationConfigSerializer(config, data=payload, partial=True)
        serializer.is_valid(raise_exception=True)
        candidate_platform = serializer.validated_data.get("platform", config.platform)
        if not integration_values_allowed(
            request.user,
            "integrations.config.update",
            platform=candidate_platform,
            environment=serializer.validated_data.get("environment", config.environment),
            regions=serializer.validated_data.get("regions", config.regions),
            config_id=config.id,
        ):
            raise DataScopeDenied(
                "Integration configuration update is outside the authorized data scope.",
                error_code=ErrorCode.DATA_SCOPE_FORBIDDEN,
            )
        config = serializer.save(config_version=config.config_version + 1)
        _write_audit_log(
            config,
            request.user,
            "update_non_secret",
            detail={
                "platform": config.platform,
                "account_alias": config.account_alias,
                "environment": config.environment,
                "status": config.status,
            },
        )
    return success_response(PlatformIntegrationConfigSerializer(config).data)


@api_view(["GET"])
@permission_classes([IsIntegrationConfigCollectionUser])
def platform_config_schema(request, platform):
    if set(request.query_params) - {"environment", "region"}:
        raise ValidationError("Unknown platform schema query parameter.")
    return success_response(
        get_platform_schema(
            platform,
            environment=request.query_params.get("environment"),
            region=request.query_params.get("region"),
        )
    )


def _config_api_type(config):
    configured = str((config.platform_config or {}).get("api_type") or "").strip().lower()
    if configured:
        return configured
    with connection.cursor() as cursor:
        columns = {
            column.name
            for column in connection.introspection.get_table_description(cursor, config._meta.db_table)
        }
        if "api_type" in columns:
            cursor.execute(
                f"SELECT api_type FROM {config._meta.db_table} WHERE id=%s AND tenant_id=%s",
                [config.id, config.tenant_id],
            )
            row = cursor.fetchone()
            if row and row[0]:
                return str(row[0]).strip().lower()
    return "inventory" if config.platform == PlatformChoices.JIFENG_WMS else "marketplace"


def _credential_update_parts(config, values):
    api_type = _config_api_type(config)
    platform_config = dict(config.platform_config or {})
    platform_config["api_type"] = api_type
    identity = str(platform_config.get("identity") or "").strip()
    secret_values = {}
    callback_url = None

    if config.platform == PlatformChoices.LAZADA:
        unsupported = set(values) - {"app_key", "app_secret", "redirect_uri"}
        if unsupported:
            raise ValidationError("Lazada 凭据字段与当前配置不匹配。")
        app_key = str(values.get("app_key") or platform_config.get("app_key") or identity).strip()
        redirect_uri = str(values.get("redirect_uri") or config.callback_url or "").strip()
        if not app_key:
            raise ValidationError({"credentials": {"app_key": "App Key 不能为空。"}})
        if not redirect_uri:
            raise ValidationError({"credentials": {"redirect_uri": "授权回调地址不能为空。"}})
        platform_config["app_key"] = app_key
        callback_url = redirect_uri
        if values.get("app_secret"):
            secret_values["app_secret"] = values["app_secret"]
    elif config.platform == PlatformChoices.SHOPEE:
        unsupported = set(values) - {"partner_id", "partner_key", "redirect_uri"}
        if unsupported:
            raise ValidationError("Shopee 凭据字段与当前配置不匹配。")
        partner_id = str(values.get("partner_id") or platform_config.get("partner_id") or identity).strip()
        redirect_uri = str(values.get("redirect_uri") or config.callback_url or "").strip()
        if not partner_id.isdigit() or int(partner_id) <= 0:
            raise ValidationError({"credentials": {"partner_id": "Partner ID 必须是正整数。"}})
        if not redirect_uri:
            raise ValidationError({"credentials": {"redirect_uri": "Shopee 授权回调地址不能为空。"}})
        platform_config["partner_id"] = partner_id
        callback_url = validate_marketplace_callback_url(
            redirect_uri,
            environment=config.environment,
            platform=config.platform,
        )
        if values.get("partner_key"):
            secret_values["partner_key"] = values["partner_key"]
    elif config.platform == PlatformChoices.TIKTOK and api_type == "advertising":
        unsupported = set(values) - {"ads_app_id", "ads_secret", "redirect_uri"}
        if unsupported:
            raise ValidationError("TikTok 广告凭据字段与当前配置不匹配。")
        app_id = str(values.get("ads_app_id") or platform_config.get("app_id") or identity).strip()
        redirect_uri = str(values.get("redirect_uri") or config.callback_url or "").strip()
        if not app_id:
            raise ValidationError({"credentials": {"ads_app_id": "App ID 不能为空。"}})
        if not redirect_uri:
            raise ValidationError({"credentials": {"redirect_uri": "广告授权回调地址不能为空。"}})
        platform_config["app_id"] = app_id
        platform_config["redirect_uri"] = redirect_uri
        callback_url = redirect_uri
        if values.get("ads_secret"):
            secret_values["api_secret"] = values["ads_secret"]
    elif config.platform == PlatformChoices.TIKTOK:
        unsupported = set(values) - {"app_key", "service_id", "app_secret"}
        if unsupported:
            raise ValidationError("TikTok Shop 凭据字段与当前配置不匹配。")
        app_key = str(values.get("app_key") or platform_config.get("app_key") or identity).strip()
        service_id = str(values.get("service_id") or platform_config.get("service_id") or "").strip()
        if not app_key or not service_id:
            raise ValidationError("App Key 和 Service ID 不能为空。")
        platform_config.update({"app_key": app_key, "service_id": service_id})
        if values.get("app_secret"):
            secret_values["app_secret"] = values["app_secret"]
    elif config.platform == PlatformChoices.JIFENG_WMS:
        unsupported = set(values) - {"api_base_url", "domain", "client_id", "client_secret"}
        if unsupported:
            raise ValidationError("极风 WMS 凭据字段与当前配置不匹配。")
        api_host = str(values.get("api_base_url") or platform_config.get("api_host") or "").strip()
        domain = str(values.get("domain") or platform_config.get("domain") or "").strip()
        client_id = str(values.get("client_id") or platform_config.get("client_id") or identity).strip()
        if not api_host or not domain or not client_id:
            raise ValidationError("API Base URL、Domain 和 Client ID 不能为空。")
        platform_config.update({"api_host": api_host, "domain": domain, "client_id": client_id})
        if values.get("client_secret"):
            secret_values["api_secret"] = values["client_secret"]
    else:
        raise ValidationError("当前平台不支持维护开发者凭据。")

    if not secret_values:
        try:
            get_custody_backend().retrieve_secret(config.credential_id)
        except Exception:
            raise ValidationError("现有凭据无法由当前保管库读取，请填写新的密钥。") from None
    return secret_values, platform_config, callback_url


@api_view(["POST"])
@permission_classes([IsMarketplaceCredentialRotator])
def rotate_integration_secret_values(request, pk):
    config = _get_config_for_user(request, pk, "integrations.credential.rotate")
    serializer = CredentialRotateWriteSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    secret_values, platform_config, callback_url = _credential_update_parts(config, dict(data["credentials"]))
    config, repeated = rotate_config_secrets(
        config,
        credentials=secret_values,
        version=data["version"],
        reason=data["reason"],
        actor=request.user,
        idempotency_key=request.headers.get("Idempotency-Key"),
        platform_config=platform_config,
        callback_url=callback_url,
    )
    response = PlatformIntegrationConfigSerializer(config).data
    response["idempotent_replay"] = repeated
    return success_response(response)


@api_view(["POST"])
@permission_classes([IsIntegrationCredentialClearer])
def clear_integration_secret_values(request, pk):
    config = _get_config_for_user(request, pk, "integrations.credential.clear")
    serializer = CredentialClearSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    config, repeated = clear_config_secrets(
        config,
        version=data["version"],
        reason=data["reason"],
        actor=request.user,
        idempotency_key=request.headers.get("Idempotency-Key"),
    )
    response = PlatformIntegrationConfigSerializer(config).data
    response["idempotent_replay"] = repeated
    return success_response(response)


@api_view(["GET"])
@permission_classes([IsIntegrationAuditViewer])
def integration_config_audit(request, pk):
    config = _get_config_for_user(request, pk, "integrations.audit.view")
    queryset = IntegrationAuditLog.objects.filter(
        tenant=request.user.tenant,
        integration_config=config,
    ).select_related("integration_config")
    return success_response(IntegrationAuditLogSerializer(queryset, many=True).data)


@api_view(["GET"])
@permission_classes([IsIntegrationAuditViewer])
def integration_audit_collection(request):
    """Return the tenant's redacted integration audit trail within data scope."""

    allowed_query = {"page", "page_size", "config_id", "platform", "action"}
    if set(request.query_params) - allowed_query:
        raise ValidationError("Unknown integration audit query parameter.")

    # Resolve the configuration scope first.  The audit table has its own
    # tenant column, but using scoped configuration IDs prevents logs for
    # configurations outside the viewer's declared integration scope from
    # leaking through this cross-configuration collection endpoint.
    visible_config_ids = filter_integration_configs(
        request.user,
        PlatformIntegrationConfig.objects.filter(tenant=request.user.tenant),
        "integrations.audit.view",
    ).values_list("id", flat=True)
    queryset = IntegrationAuditLog.objects.filter(
        tenant=request.user.tenant,
        integration_config_id__in=visible_config_ids,
    ).select_related("integration_config")

    config_id = request.query_params.get("config_id")
    if config_id not in (None, ""):
        queryset = queryset.filter(
            integration_config_id=positive_int(config_id, default=None, maximum=2147483647)
        )

    platform = str(request.query_params.get("platform") or "").strip().lower()
    if platform:
        if platform not in PlatformChoices.values:
            raise ValidationError({"platform": "Unsupported integration platform filter."})
        queryset = queryset.filter(integration_config__platform=platform)

    action = str(request.query_params.get("action") or "").strip()
    if len(action) > 80:
        raise ValidationError({"action": "Action filter must not exceed 80 characters."})
    if action:
        queryset = queryset.filter(action=action)

    page, page_size = pagination_query(request)
    return success_response(
        paginated_data(
            request,
            queryset,
            IntegrationAuditLogSerializer,
            page=page,
            page_size=page_size,
        )
    )


@api_view(["POST"])
@permission_classes([IsIntegrationCredentialRotator])
def rotate_integration_credentials(request, pk):
    config = _get_config_for_user(request, pk, "integrations.rotate")
    reject_raw_credential_fields(request.data)
    serializer = RotateCredentialsSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    config = rotate_config_references(
        config,
        credential_id=serializer.validated_data["credential_id"],
        token_id=serializer.validated_data["token_id"],
        version=serializer.validated_data["credential_reference_version"],
        actor=request.user,
    )
    return success_response(PlatformIntegrationConfigSerializer(config).data)


@api_view(["GET"])
@permission_classes([IsMarketplaceStoreViewer])
def store_authorization_collection(request):
    allowed_query = {"page", "page_size", "platform", "status", "store_id"}
    if set(request.query_params) - allowed_query:
        raise ValidationError("Unknown store authorization query parameter.")
    queryset = MarketplaceStoreAuthorization.objects.filter(tenant=request.user.tenant).select_related("store").prefetch_related("connection_capabilities")
    if request.query_params.get("platform"):
        platform = request.query_params["platform"]
        if platform not in {"lazada", "shopee", "tiktok"}:
            raise ValidationError("Unsupported marketplace platform filter.")
        queryset = queryset.filter(platform=platform)
    if request.query_params.get("status"):
        status_value = request.query_params["status"]
        if status_value not in MarketplaceStoreAuthorization.Status.values:
            raise ValidationError("Unsupported authorization status filter.")
        queryset = queryset.filter(status=status_value)
    if request.query_params.get("store_id"):
        queryset = queryset.filter(store_id=positive_int(request.query_params["store_id"], default=0))
    queryset = filter_store_authorizations(request.user, queryset, "integrations.store.view")
    page, page_size = pagination_query(request)
    return success_response(
        paginated_data(
            request,
            queryset,
            MarketplaceStoreAuthorizationSerializer,
            page=page,
            page_size=page_size,
        )
    )


@api_view(["GET"])
@permission_classes([IsMarketplaceStoreViewer])
def store_authorization_detail(request, pk):
    queryset = filter_store_authorizations(
        request.user,
        MarketplaceStoreAuthorization.objects.filter(tenant=request.user.tenant).select_related("store").prefetch_related("connection_capabilities"),
        "integrations.store.view",
    )
    authorization = get_scoped_object_or_404(queryset, pk=pk)
    return success_response(MarketplaceStoreAuthorizationSerializer(authorization).data)


@api_view(["GET", "PUT"])
@permission_classes([IsMarketplaceCapabilityManager])
def store_authorization_capabilities(request, pk):
    permission_code = "integrations.store.view" if request.method == "GET" else "integrations.store.authorize"
    authorization = get_scoped_object_or_404(
        filter_store_authorizations(
            request.user,
            MarketplaceStoreAuthorization.objects.filter(tenant=request.user.tenant),
            permission_code,
        ),
        pk=pk,
    )
    if request.method == "PUT":
        if not isinstance(request.data, dict) or set(request.data) != {"capabilities"} or not isinstance(request.data.get("capabilities"), list):
            raise ValidationError({"capabilities": "A capabilities list is required and no other fields are accepted."})
        rows = request.data["capabilities"]
        allowed_fields = {"capability_code", "read_enabled", "write_enabled", "sync_mode", "source_priority", "status"}
        if any(set(row) - allowed_fields for row in rows if isinstance(row, dict)):
            raise ValidationError({"capabilities": "Unsupported capability field."})
        serializer = ConnectionCapabilityWriteSerializer(data=rows, many=True)
        serializer.is_valid(raise_exception=True)
        codes = [row["capability_code"] for row in serializer.validated_data]
        if len(codes) != len(set(codes)):
            raise ValidationError({"capabilities": "Capability codes must be unique within a request."})
        if authorization.status != MarketplaceStoreAuthorization.Status.ACTIVE and any(
            row["status"] == ConnectionCapability.Status.ACTIVE for row in serializer.validated_data
        ):
            raise ValidationError({"capabilities": "A revoked, expired, pending or failed authorization cannot activate capabilities."})
        with transaction.atomic():
            for row in serializer.validated_data:
                item, _ = ConnectionCapability.objects.get_or_create(
                    authorization=authorization,
                    capability_code=row["capability_code"],
                )
                for field in ("read_enabled", "write_enabled", "sync_mode", "source_priority", "status"):
                    setattr(item, field, row[field])
                item.full_clean()
                item.save()
    queryset = ConnectionCapability.objects.filter(authorization=authorization)
    return success_response({
        "authorization_id": authorization.id,
        "available_codes": list(ConnectionCapability.CapabilityCode.values),
        "suggestions": capability_suggestions(authorization),
        "results": ConnectionCapabilitySerializer(queryset, many=True).data,
    })


@api_view(["POST"])
@permission_classes([IsMarketplaceStoreAuthorizer])
def start_marketplace_store_oauth(request):
    reject_raw_credential_fields(request.data)
    serializer = MarketplaceOAuthStartSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    if not integration_values_allowed(
        request.user,
        "integrations.store.authorize",
        platform=data["platform"],
        config_id=data["integration_config_id"],
        store_id=data["store_id"],
    ):
        raise DataScopeDenied(
            "OAuth start is outside the authorized data scope.",
            error_code=ErrorCode.DATA_SCOPE_FORBIDDEN,
        )
    config = get_scoped_object_or_404(
        filter_integration_configs(
            request.user,
            PlatformIntegrationConfig.objects.filter(tenant=request.user.tenant),
            "integrations.store.authorize",
        ),
        pk=data["integration_config_id"],
    )
    if config.regions and data["region"] not in config.regions:
        raise ValidationError({"region": "OAuth region is not approved by the selected configuration."})
    if config.callback_url and data["redirect_uri"] != config.callback_url:
        raise ValidationError({"redirect_uri": "OAuth redirect URI does not match the selected configuration."})
    if config.scopes and set(data["scopes"]) != set(config.scopes):
        raise ValidationError({"scopes": "OAuth scopes must exactly match the selected configuration."})
    from apps.masterdata.models import StoreMaster

    store = get_object_or_404(StoreMaster, tenant=request.user.tenant, pk=data["store_id"])
    result = start_marketplace_oauth(
        actor=request.user,
        platform=data["platform"],
        integration_config=config,
        store=store,
        region=data["region"],
        redirect_uri=data["redirect_uri"],
        scopes=data["scopes"],
    )
    _write_audit_log(
        config,
        request.user,
        "oauth_start",
        detail={"platform": data["platform"], "region": data["region"], "store_id": store.id},
    )
    return success_response(result, status=201)


def _marketplace_oauth_callback(request, platform):
    authorization = complete_marketplace_oauth_callback(platform=platform, query_params=request.query_params)
    return success_response(MarketplaceStoreAuthorizationSerializer(authorization).data)


@api_view(["GET"])
@authentication_classes([])
@permission_classes([])
def marketplace_oauth_callback_shopee(request):
    return _marketplace_oauth_callback(request, PlatformChoices.SHOPEE)


@api_view(["GET"])
@authentication_classes([])
@permission_classes([])
def marketplace_oauth_callback_tiktok(request):
    return _marketplace_oauth_callback(request, PlatformChoices.TIKTOK)


@api_view(["GET"])
@authentication_classes([])
@permission_classes([])
def marketplace_oauth_callback_lazada(request):
    return _marketplace_oauth_callback(request, PlatformChoices.LAZADA)


def _get_store_authorization_for_user(request, pk, permission_code):
    queryset = filter_store_authorizations(
        request.user,
        MarketplaceStoreAuthorization.objects.filter(tenant=request.user.tenant),
        permission_code,
    )
    return get_scoped_object_or_404(queryset, pk=pk)


def _get_store_authorization_for_permissions(request, pk, *permission_codes):
    """Resolve a store authorization inside the intersection of scopes."""
    queryset = MarketplaceStoreAuthorization.objects.filter(tenant=request.user.tenant)
    for permission_code in permission_codes:
        queryset = filter_store_authorizations(request.user, queryset, permission_code)
    return get_scoped_object_or_404(queryset, pk=pk)


@api_view(["POST"])
@permission_classes([IsMarketplaceStoreAuthorizer, IsMarketplaceCredentialRotator])
def refresh_store_authorization(request, pk):
    reject_raw_credential_fields(request.data)
    record = _get_store_authorization_for_permissions(
        request,
        pk,
        "integrations.store.authorize",
        "integrations.credential.rotate",
    )
    if record.platform == PlatformChoices.TIKTOK and request.data.get("confirmed") is not True:
        raise ValidationError({"confirmed": "TikTok Shop token refresh requires explicit confirmation."})
    record = refresh_marketplace_authorization(record, actor=request.user)
    return success_response(MarketplaceStoreAuthorizationSerializer(record).data)


@api_view(["POST"])
@permission_classes([IsMarketplaceStoreRevoker])
def revoke_store_authorization(request, pk):
    reject_raw_credential_fields(request.data)
    record = _get_store_authorization_for_user(request, pk, "integrations.store.revoke")
    record, idempotent = revoke_marketplace_authorization(record, actor=request.user)
    return success_response(
        {"idempotent": idempotent, "authorization": MarketplaceStoreAuthorizationSerializer(record).data}
    )


STORE_MAPPING_VIEW_PERMISSION = "integrations.store_mapping.view"
STORE_MAPPING_MANAGE_PERMISSION = "integrations.store_mapping.manage"
PRODUCT_MAPPING_VIEW_PERMISSION = "integrations.product_mapping.view"
PRODUCT_MAPPING_MANAGE_PERMISSION = "integrations.product_mapping.manage"
PRODUCT_MAPPING_CONFIRM_PERMISSION = "integrations.product_mapping.confirm"


def _mask_platform_store_id(value):
    value = str(value or "")
    if len(value) <= 4:
        return "*" * len(value)
    return "*" * (len(value) - 4) + value[-4:]


def _option_page(request, queryset, serializer, *, page, page_size):
    paginator = Paginator(queryset, page_size)
    if paginator.num_pages and page <= paginator.num_pages:
        page_obj = paginator.page(page)
        rows = page_obj.object_list
        has_next = page_obj.has_next()
        has_previous = page_obj.has_previous()
    else:
        rows = []
        has_next = False
        has_previous = bool(paginator.num_pages and page > 1)

    def page_url(target):
        if target is None:
            return None
        params = request.query_params.copy()
        params["page"] = target
        params["page_size"] = page_size
        return request.build_absolute_uri(f"{request.path}?{params.urlencode()}")

    return {
        "results": serializer(rows),
        "pagination": {
            "count": paginator.count,
            "page": page,
            "page_size": page_size,
            "next": page_url(page + 1) if has_next else None,
            "previous": page_url(page - 1) if has_previous else None,
        },
    }


@api_view(["GET"])
@permission_classes([IsMarketplaceStoreMappingManager])
def store_mapping_options(request):
    """Return safe, scope-filtered options for the consolidated store page."""

    allowed_query = {"page", "page_size", "platform", "store_id", "search"}
    if set(request.query_params) - allowed_query:
        raise ValidationError("Unknown store mapping option query parameter.")
    platform = str(request.query_params.get("platform") or "").strip().lower()
    if platform and platform not in {"shopee", "tiktok", "lazada"}:
        raise ValidationError("Unsupported marketplace platform filter.")
    store_id = positive_int(request.query_params.get("store_id"), default=0) if request.query_params.get("store_id") else None
    search = str(request.query_params.get("search") or "").strip()
    page, page_size = pagination_query(request, default_size=20)

    from apps.masterdata.models import StoreMaster

    authorizations = MarketplaceStoreAuthorization.objects.filter(
        tenant=request.user.tenant,
    ).select_related("store", "integration_config")
    authorizations = filter_store_authorizations(request.user, authorizations, STORE_MAPPING_VIEW_PERMISSION)
    mappings = MarketplaceStoreMapping.objects.filter(
        tenant=request.user.tenant,
    ).select_related("store", "authorization")
    mappings = filter_store_mappings(request.user, mappings, STORE_MAPPING_VIEW_PERMISSION)
    if platform:
        authorizations = authorizations.filter(platform=platform)
        mappings = mappings.filter(platform=platform)
    if store_id:
        authorizations = authorizations.filter(store_id=store_id)
        mappings = mappings.filter(store_id=store_id)
    if search:
        term = Q(store__code__icontains=search) | Q(store__name__icontains=search) | Q(platform_store_id__icontains=search)
        authorizations = authorizations.filter(term)
        mappings = mappings.filter(term)

    # Stores are derived from authorized identities as well as existing links,
    # so an operator can create the first mapping without masterdata access.
    store_ids = set(authorizations.values_list("store_id", flat=True)) | set(mappings.values_list("store_id", flat=True))
    stores = StoreMaster.objects.filter(tenant=request.user.tenant, id__in=store_ids).select_related("platform")
    if platform:
        stores = stores.filter(Q(platform__platform_type=platform) | Q(platform__code=platform))
    if search:
        stores = stores.filter(Q(code__icontains=search) | Q(name__icontains=search))
    if store_id:
        stores = stores.filter(pk=store_id)

    store_page = _option_page(
        request,
        stores.order_by("code", "id"),
        lambda rows: [
            {
                "id": item.id,
                "code": item.code,
                "name": item.name,
                "platform": item.platform.platform_type,
                "platform_name": item.platform.name,
            }
            for item in rows
        ],
        page=page,
        page_size=page_size,
    )
    authorization_page = _option_page(
        request,
        authorizations.order_by("platform", "store_id", "id"),
        lambda rows: [
            {
                "id": item.id,
                "store_id": item.store_id,
                "store_code": item.store.code,
                "store_name": item.store.name,
                "platform": item.platform,
                "region": item.region,
                "status": item.status,
                "platform_store_id_masked": _mask_platform_store_id(item.platform_store_id),
                "expires_at": item.expires_at,
            }
            for item in rows
        ],
        page=page,
        page_size=page_size,
    )
    mapping_page = _option_page(
        request,
        mappings.order_by("platform", "store_id", "id"),
        lambda rows: [
            {
                "id": item.id,
                "store_id": item.store_id,
                "store_code": item.store.code,
                "store_name": item.store.name,
                "platform": item.platform,
                "platform_store_id": item.platform_store_id,
                "region": item.region,
                "status": item.status,
            }
            for item in rows
        ],
        page=page,
        page_size=page_size,
    )
    return success_response({
        "stores": store_page["results"],
        "authorizations": authorization_page["results"],
        "store_mappings": mapping_page["results"],
        "pagination": {
            "stores": store_page["pagination"],
            "authorizations": authorization_page["pagination"],
            "store_mappings": mapping_page["pagination"],
        },
    })


@api_view(["GET"])
@permission_classes([IsMarketplaceProductMappingManager])
def product_mapping_options(request):
    """Return canonical detail and tenant SKU options within mapping scope."""

    allowed_query = {
        "page", "page_size", "platform", "store_id", "platform_detail_id", "variant_id",
        "mapping_status", "search",
    }
    if set(request.query_params) - allowed_query:
        raise ValidationError("Unknown product mapping option query parameter.")
    platform = str(request.query_params.get("platform") or "").strip().lower()
    if platform and platform not in {"shopee", "tiktok", "lazada"}:
        raise ValidationError("Unsupported marketplace platform filter.")
    store_id = positive_int(request.query_params.get("store_id"), default=0) if request.query_params.get("store_id") else None
    detail_id = positive_int(request.query_params.get("platform_detail_id"), default=0) if request.query_params.get("platform_detail_id") else None
    variant_id = str(request.query_params.get("variant_id") or "").strip()
    mapping_status = str(request.query_params.get("mapping_status") or "").strip().lower()
    search = str(request.query_params.get("search") or "").strip()
    page, page_size = pagination_query(request, default_size=20)

    from apps.listings.models import PlatformProductDetail
    from apps.masterdata.models import StoreMaster
    from apps.products.models import ProductSKU

    if mapping_status and mapping_status not in MarketplaceProductMapping.Status.values:
        raise ValidationError({"mapping_status": "Unsupported product mapping status filter."})

    # Product-only users receive store mappings through the same product-
    # mapping scope; no store-mapping permission is required.  Keep inactive
    # mappings in the visible set so historical product mappings remain
    # discoverable, but derive the create target from a separate active set.
    store_mapping_queryset = MarketplaceStoreMapping.objects.filter(
        tenant=request.user.tenant,
    ).select_related("store")
    store_mapping_queryset = filter_store_mappings(
        request.user,
        store_mapping_queryset,
        PRODUCT_MAPPING_VIEW_PERMISSION,
    )
    if platform:
        store_mapping_queryset = store_mapping_queryset.filter(platform=platform)
    if store_id:
        store_mapping_queryset = store_mapping_queryset.filter(store_id=store_id)
    visible_store_mappings = list(store_mapping_queryset)
    visible_mapping_queryset = MarketplaceProductMapping.objects.filter(
        tenant=request.user.tenant,
    ).select_related(
        "sku",
        "platform_detail",
        "platform_detail__platform",
        "platform_detail__store",
        "store_mapping",
        "store_mapping__store",
    )
    visible_mapping_queryset = filter_product_mappings(
        request.user,
        visible_mapping_queryset,
        PRODUCT_MAPPING_VIEW_PERMISSION,
    )

    # A detail can be returned when its store mapping is inactive, provided
    # the mapping itself is visible.  Unlinked details still need a visible
    # store/platform identity so they can be offered as a candidate.
    scope_pairs = {
        (item.store_id, str(item.platform).strip().lower())
        for item in visible_store_mappings
    }
    detail_scope = Q(pk__in=[])
    for scoped_store_id, scoped_platform in scope_pairs:
        detail_scope |= Q(store_id=scoped_store_id) & (
            Q(platform__platform_type=scoped_platform)
            | Q(platform__code=scoped_platform)
        )
    detail_queryset = PlatformProductDetail.objects.filter(
        tenant=request.user.tenant,
    ).filter(detail_scope).select_related(
        "platform", "store", "internal_sku"
    )
    if platform:
        detail_queryset = detail_queryset.filter(
            Q(platform__platform_type=platform) | Q(platform__code=platform)
        )
    if detail_id:
        detail_queryset = detail_queryset.filter(pk=detail_id)
    if variant_id:
        detail_queryset = detail_queryset.filter(platform_variant_id=variant_id)
    if mapping_status == MarketplaceProductMapping.Status.UNMAPPED:
        visible_unmapped_detail_ids = visible_mapping_queryset.filter(
            status=MarketplaceProductMapping.Status.UNMAPPED,
            platform_detail_id__isnull=False,
        ).values_list("platform_detail_id", flat=True)
        detail_queryset = detail_queryset.filter(
            Q(marketplace_mapping__isnull=True)
            | Q(pk__in=visible_unmapped_detail_ids)
        )
    elif mapping_status:
        visible_status_detail_ids = visible_mapping_queryset.filter(
            status=mapping_status,
            platform_detail_id__isnull=False,
        ).values_list("platform_detail_id", flat=True)
        detail_queryset = detail_queryset.filter(pk__in=visible_status_detail_ids)
    if search:
        detail_queryset = detail_queryset.filter(
            Q(platform_product_id__icontains=search)
            | Q(platform_variant_id__icontains=search)
            | Q(platform_sku__icontains=search)
            | Q(title__icontains=search)
            | Q(internal_sku__sku_code__icontains=search)
        )
    details = detail_queryset.order_by("platform_id", "store_id", "id")

    active_store_mappings_by_key = defaultdict(dict)
    for item in visible_store_mappings:
        if item.status != MarketplaceStoreMapping.Status.ACTIVE:
            continue
        platform_keys = {
            str(item.platform or "").strip().lower(),
            str(getattr(item.store.platform, "platform_type", "") or "").strip().lower(),
            str(getattr(item.store.platform, "code", "") or "").strip().lower(),
        }
        for platform_key in filter(None, platform_keys):
            active_store_mappings_by_key[(item.store_id, platform_key)][item.id] = item

    def active_store_mapping_for_detail(item):
        platform_keys = {
            str(getattr(item.platform, "platform_type", "") or "").strip().lower(),
            str(getattr(item.platform, "code", "") or "").strip().lower(),
        }
        matches = {}
        for platform_key in filter(None, platform_keys):
            matches.update(active_store_mappings_by_key.get((item.store_id, platform_key), {}))
        # A detail with multiple active bindings is deliberately not assigned
        # a guessed target; the UI must ask the operator to choose one.
        return next(iter(matches.values())) if len(matches) == 1 else None

    def serialize_detail_options(rows):
        page_detail_ids = [item.id for item in rows]
        page_mappings = {
            mapping.platform_detail_id: mapping
            for mapping in visible_mapping_queryset.filter(
                platform_detail_id__in=page_detail_ids,
            )
        }
        result = []
        for item in rows:
            mapping = page_mappings.get(item.id)
            active_store_mapping = active_store_mapping_for_detail(item)
            result.append({
                "id": item.id,
                "platform": item.platform.platform_type,
                "platform_name": item.platform.name,
                "store_id": item.store_id,
                "store_code": item.store.code,
                "store_name": item.store.name,
                "store_mapping_id": active_store_mapping.id if active_store_mapping else None,
                "platform_product_id": item.platform_product_id,
                "platform_variant_id": item.platform_variant_id,
                "platform_sku": item.platform_sku,
                "title": item.title,
                "internal_sku_id": item.internal_sku_id,
                "internal_sku_code": item.internal_sku.sku_code if item.internal_sku_id and item.internal_sku else None,
                "mapping": {
                    "id": mapping.id,
                    "status": mapping.status,
                    "sku_id": mapping.sku_id,
                    "sku_code": mapping.sku.sku_code if mapping.sku_id and mapping.sku else None,
                    "confidence": mapping.confidence,
                    "result_code": mapping.result_code,
                    "manually_confirmed": mapping.manually_confirmed,
                } if mapping is not None else None,
            })
        return result

    def serialize_detail_option(item):
        """Retained as a tiny compatibility helper for callers/tests."""
        return serialize_detail_options([item])[0]

    detail_page = _option_page(
        request,
        details,
        serialize_detail_options,
        page=page,
        page_size=page_size,
    )
    sku_queryset = ProductSKU.objects.filter(tenant=request.user.tenant).select_related("spu")
    if search:
        sku_queryset = sku_queryset.filter(
            Q(sku_code__icontains=search)
            | Q(legacy_sku_code__icontains=search)
            | Q(spu__spu_code__icontains=search)
            | Q(spu__product_name__icontains=search)
        )
    sku_page = _option_page(
        request,
        sku_queryset.order_by("sku_code", "id"),
        lambda rows: [
            {
                "id": item.id,
                "sku_code": item.sku_code,
                "legacy_sku_code": item.legacy_sku_code,
                "product_id": item.spu_id,
                "product_name": item.spu.product_name if item.spu_id and item.spu else "",
            }
            for item in rows
        ],
        page=page,
        page_size=page_size,
    )
    return success_response({
        "count": detail_page["pagination"]["count"],
        "platform_details": detail_page["results"],
        "skus": sku_page["results"],
        "pagination": {
            "platform_details": detail_page["pagination"],
            "skus": sku_page["pagination"],
        },
    })


@api_view(["GET", "POST"])
@permission_classes([IsMarketplaceStoreMappingManager])
def store_mapping_collection(request):
    if request.method == "GET":
        allowed_query = {"page", "page_size", "platform", "status", "store_id"}
        if set(request.query_params) - allowed_query:
            raise ValidationError("Unknown store mapping query parameter.")
        queryset = MarketplaceStoreMapping.objects.filter(tenant=request.user.tenant).select_related("store")
        if request.query_params.get("platform"):
            platform = request.query_params["platform"]
            if platform not in {"shopee", "tiktok"}:
                raise ValidationError("Unsupported marketplace platform filter.")
            queryset = queryset.filter(platform=platform)
        if request.query_params.get("status"):
            status_value = request.query_params["status"]
            if status_value not in MarketplaceStoreMapping.Status.values:
                raise ValidationError("Unsupported store mapping status filter.")
            queryset = queryset.filter(status=status_value)
        if request.query_params.get("store_id"):
            queryset = queryset.filter(store_id=positive_int(request.query_params["store_id"], default=0))
        queryset = filter_store_mappings(request.user, queryset, STORE_MAPPING_VIEW_PERMISSION)
        page, page_size = pagination_query(request)
        return success_response(
            paginated_data(
                request,
                queryset,
                MarketplaceStoreMappingSerializer,
                page=page,
                page_size=page_size,
            )
        )

    reject_raw_credential_fields(request.data)
    serializer = StoreMappingCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    authorization = get_scoped_object_or_404(
        filter_store_authorizations(
            request.user,
            MarketplaceStoreAuthorization.objects.filter(tenant=request.user.tenant),
            STORE_MAPPING_MANAGE_PERMISSION,
        ),
        pk=data["authorization_id"],
    )
    from apps.masterdata.models import StoreMaster

    store = get_object_or_404(StoreMaster, tenant=request.user.tenant, pk=data["store_id"])
    if authorization.store_id != store.id:
        raise ValidationError({"store_id": "授权身份与所选店铺不一致。"})
    mapping = create_store_mapping(
        tenant=request.user.tenant,
        actor=request.user,
        store=store,
        authorization=authorization,
        store_timezone=data["timezone"],
        currency=data["currency"],
    )
    return success_response(MarketplaceStoreMappingSerializer(mapping).data, status=201)


@api_view(["GET", "PATCH"])
@permission_classes([IsMarketplaceStoreMappingManager])
def store_mapping_detail(request, pk):
    permission_code = STORE_MAPPING_VIEW_PERMISSION if request.method == "GET" else STORE_MAPPING_MANAGE_PERMISSION
    queryset = filter_store_mappings(
        request.user,
        MarketplaceStoreMapping.objects.filter(tenant=request.user.tenant).select_related("store", "authorization"),
        permission_code,
    )
    mapping = get_scoped_object_or_404(queryset, pk=pk)
    if request.method == "GET":
        return success_response(MarketplaceStoreMappingSerializer(mapping).data)

    reject_raw_credential_fields(request.data)
    serializer = StoreMappingUpdateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    if not serializer.validated_data:
        raise ValidationError("No supported store mapping fields were provided.")
    mapping = update_store_mapping(
        mapping,
        actor=request.user,
        status=serializer.validated_data.get("status"),
        store_timezone=serializer.validated_data.get("timezone"),
        currency=serializer.validated_data.get("currency"),
    )
    return success_response(MarketplaceStoreMappingSerializer(mapping).data)


@api_view(["GET", "POST"])
@permission_classes([IsMarketplaceProductMappingManager])
def product_mapping_collection(request):
    if request.method == "GET":
        allowed_query = {
            "page", "page_size", "platform", "status", "store_mapping_id", "store_id",
            "platform_detail_id", "platform_variant_id", "search", "unlinked",
        }
        if set(request.query_params) - allowed_query:
            raise ValidationError("Unknown product mapping query parameter.")
        queryset = MarketplaceProductMapping.objects.filter(tenant=request.user.tenant).select_related(
            "sku", "platform_detail", "store_mapping", "store_mapping__store"
        )
        if request.query_params.get("platform"):
            platform = request.query_params["platform"]
            if platform not in {"shopee", "tiktok"}:
                raise ValidationError("Unsupported marketplace platform filter.")
            queryset = queryset.filter(platform=platform)
        if request.query_params.get("status"):
            status_value = request.query_params["status"]
            if status_value not in MarketplaceProductMapping.Status.values:
                raise ValidationError("Unsupported product mapping status filter.")
            queryset = queryset.filter(status=status_value)
        if request.query_params.get("store_mapping_id"):
            queryset = queryset.filter(
                store_mapping_id=positive_int(request.query_params["store_mapping_id"], default=0)
            )
        if request.query_params.get("store_id"):
            queryset = queryset.filter(
                store_mapping__store_id=positive_int(request.query_params["store_id"], default=0)
            )
        if request.query_params.get("platform_detail_id"):
            queryset = queryset.filter(
                platform_detail_id=positive_int(request.query_params["platform_detail_id"], default=0)
            )
        if request.query_params.get("platform_variant_id"):
            queryset = queryset.filter(
                platform_variant_id=str(request.query_params["platform_variant_id"]).strip()
            )
        if request.query_params.get("search"):
            search = str(request.query_params["search"]).strip()
            queryset = queryset.filter(
                Q(platform_product_id__icontains=search)
                | Q(platform_variant_id__icontains=search)
                | Q(platform_sku__icontains=search)
                | Q(sku__sku_code__icontains=search)
                | Q(sku__legacy_sku_code__icontains=search)
                | Q(platform_detail__platform_product_id__icontains=search)
                | Q(platform_detail__platform_sku__icontains=search)
                | Q(platform_detail__title__icontains=search)
            )
        if request.query_params.get("unlinked", "").strip().lower() in {"1", "true", "yes", "on"}:
            queryset = queryset.filter(platform_detail_id__isnull=True)
        queryset = filter_product_mappings(request.user, queryset, PRODUCT_MAPPING_VIEW_PERMISSION)
        page, page_size = pagination_query(request)
        return success_response(
            paginated_data(
                request,
                queryset,
                MarketplaceProductMappingSerializer,
                page=page,
                page_size=page_size,
            )
        )

    reject_raw_credential_fields(request.data)
    serializer = ProductMappingCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    from apps.listings.models import PlatformProductDetail

    platform_detail = None
    if data.get("platform_detail_id"):
        platform_detail = get_object_or_404(
            PlatformProductDetail.objects.select_related("platform", "store"),
            tenant=request.user.tenant,
            pk=data["platform_detail_id"],
        )
    store_mapping_queryset = filter_store_mappings(
        request.user,
        MarketplaceStoreMapping.objects.filter(
            tenant=request.user.tenant,
            status=MarketplaceStoreMapping.Status.ACTIVE,
        ),
        PRODUCT_MAPPING_MANAGE_PERMISSION,
    )
    if data.get("store_mapping_id"):
        store_mapping = get_scoped_object_or_404(store_mapping_queryset, pk=data["store_mapping_id"])
    elif platform_detail is not None:
        platform_value = platform_detail.platform.platform_type or platform_detail.platform.code
        matches = list(store_mapping_queryset.filter(
            store_id=platform_detail.store_id,
            platform=platform_value,
        )[:2])
        if len(matches) != 1:
            raise ValidationError({"store_mapping_id": "该平台商品明细没有唯一可用的店铺映射。"})
        store_mapping = matches[0]
    else:
        raise ValidationError({"store_mapping_id": "店铺映射不能为空。"})
    mapping = create_product_mapping(
        tenant=request.user.tenant,
        actor=request.user,
        store_mapping=store_mapping,
        platform_product_id=data["platform_product_id"],
        platform_variant_id=data["platform_variant_id"],
        platform_sku=data["platform_sku"],
        platform_detail=platform_detail,
    )
    return success_response(MarketplaceProductMappingSerializer(mapping).data, status=201)


@api_view(["GET", "PATCH"])
@permission_classes([IsMarketplaceProductMappingManager])
def product_mapping_detail(request, pk):
    raw_confirm = request.method == "PATCH" and request.data.get("manually_confirmed") is True
    permission_code = (
        PRODUCT_MAPPING_VIEW_PERMISSION
        if request.method == "GET"
        else PRODUCT_MAPPING_CONFIRM_PERMISSION
        if raw_confirm
        else PRODUCT_MAPPING_MANAGE_PERMISSION
    )
    queryset = filter_product_mappings(
        request.user,
        MarketplaceProductMapping.objects.filter(tenant=request.user.tenant).select_related(
            "sku", "platform_detail", "store_mapping", "store_mapping__store"
        ),
        permission_code,
    )
    mapping = get_scoped_object_or_404(queryset, pk=pk)
    if request.method == "GET":
        return success_response(MarketplaceProductMappingSerializer(mapping).data)

    if not request.data:
        raise ValidationError("No supported product mapping fields were provided.")
    reject_raw_credential_fields(request.data)
    serializer = ProductMappingUpdateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    sku = None
    if data.get("sku_id"):
        from apps.products.models import ProductSKU

        sku = get_object_or_404(ProductSKU, tenant=request.user.tenant, pk=data["sku_id"])
    if data.get("status") == MarketplaceProductMapping.Status.INACTIVE:
        mapping = deactivate_product_mapping(mapping, actor=request.user)
    elif data.get("manually_confirmed"):
        if not check_user_permission(request.user, PRODUCT_MAPPING_CONFIRM_PERMISSION):
            raise PermissionDenied("缺少商品映射人工确认权限。")
        scoped_confirmation = filter_product_mappings(
            request.user,
            MarketplaceProductMapping.objects.filter(
                tenant=request.user.tenant,
                pk=mapping.pk,
            ),
            PRODUCT_MAPPING_CONFIRM_PERMISSION,
        )
        mapping = get_scoped_object_or_404(scoped_confirmation, pk=mapping.pk)
        mapping = confirm_product_mapping(
            mapping,
            actor=request.user,
            sku=sku,
            manually_confirmed=True,
            expected_internal_sku_id=data.get("expected_internal_sku_id"),
            replace_existing=data.get("replace_existing", False),
        )
    else:
        if sku is None or "confidence" not in data:
            raise ValidationError("Product mapping suggestions require a SKU and a confidence score.")
        mapping = suggest_product_mapping(mapping, actor=request.user, sku=sku, confidence=data["confidence"])
    return success_response(MarketplaceProductMappingSerializer(mapping).data)


@api_view(["POST"])
@permission_classes([IsIntegrationConfigDisabler])
def disable_integration_config(request, pk):
    config = _get_config_for_user(request, pk, "integrations.config.disable")
    with transaction.atomic():
        config.status = PlatformIntegrationConfig.Status.DISABLED
        config.save(update_fields=["status", "updated_at"])
        disabled_jobs = SyncJob.objects.filter(
            tenant=request.user.tenant,
            integration_config=config,
        ).update(is_enabled=False, status=SyncJob.Status.DISABLED, next_run_at=None)
        _write_audit_log(
            config,
            request.user,
            "disable",
            detail={"status": config.status, "disabled_job_count": disabled_jobs},
        )
    return success_response(PlatformIntegrationConfigSerializer(config).data)


@api_view(["POST"])
@permission_classes([IsIntegrationConfigDisabler])
def delete_integration_config(request, pk):
    config = _get_config_for_user(request, pk, "integrations.config.disable")
    if config.status != PlatformIntegrationConfig.Status.DISABLED:
        raise StateConflict("仅已禁用的接入配置可以删除。")
    with transaction.atomic():
        config = PlatformIntegrationConfig.objects.select_for_update().get(
            pk=config.pk,
            tenant=request.user.tenant,
        )
        if config.status != PlatformIntegrationConfig.Status.DISABLED:
            raise StateConflict("仅已禁用的接入配置可以删除。")
        SyncJob.objects.filter(
            tenant=request.user.tenant,
            integration_config=config,
        ).update(is_enabled=False, status=SyncJob.Status.DISABLED, next_run_at=None)
        _write_audit_log(
            config,
            request.user,
            "delete",
            detail={"status": config.status, "soft_deleted": True},
        )
        config.deleted_at = timezone.now()
        config.save(update_fields=["deleted_at", "updated_at"])
    return success_response({"id": config.id, "deleted": True})


@api_view(["POST"])
@permission_classes([IsIntegrationConfigVerifier])
def verify_integration_config(request, pk):
    config = _get_config_for_user(request, pk, "integrations.config.verify")
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


@api_view(["POST"])
@permission_classes([IsIntegrationConfigVerifier])
def check_integration_reference(request, pk):
    config = _get_config_for_user(request, pk, "integrations.config.verify")
    if not config.credential_id:
        raise ValidationError("开发者凭据引用不完整，请先维护凭据。")
    if config.credential_status in {
        PlatformIntegrationConfig.CredentialStatus.UNCONFIGURED,
        PlatformIntegrationConfig.CredentialStatus.REVOKED,
    }:
        raise ValidationError("开发者凭据当前不可用，请重新维护凭据。")
    if config.platform in {PlatformChoices.SHOPEE, PlatformChoices.TIKTOK, PlatformChoices.JIFENG_WMS}:
        try:
            get_custody_backend().retrieve_secret(config.credential_id)
        except CustodyError:
            raise ValidationError("当前凭据仍是交接包旧引用或已失效，请通过“维护凭据”重新加密保存。") from None
    config.last_verified_at = timezone.now()
    if config.status != PlatformIntegrationConfig.Status.DISABLED:
        config.status = PlatformIntegrationConfig.Status.VERIFIED
    config.save(update_fields=["status", "last_verified_at", "updated_at"])
    _write_audit_log(
        config,
        request.user,
        "verify_credential_reference",
        detail={"external_api_called": False, "token_refreshed": False},
    )
    return success_response({"verified": True, "external_api_called": False, "token_refreshed": False, "checked_at": config.last_verified_at})


def _warehouse_binding_summary(config):
    countries = [
        str(country or "").upper()
        for country in WarehouseAuthorization.objects.filter(
            tenant_id=config.tenant_id,
            integration_config=config,
        ).values_list("warehouse__country_code", flat=True)
    ]
    regions = {str(value).upper() for value in (config.regions or [])}
    return {
        "count": len(countries),
        "invalid_region_count": sum(1 for country in countries if country not in regions),
    }


@api_view(["POST"])
@permission_classes([IsIntegrationConfigVerifier])
def check_integration_consistency(request, pk):
    config = _get_config_for_user(request, pk, "integrations.config.verify")
    regions = {str(value).upper() for value in (config.regions or [])}
    store_bindings = list(
        MarketplaceStoreAuthorization.objects.filter(tenant=request.user.tenant, integration_config=config).values("region", "status")
    )
    warehouse = _warehouse_binding_summary(config)
    invalid_store_regions = sum(1 for binding in store_bindings if str(binding["region"] or "").upper() not in regions)
    credential_ready = bool(config.credential_id) and config.credential_status not in {
        PlatformIntegrationConfig.CredentialStatus.UNCONFIGURED,
        PlatformIntegrationConfig.CredentialStatus.REVOKED,
    }
    checks = {
        "credential_reference": credential_ready,
        "region_configuration": bool(regions),
        "binding_regions": invalid_store_regions + warehouse["invalid_region_count"] == 0,
        "config_enabled": config.status != PlatformIntegrationConfig.Status.DISABLED,
    }
    passed = all(checks.values())
    job_count = SyncJob.objects.filter(tenant=request.user.tenant, integration_config=config).count()
    _write_audit_log(
        config,
        request.user,
        "test_simulated_integration_connection",
        result=IntegrationAuditLog.Result.SUCCESS if passed else IntegrationAuditLog.Result.BLOCKED,
        detail={"external_api_called": False, "token_refreshed": False, "binding_count": len(store_bindings) + warehouse["count"], "job_reference_count": job_count, "checks": checks},
    )
    if not passed:
        raise ValidationError("本地配置、凭据引用或授权映射存在不一致，请按检查结果处理。")
    return success_response({"connected": True, "simulated": True, "external_api_called": False, "token_refreshed": False, "binding_count": len(store_bindings) + warehouse["count"], "job_reference_count": job_count, "checks": checks})


@api_view(["POST"])
@permission_classes([IsIntegrationLiveReadonlyRunner])
def check_integration_readonly_connection(request, pk):
    if not isinstance(request.data, dict):
        raise ValidationError("只读检查请求必须是 JSON 对象。")
    if set(request.data) - {"warehouse_authorization_id", "store_authorization_id"}:
        raise ValidationError("只读检查请求包含不支持的字段。")
    warehouse_authorization_id = request.data.get("warehouse_authorization_id")
    store_authorization_id = request.data.get("store_authorization_id")
    if warehouse_authorization_id is not None and store_authorization_id is not None:
        raise ValidationError("只读检查请求不能同时指定店铺授权和仓库授权。")
    if warehouse_authorization_id is not None:
        warehouse_authorization_id = positive_int(warehouse_authorization_id, default=None)
        if warehouse_authorization_id is None:
            raise ValidationError({"warehouse_authorization_id": "仓库授权 ID 无效。"})
    if store_authorization_id is not None:
        store_authorization_id = positive_int(store_authorization_id, default=None)
        if store_authorization_id is None:
            raise ValidationError({"store_authorization_id": "店铺授权 ID 无效。"})
    if warehouse_authorization_id is None and store_authorization_id is None:
        raise ValidationError("只读检查请求必须指定一个具体的店铺授权或仓库授权。")

    config = _get_config_for_user(request, pk, "integrations.run_live_readonly")
    warehouse_authorization = None
    store_authorization = None
    if warehouse_authorization_id is not None:
        if not check_user_permission(request.user, "integrations.warehouse.view"):
            raise DataScopeDenied(
                "当前角色没有查看仓库 API 授权的权限。",
                error_code=ErrorCode.PERMISSION_DENIED,
            )
        if not get_permission_data_scopes(request.user, "integrations.warehouse.view"):
            raise DataScopeDenied(
                "仓库 API 授权查看权限尚未声明数据范围。",
                error_code=ErrorCode.DATA_SCOPE_MISSING,
            )
        warehouse_queryset = WarehouseAuthorization.objects.filter(
            tenant=request.user.tenant,
            integration_config=config,
            status=WarehouseAuthorization.Status.ACTIVE,
        )
        warehouse_authorization = get_scoped_object_or_404(
            filter_warehouse_authorizations(
                request.user,
                warehouse_queryset,
                "integrations.warehouse.view",
            ),
            pk=warehouse_authorization_id,
        )
        job_queryset = SyncJob.objects.filter(
            tenant=request.user.tenant,
            integration_config=config,
            warehouse_authorization=warehouse_authorization,
            resource_type=SyncJob.ResourceType.INVENTORY_SNAPSHOT,
        )
    elif store_authorization_id is not None:
        if not check_user_permission(request.user, "integrations.store.view"):
            raise DataScopeDenied(
                "当前角色没有查看店铺 API 授权的权限。",
                error_code=ErrorCode.PERMISSION_DENIED,
            )
        if not get_permission_data_scopes(request.user, "integrations.store.view"):
            raise DataScopeDenied(
                "店铺 API 授权查看权限尚未声明数据范围。",
                error_code=ErrorCode.DATA_SCOPE_MISSING,
            )
        store_queryset = MarketplaceStoreAuthorization.objects.filter(
            tenant=request.user.tenant,
            integration_config=config,
            status=MarketplaceStoreAuthorization.Status.ACTIVE,
        )
        store_authorization = get_scoped_object_or_404(
            filter_store_authorizations(
                request.user,
                store_queryset,
                "integrations.store.view",
            ),
            pk=store_authorization_id,
        )
        job_queryset = SyncJob.objects.filter(
            tenant=request.user.tenant,
            integration_config=config,
            store_authorization=store_authorization,
            resource_type__in=(
                SyncJob.ResourceType.SALES_ORDER,
                SyncJob.ResourceType.REFUND_RETURN,
            ),
        )
    # Subject authorization is complete only after the concrete binding and
    # its candidate job have both been narrowed by the run scope.  Runtime
    # switches and custody/adapter access intentionally happen afterwards.
    job_queryset = filter_sync_jobs(
        request.user,
        job_queryset.select_related("integration_config"),
        "integrations.run_live_readonly",
    )
    job = job_queryset.first()
    if job is None:
        raise ValidationError("当前配置没有可用于只读检查的已授权同步任务。")
    if get_runtime_setting("network", "mode", default="") != "approved-live-test":
        raise ValidationError("系统尚未启用生产平台只读网络模式；请由运维确认网络白名单后再检查。")
    if not get_runtime_setting("network", "readonly_sync_enabled", default=False):
        raise ValidationError("系统尚未启用生产只读同步功能。")
    if config.status not in {PlatformIntegrationConfig.Status.VERIFIED, PlatformIntegrationConfig.Status.ACTIVE}:
        raise ValidationError("请先维护并检查开发者凭据，再执行平台只读检查。")
    try:
        get_custody_backend().retrieve_secret(config.credential_id)
    except CustodyError:
        raise ValidationError("开发者凭据无法读取，请通过“维护凭据”重新加密保存。") from None
    adapter = get_adapter_for_config(config, job.resource_type)
    try:
        adapter.validate_configuration(job)
        page = adapter.fetch_page(job, None)
    except CustodyError:
        _write_audit_log(config, request.user, "test_live_integration_connection", result=IntegrationAuditLog.Result.FAILED, detail={"external_api_called": False, "token_refreshed": False, "reason": "credential_unavailable"})
        raise ValidationError("平台或主体授权凭据无法读取，请重新维护开发者凭据并检查基础档案授权。") from None
    except Exception:
        _write_audit_log(config, request.user, "test_live_integration_connection", result=IntegrationAuditLog.Result.FAILED, detail={"external_api_called": True, "token_refreshed": False})
        raise
    config.last_verified_at = timezone.now()
    config.save(update_fields=["last_verified_at", "updated_at"])
    if warehouse_authorization is not None:
        warehouse_authorization.last_verified_at = config.last_verified_at
        warehouse_authorization.updated_by = request.user
        warehouse_authorization.save(update_fields=["last_verified_at", "updated_by", "updated_at"])
    _write_audit_log(
        config,
        request.user,
        "test_live_integration_connection",
        detail={
            "external_api_called": True,
            "token_refreshed": False,
            "resource_type": job.resource_type,
            "store_authorization_id": store_authorization.id if store_authorization else None,
            "warehouse_authorization_id": warehouse_authorization.id if warehouse_authorization else None,
        },
    )
    return success_response({"connected": True, "external_api_called": True, "token_refreshed": False, "sample_count": len(page.get("records", [])) if isinstance(page, dict) else 0, "checked_at": config.last_verified_at})


@api_view(["GET", "POST"])
@permission_classes([IsIntegrationReadOrManage])
def sync_job_collection(request):
    if request.method == "GET":
        queryset = filter_sync_jobs(
            request.user,
            SyncJob.objects.filter(tenant=request.user.tenant).select_related("integration_config"),
            "integrations.view",
        )
        return success_response(SyncJobSerializer(queryset, many=True, context={"request": request}).data)

    serializer = SyncJobSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    integration_config = PlatformIntegrationConfig.objects.get(
        tenant=request.user.tenant,
        pk=serializer.validated_data["integration_config_id"],
    )
    warehouse_authorization_id = serializer.validated_data.get("warehouse_authorization_id")
    store_authorization_id = serializer.validated_data.get("store_authorization_id")
    warehouse_id = None
    warehouse_country = None
    store_id = None
    store_region = None
    if warehouse_authorization_id:
        warehouse_id, warehouse_country = WarehouseAuthorization.objects.filter(
            tenant=request.user.tenant,
            pk=warehouse_authorization_id,
        ).values_list("warehouse_id", "warehouse__country_code").first() or (None, None)
    if store_authorization_id:
        store_id, store_region = MarketplaceStoreAuthorization.objects.filter(
            tenant=request.user.tenant,
            pk=store_authorization_id,
        ).values_list("store_id", "region").first() or (None, None)
    config_regions = [
        str(region).strip().upper()
        for region in (integration_config.regions or [])
        if str(region).strip()
    ]
    concrete_region = warehouse_country or store_region
    effective_regions = list(dict.fromkeys(config_regions + ([str(concrete_region).strip().upper()] if concrete_region else ["__UNKNOWN__"])))
    if not integration_values_allowed(
        request.user,
        "integrations.manage",
        platform=integration_config.platform,
        environment=integration_config.environment,
        # A global config is evaluated against the concrete subject region;
        # otherwise a regional role could create an SG warehouse job from a
        # config whose regions list is empty.
        regions=effective_regions,
        config_id=integration_config.id,
        resource_type=serializer.validated_data["resource_type"],
        store_id=store_id,
        warehouse_id=warehouse_id,
    ):
        raise DataScopeDenied(
            "Sync job is outside the authorized data scope.",
            error_code=ErrorCode.DATA_SCOPE_FORBIDDEN,
        )
    # Inventory jobs are intentionally idempotent per authorization/resource.
    # The UI can safely offer “创建库存同步任务” without producing duplicate
    # schedules when an operator retries or refreshes after a successful POST.
    if warehouse_authorization_id:
        existing_job = SyncJob.objects.filter(
            tenant=request.user.tenant,
            warehouse_authorization_id=warehouse_authorization_id,
            resource_type=serializer.validated_data["resource_type"],
        ).first()
        if existing_job is not None:
            payload = SyncJobSerializer(existing_job, context={"request": request}).data
            return success_response(
                {"idempotent": True, "sync_job": payload, "job": payload},
                status=200,
            )
    job = serializer.save(tenant=request.user.tenant)
    return success_response(SyncJobSerializer(job, context={"request": request}).data, status=201)


def _scoped_sync_job(request, pk, permission_code="integrations.manage"):
    return get_scoped_object_or_404(
        filter_sync_jobs(
            request.user,
            SyncJob.objects.filter(tenant=request.user.tenant).select_related("integration_config"),
            permission_code,
        ),
        pk=pk,
    )


def _set_job_scope(job, values):
    scope = dict(job.sync_scope or {})
    schedule = scope.get("schedule") if isinstance(scope.get("schedule"), dict) else {}
    query = scope.get("query") if isinstance(scope.get("query"), dict) else {}
    if "execution_mode" in values:
        scope["execution_mode"] = values["execution_mode"]
    for key in ("interval_minutes", "local_time", "weekdays", "timezone", "catch_up", "pause_until"):
        if key in values:
            schedule[key] = values[key]
    query_fields = {
        "query_mode": "mode",
        "lookback_days": "lookback_days",
        "overlap_minutes": "overlap_minutes",
        "query_page_size": "page_size",
        "max_pages": "max_pages",
        "max_records": "max_records",
        "range_start_at": "start_at",
        "range_end_at": "end_at",
        "query_statuses": "statuses",
    }
    for source, target in query_fields.items():
        if source in values:
            query[target] = values[source]
    scope["schedule"] = schedule
    scope["query"] = query
    job.sync_scope = scope


def _validated_job_policy(data):
    allowed = {
        "schedule_type", "max_retry_count", "backoff_base_seconds", "execution_mode",
        "interval_minutes", "local_time", "weekdays", "timezone", "catch_up", "pause_until",
        "query_mode", "lookback_days", "overlap_minutes", "query_page_size", "max_pages",
        "max_records", "range_start_at", "range_end_at", "query_statuses",
    }
    if set(data) - allowed:
        raise ValidationError("同步策略包含不支持的字段。")
    values = dict(data)
    choices = {
        "schedule_type": {"manual", "hourly", "interval", "daily", "weekly", "cron"},
        "execution_mode": {"simulation", "live_readonly"},
        "catch_up": {"run_once", "skip"},
        "query_mode": {"incremental", "range"},
    }
    for key, valid in choices.items():
        if key in values and values[key] not in valid:
            raise ValidationError({key: "策略选项无效。"})
    limits = {
        "max_retry_count": (0, 10),
        "backoff_base_seconds": (1, 5),
        "interval_minutes": (15, 10080),
        "lookback_days": (1, 3650),
        "overlap_minutes": (0, 1440),
        "query_page_size": (1, 100),
        "max_pages": (1, 1000),
        "max_records": (1, 100000),
    }
    for key, (minimum, maximum) in limits.items():
        if key not in values:
            continue
        try:
            values[key] = int(values[key])
        except (TypeError, ValueError):
            raise ValidationError({key: "必须为整数。"})
        if not minimum <= values[key] <= maximum:
            raise ValidationError({key: f"必须在 {minimum} 到 {maximum} 之间。"})
    if "weekdays" in values:
        if not isinstance(values["weekdays"], list):
            raise ValidationError({"weekdays": "每周执行日必须为数组。"})
        try:
            values["weekdays"] = sorted({int(day) for day in values["weekdays"]})
        except (TypeError, ValueError):
            raise ValidationError({"weekdays": "每周执行日无效。"})
        if any(day < 1 or day > 7 for day in values["weekdays"]):
            raise ValidationError({"weekdays": "每周执行日必须在周一到周日之间。"})
    if "query_statuses" in values:
        statuses = values["query_statuses"]
        if isinstance(statuses, str):
            statuses = [item.strip() for item in statuses.split(",") if item.strip()]
        if not isinstance(statuses, list):
            raise ValidationError({"query_statuses": "查询状态必须为列表或逗号分隔文本。"})
        values["query_statuses"] = statuses
    for key in ("local_time", "timezone", "pause_until", "range_start_at", "range_end_at"):
        if key in values and values[key] is not None and not isinstance(values[key], str):
            raise ValidationError({key: "必须为文本。"})
    if values.get("schedule_type") in {"daily", "weekly"} and not values.get("local_time"):
        raise ValidationError({"local_time": "定时任务必须填写执行时间。"})
    if values.get("schedule_type") == "weekly" and not values.get("weekdays"):
        raise ValidationError({"weekdays": "每周任务必须选择执行日。"})
    if "timezone" in values and not values["timezone"].strip():
        raise ValidationError({"timezone": "执行时区不能为空。"})
    if values.get("query_mode") == "range" and (not values.get("range_start_at") or not values.get("range_end_at")):
        raise ValidationError({"query_mode": "指定时间范围时必须填写开始和结束时间。"})
    return values


@api_view(["GET", "PATCH"])
@permission_classes([IsIntegrationReadOrManage])
def sync_job_detail(request, pk):
    permission_code = "integrations.view" if request.method == "GET" else "integrations.manage"
    job = _scoped_sync_job(request, pk, permission_code)
    if request.method == "GET":
        return success_response(SyncJobSerializer(job, context={"request": request}).data)
    if job.status == SyncJob.Status.RUNNING:
        raise ValidationError("运行中的同步任务不能修改。")
    values = _validated_job_policy(request.data)
    core_fields = {"schedule_type", "max_retry_count", "backoff_base_seconds"}
    changed_core = [key for key in core_fields if key in values]
    with transaction.atomic():
        for key in changed_core:
            setattr(job, key, values[key])
        _set_job_scope(job, values)
        update_fields = [*changed_core, "sync_scope"]
        if {"schedule_type", "interval_minutes", "local_time", "weekdays", "timezone", "pause_until"} & set(values):
            job.next_run_at = calculate_next_run_at(job)
            update_fields.append("next_run_at")
        job.save(update_fields=[*dict.fromkeys(update_fields), "updated_at"])
    _write_audit_log(job.integration_config, request.user, "update_sync_job", detail={"sync_job_id": job.id, "updated_fields": sorted(request.data.keys())})
    return success_response(SyncJobSerializer(job, context={"request": request}).data)


@api_view(["POST"])
@permission_classes([IsIntegrationManager])
def toggle_sync_job(request, pk):
    if not is_module_enabled("api_integrations"):
        raise ValidationError("API data integration module is disabled.")
    job = _scoped_sync_job(request, pk)
    if job.status == SyncJob.Status.RUNNING:
        raise ValidationError("运行中的同步任务不能切换启用状态。")
    enabled = request.data.get("enabled") is True
    if enabled:
        if job.integration_config.status == PlatformIntegrationConfig.Status.DISABLED:
            raise ValidationError("关联接入配置已禁用。")
        if not job.integration_config.credential_id or job.integration_config.credential_status in {
            PlatformIntegrationConfig.CredentialStatus.UNCONFIGURED,
            PlatformIntegrationConfig.CredentialStatus.REVOKED,
        }:
            raise ValidationError("开发者凭据尚未就绪。")
    job.is_enabled = enabled
    job.status = SyncJob.Status.IDLE if enabled else SyncJob.Status.DISABLED
    job.next_run_at = None
    job.save(update_fields=["is_enabled", "status", "next_run_at", "updated_at"])
    _write_audit_log(job.integration_config, request.user, "enable_sync_job" if enabled else "disable_sync_job", detail={"sync_job_id": job.id})
    return success_response(SyncJobSerializer(job, context={"request": request}).data)


def _sync_job_delete_preview(job):
    run_count = SyncRun.objects.filter(tenant=job.tenant, sync_job=job).count()
    cursor_count = job.cursors.count()
    blockers = []
    if job.is_enabled or job.status == SyncJob.Status.RUNNING:
        blockers.append("请先停用同步任务")
    if job.lock_token or job.lock_acquired_at or job.lock_expires_at or job.lock_heartbeat_at:
        blockers.append("任务仍保留运行锁")
    if run_count:
        blockers.append("任务已有运行记录，需保留审计链路")
    if cursor_count:
        blockers.append("任务已有同步游标，不能直接删除")
    return {"can_delete": not blockers, "run_count": run_count, "cursor_count": cursor_count, "blockers": blockers}


@api_view(["GET", "POST"])
@permission_classes([IsIntegrationReadOrManage])
def sync_job_delete(request, pk):
    job = _scoped_sync_job(request, pk, "integrations.view" if request.method == "GET" else "integrations.manage")
    preview = _sync_job_delete_preview(job)
    if request.method == "GET":
        return success_response(preview)
    if not preview["can_delete"]:
        raise ValidationError(preview["blockers"][0])
    config = job.integration_config
    job_id = job.id
    job.delete()
    _write_audit_log(config, request.user, "delete_sync_job", detail={"sync_job_id": job_id})
    return success_response({"deleted": True, "job_id": job_id})


@api_view(["GET"])
@permission_classes([IsIntegrationViewer])
def sync_run_collection(request):
    queryset = filter_sync_runs(
        request.user,
        SyncRun.objects.filter(tenant=request.user.tenant).select_related("sync_job", "sync_job__integration_config"),
        "integrations.view",
    )
    return success_response(SyncRunSerializer(queryset, many=True).data)


@api_view(["GET"])
@permission_classes([IsIntegrationViewer])
def sync_run_detail(request, pk):
    queryset = filter_sync_runs(
        request.user,
        SyncRun.objects.filter(tenant=request.user.tenant).select_related("sync_job", "sync_job__integration_config"),
        "integrations.view",
    )
    sync_run = get_scoped_object_or_404(queryset, pk=pk)
    return success_response(SyncRunSerializer(sync_run).data)


def _incident_queryset(request, permission_code):
    visible_job_ids = filter_sync_jobs(
        request.user,
        SyncJob.objects.filter(tenant=request.user.tenant),
        permission_code,
    ).values_list("id", flat=True)
    return SyncAlertIncident.objects.filter(
        tenant=request.user.tenant,
        sync_job_id__in=visible_job_ids,
    ).select_related(
        "sync_job", "sync_job__integration_config", "assignee", "acknowledged_by",
        "resolved_by", "last_sync_run", "notification",
    )


@api_view(["GET"])
@permission_classes([IsIntegrationViewer])
def sync_alert_incident_collection(request):
    if set(request.query_params) - {"status", "store_id"}:
        raise ValidationError("Unknown sync incident query parameter.")
    queryset = _incident_queryset(request, "integrations.view")
    if request.query_params.get("store_id"):
        store_id = positive_int(request.query_params.get("store_id"), default=None)
        if store_id is None:
            raise ValidationError({"store_id": "店铺 ID 无效。"})
        store_filter = Q(sync_job__store_authorization__store_id=store_id)
        # Some deployments carry a denormalized SyncJob.store_id.  Keep the
        # filter compatible with both schemas while the authorization relation
        # remains the canonical source in this checkout.
        if any(field.name == "store_id" for field in SyncJob._meta.fields):
            store_filter |= Q(sync_job__store_id=store_id)
        queryset = queryset.filter(store_filter)
    status_value = str(request.query_params.get("status") or "").strip()
    if status_value:
        if status_value not in SyncAlertIncident.Status.values:
            raise ValidationError({"status": "Unsupported incident status."})
        queryset = queryset.filter(status=status_value)
    return success_response(SyncAlertIncidentSerializer(queryset, many=True).data)


@api_view(["POST"])
@permission_classes([IsIntegrationManager])
def sync_alert_incident_action(request, pk):
    if not isinstance(request.data, dict) or not request.data.get("action"):
        raise ValidationError({"action": "Incident action is required."})
    allowed_fields = {"action", "assignee_id", "note"}
    if set(request.data) - allowed_fields:
        raise ValidationError("Unsupported incident action field.")
    action = str(request.data["action"]).strip().lower()
    with transaction.atomic():
        incident = get_scoped_object_or_404(
            _incident_queryset(request, "integrations.manage").select_for_update(), pk=pk
        )
        note = request.data.get("note", "")
        if action == "acknowledge":
            incident = acknowledge_incident(incident, request.user, note)
        elif action == "assign":
            assignee_id = positive_int(request.data.get("assignee_id"), default=None, maximum=2147483647)
            if assignee_id is None:
                raise ValidationError({"assignee_id": "An assignee is required."})
            assignee = get_object_or_404(
                get_user_model().objects.filter(tenant=request.user.tenant, is_active=True), pk=assignee_id
            )
            incident = assign_incident(incident, request.user, assignee, note)
        elif action == "note":
            incident = add_incident_note(incident, request.user, note)
        elif action == "resolve":
            incident = resolve_incident(incident, request.user, note)
        else:
            raise ValidationError({"action": "Supported actions are acknowledge, assign, note and resolve."})
    return success_response(SyncAlertIncidentSerializer(incident).data)


def _retry_preview(incident):
    source_run = incident.last_sync_run
    job = incident.sync_job
    execution_mode = (source_run.masked_log or {}).get("execution_mode", "simulation") if source_run else ""
    reason = ""
    if incident.status == SyncAlertIncident.Status.RESOLVED:
        reason = "事件已解决。"
    elif source_run is None or source_run.status != SyncRun.Status.FAILED:
        reason = "事件没有可重试的失败运行。"
    elif job.integration_config.environment not in {
        PlatformIntegrationConfig.Environment.MOCK, PlatformIntegrationConfig.Environment.SANDBOX,
    }:
        reason = "人工重试仅允许 Mock 或沙箱环境。"
    elif execution_mode == "live_readonly":
        reason = "live_readonly 运行不能通过事件工作台重试。"
    elif not job.is_enabled or job.status == SyncJob.Status.DISABLED:
        reason = "同步任务已禁用。"
    elif job.status == SyncJob.Status.RUNNING:
        reason = "同步任务已有运行中的实例。"
    return {
        "incident_id": incident.id,
        "sync_job_id": job.id,
        "source_sync_run_id": source_run.id if source_run else None,
        "source_run_id": source_run.run_id if source_run else "",
        "environment": job.integration_config.environment,
        "execution_mode": "simulation",
        "external_api_called": False,
        "allowed": not reason,
        "blocked_reason": reason,
        "requires_confirmation": True,
    }


@api_view(["GET", "POST"])
@permission_classes([IsIntegrationRunner])
def sync_alert_incident_retry(request, pk):
    incident = get_scoped_object_or_404(_incident_queryset(request, "integrations.run"), pk=pk)
    preview = _retry_preview(incident)
    if request.method == "GET":
        return success_response(preview)
    if not isinstance(request.data, dict) or set(request.data) != {"confirmed", "idempotency_key"}:
        raise ValidationError("confirmed and idempotency_key are required; no other fields are accepted.")
    if request.data.get("confirmed") is not True:
        raise ValidationError({"confirmed": "Explicit confirmation is required."})
    idempotency_key = str(request.data.get("idempotency_key") or "").strip()
    if not 8 <= len(idempotency_key) <= 100:
        raise ValidationError({"idempotency_key": "Idempotency key must be 8 to 100 characters."})
    scoped_idempotency_key = f"incident:{incident.id}:{idempotency_key}"
    existing = SyncRun.objects.filter(
        tenant=incident.tenant,
        sync_job=incident.sync_job,
        idempotency_key=scoped_idempotency_key,
    ).first()
    if existing:
        return success_response({
            "created": False, "incident_id": incident.id,
            "run": SyncRunSerializer(existing).data,
        })
    if not preview["allowed"]:
        raise ValidationError(preview["blocked_reason"])
    source_run = incident.last_sync_run
    run, created = run_sync_job(
        incident.sync_job,
        adapter=MockPlatformAdapter(),
        idempotency_key=scoped_idempotency_key,
    )
    if created:
        run.masked_log = {
            **(run.masked_log or {}), "execution_mode": "simulation",
            "manual_retry_of": source_run.run_id, "external_api_called": False,
            "confirmed_by": request.user.id,
        }
        run.save(update_fields=["masked_log"])
        _write_audit_log(
            incident.sync_job.integration_config, request.user, "retry_sync_incident",
            detail={
                "incident_id": incident.id, "source_run_id": source_run.run_id,
                "retry_run_id": run.run_id, "external_api_called": False,
            },
        )
    return success_response({
        "created": created, "incident_id": incident.id,
        "run": SyncRunSerializer(run).data,
    }, status=201 if created else 200)


@api_view(["POST"])
@permission_classes([IsIntegrationRunner])
def retry_sync_run(request, pk):
    sync_run = get_scoped_object_or_404(
        filter_sync_runs(
            request.user,
            SyncRun.objects.filter(tenant=request.user.tenant).select_related("sync_job", "sync_job__integration_config"),
            "integrations.run",
        ),
        pk=pk,
    )
    if sync_run.status != SyncRun.Status.FAILED:
        raise ValidationError("只有失败的本地模拟运行可以重试。")
    if sync_run.retry_count >= sync_run.sync_job.max_retry_count:
        raise ValidationError("该运行已达到最大重试次数。")
    execution_mode = (sync_run.masked_log or {}).get("execution_mode", "simulation")
    if execution_mode == "live_readonly":
        raise ValidationError("生产只读任务请返回同步任务页重新确认运行。")
    run, _created = run_sync_job(
        sync_run.sync_job,
        adapter=MockPlatformAdapter(),
        idempotency_key=f"retry:{sync_run.id}:{uuid.uuid4().hex}",
    )
    run.retry_count = sync_run.retry_count + 1
    run.masked_log = {**(run.masked_log or {}), "execution_mode": "simulation", "retry_of": sync_run.run_id}
    run.save(update_fields=["retry_count", "masked_log"])
    _write_audit_log(sync_run.sync_job.integration_config, request.user, "retry_simulated_sync_run", detail={"source_run_id": sync_run.run_id, "retry_run_id": run.run_id, "external_api_called": False})
    return success_response(SyncRunSerializer(run).data, status=201)


@api_view(["POST"])
@permission_classes([IsIntegrationRunner])
def run_mock_sync_job(request, pk):
    sync_job = get_scoped_object_or_404(
        filter_sync_jobs(
            request.user,
            SyncJob.objects.filter(tenant=request.user.tenant).select_related("integration_config"),
            "integrations.run",
        ),
        pk=pk,
    )
    run, created = run_sync_job(sync_job, idempotency_key=request.data.get("idempotency_key"))
    return success_response({"created": created, "run": SyncRunSerializer(run).data})


@api_view(["POST"])
@permission_classes([IsIntegrationLiveReadonlyRunner])
def enqueue_sync_job(request, pk):
    if not is_module_enabled("api_integrations"):
        raise ValidationError("API data integration module is disabled.")
    sync_job = get_scoped_object_or_404(
        filter_sync_jobs(
            request.user,
            SyncJob.objects.filter(tenant=request.user.tenant).select_related("integration_config"),
            "integrations.run_live_readonly",
        ),
        pk=pk,
    )
    idempotency_key = str(request.data.get("idempotency_key") or "").strip() or None
    if idempotency_key and len(idempotency_key) > 160:
        raise ValidationError({"idempotency_key": "Idempotency key cannot exceed 160 characters."})
    task = run_readonly_sync_job.delay(sync_job.id, idempotency_key)
    return success_response({"accepted": True, "task_id": task.id}, status=202)


@api_view(["POST"])
@permission_classes([IsIntegrationManager])
def disable_sync_job(request, pk):
    sync_job = get_scoped_object_or_404(
        filter_sync_jobs(
            request.user,
            SyncJob.objects.filter(tenant=request.user.tenant).select_related("integration_config"),
            "integrations.manage",
        ),
        pk=pk,
    )
    sync_job.is_enabled = False
    sync_job.status = SyncJob.Status.DISABLED
    sync_job.save(update_fields=["is_enabled", "status", "updated_at"])
    return success_response(SyncJobSerializer(sync_job, context={"request": request}).data)
