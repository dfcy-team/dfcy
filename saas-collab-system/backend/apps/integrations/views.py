import json
import uuid

from django.conf import settings
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from urllib.parse import urlencode
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.common.error_codes import ErrorCode
from apps.common.exceptions import DataScopeDenied, StateConflict, get_scoped_object_or_404
from apps.common.responses import error_response, success_response
from apps.common.query import pagination_query, positive_int
from apps.common.responses import paginated_data
from apps.workflows.models import CollaborationEvent
from apps.workflows.serializers import CollaborationEventSerializer
from apps.workflows.services import receive_mock_collaboration_event
from apps.masterdata.models import StoreMaster
from apps.permissions.api_permissions import (
    IsIntegrationCredentialRotator,
    IsIntegrationManager,
    IsIntegrationReadOrManage,
    IsIntegrationRunner,
    IsIntegrationViewer,
    IsInternalUser,
    IsMarketplaceCredentialRotator,
    IsMarketplaceStoreAuthorizer,
    IsMarketplaceStoreRetryRunner,
    IsMarketplaceStoreRevoker,
    IsMarketplaceStoreViewer,
)
from apps.permissions.services import get_permission_data_scopes, user_has_integration_permission
from apps.permissions.ui_p6_scopes import (
    filter_integration_configs,
    filter_sync_jobs,
    filter_sync_runs,
    integration_values_allowed,
    filter_store_authorizations,
)

from .credential_service import reject_raw_credential_fields, rotate_config_references
from .models import (
    IntegrationAuditLog,
    MarketplaceOAuthAction,
    MarketplaceStoreAuthorization,
    PlatformIntegrationConfig,
    SyncJob,
    SyncRun,
)
from .models import MarketplaceOAuthAttempt
from .oauth_adapters import OAuthAdapterError, SyntheticMarketplaceAdapter
from .oauth_serializers import MarketplaceOAuthAttemptSerializer
from .oauth_services import (
    begin_callback_handoff,
    begin_oauth_action,
    complete_oauth_action,
    exchange_callback,
    fail_oauth_action,
    fail_attempt,
    claim_oauth_action,
    initiate_oauth,
    refresh_authorization,
    revoke_authorization,
    _require_synthetic,
    _update_operation,
    wait_for_oauth_action,
)
from .serializers import (
    MarketplaceStoreAuthorizationSerializer,
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


def _get_config_for_user(request, pk, permission_code):
    queryset = filter_integration_configs(
        request.user,
        PlatformIntegrationConfig.objects.filter(tenant=request.user.tenant),
        permission_code,
    )
    return get_scoped_object_or_404(queryset, pk=pk)


@api_view(["GET", "POST"])
@permission_classes([IsIntegrationReadOrManage])
def integration_config_collection(request):
    if request.method == "GET":
        queryset = filter_integration_configs(
            request.user,
            PlatformIntegrationConfig.objects.filter(tenant=request.user.tenant),
            "integrations.view",
        )
        serializer = PlatformIntegrationConfigSerializer(queryset, many=True)
        return success_response(serializer.data)

    reject_raw_credential_fields(request.data)
    serializer = PlatformIntegrationConfigSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    if not integration_values_allowed(
        request.user,
        "integrations.manage",
        platform=serializer.validated_data["platform"],
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


@api_view(["GET", "PATCH"])
@permission_classes([IsIntegrationReadOrManage])
def integration_config_detail(request, pk):
    permission_code = "integrations.view" if request.method == "GET" else "integrations.manage"
    config = _get_config_for_user(request, pk, permission_code)
    if request.method == "GET":
        return success_response(PlatformIntegrationConfigSerializer(config).data)

    reject_raw_credential_fields(request.data)
    serializer = PlatformIntegrationConfigSerializer(config, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    candidate_platform = serializer.validated_data.get("platform", config.platform)
    if not integration_values_allowed(
        request.user,
        "integrations.manage",
        platform=candidate_platform,
        config_id=config.id,
    ):
        raise DataScopeDenied(
            "Integration configuration update is outside the authorized data scope.",
            error_code=ErrorCode.DATA_SCOPE_FORBIDDEN,
        )
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
    queryset = MarketplaceStoreAuthorization.objects.filter(tenant=request.user.tenant).select_related("store")
    if request.query_params.get("platform"):
        platform = request.query_params["platform"]
        if platform not in {"shopee", "tiktok"}:
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
        MarketplaceStoreAuthorization.objects.filter(tenant=request.user.tenant).select_related("store"),
        "integrations.store.view",
    )
    authorization = get_scoped_object_or_404(queryset, pk=pk)
    return success_response(MarketplaceStoreAuthorizationSerializer(authorization).data)


OAUTH_TARGET_PERMISSIONS = {
    "authorize": "integrations.store.authorize",
    "refresh": "integrations.credential.rotate",
    "revoke": "integrations.store.revoke",
    "retry": "integrations.store.retry",
}


@api_view(["GET"])
@permission_classes([IsInternalUser])
def oauth_target_collection(request):
    action = str(request.query_params.get("action", "authorize"))
    permission_code = OAUTH_TARGET_PERMISSIONS.get(action)
    if not permission_code or set(request.query_params) - {"action"}:
        raise ValidationError("OAuth target action is invalid.")
    if not user_has_integration_permission(request.user, permission_code):
        raise PermissionDenied("The requested OAuth action is not permitted.")
    if not get_permission_data_scopes(request.user, permission_code):
        raise DataScopeDenied("The declared permission has no data scope.", error_code=ErrorCode.DATA_SCOPE_MISSING)
    if action == "authorize":
        configs = filter_integration_configs(
            request.user,
            PlatformIntegrationConfig.objects.filter(tenant=request.user.tenant),
            permission_code,
        )
        stores = StoreMaster.objects.filter(tenant=request.user.tenant).select_related("platform")
        config_data = [
            {
                "id": config.id,
                "platform": config.platform,
                "account_alias": config.account_alias,
                "environment": config.environment,
                "status": config.status,
            }
            for config in configs
        ]
        store_data = [
            {
                "store_id": store.id,
                "store_name": store.name,
                "platform": store.platform.platform_type,
                "region": store.country_code,
            }
            for store in stores
            if store.platform.platform_type in {"shopee", "tiktok"}
            and any(
                integration_values_allowed(
                    request.user,
                    permission_code,
                    platform=store.platform.platform_type,
                    config_id=config.id,
                    store_id=store.id,
                )
                for config in configs
            )
        ]
        return success_response({"action": action, "configs": config_data, "stores": store_data, "api_status": "mock"})
    queryset = filter_store_authorizations(
        request.user,
        MarketplaceStoreAuthorization.objects.filter(tenant=request.user.tenant).select_related("store"),
        permission_code,
    )
    return success_response({
        "action": action,
        "authorizations": MarketplaceStoreAuthorizationSerializer(queryset, many=True).data,
        "api_status": "mock",
    })


def _oauth_attempt_scope_allowed(user, attempt, permission_code="integrations.store.authorize"):
    return integration_values_allowed(
        user,
        permission_code,
        platform=attempt.platform,
        config_id=attempt.integration_config_id,
        store_id=attempt.store_id,
    )


@api_view(["POST"])
@permission_classes([IsMarketplaceStoreAuthorizer])
def oauth_initiate(request):
    try:
        _require_synthetic()
    except OAuthAdapterError as exc:
        return error_response(exc.error_code, "Synthetic OAuth is disabled in this environment.", status=exc.http_status)
    attempt, authorization_url, created = initiate_oauth(request=request, payload=request.data, actor=request.user)
    data = {
        **MarketplaceOAuthAttemptSerializer(attempt).data,
        "attempt_id": attempt.pk,
        "status": attempt.status,
        "api_status": "mock",
    }
    if authorization_url:
        data["authorization_url"] = authorization_url
    return success_response(
        data,
        status=201 if created else 200,
    )


@api_view(["GET"])
@permission_classes([IsInternalUser])
def oauth_attempt_detail(request, pk):
    attempt = get_scoped_object_or_404(
        MarketplaceOAuthAttempt.objects.filter(tenant=request.user.tenant),
        pk=pk,
    )
    permission_code = None
    if user_has_integration_permission(request.user, "integrations.store.authorize"):
        permission_code = "integrations.store.authorize"
    elif (
        user_has_integration_permission(request.user, "integrations.store.retry")
        and attempt.actions.filter(
            action=MarketplaceOAuthAction.Action.RETRY,
            internal_user=request.user,
        ).exists()
    ):
        permission_code = "integrations.store.retry"
    if not permission_code:
        raise PermissionDenied("OAuth attempt status is not permitted for this action.")
    if not _oauth_attempt_scope_allowed(request.user, attempt, permission_code):
        raise DataScopeDenied("OAuth attempt is outside the authorized store scope.", error_code=ErrorCode.DATA_SCOPE_FORBIDDEN)
    return success_response({**MarketplaceOAuthAttemptSerializer(attempt).data, "api_status": "mock"})


def _oauth_redirect(attempt, result, error_code=""):
    target = settings.MARKETPLACE_OAUTH_REDIRECT_TARGETS.get(attempt.redirect_target_code)
    if not target or not target.startswith("/") or target.startswith("//"):
        return success_response({"status": "failed", "error_code": "OAUTH_REDIRECT_INVALID"}, status=422)
    params = {"oauth_result": result, "attempt_id": str(attempt.pk)}
    if error_code:
        params["error_code"] = error_code
    return HttpResponseRedirect(f"{target}?{urlencode(params)}")


@api_view(["GET"])
@authentication_classes([])
@permission_classes([])
def oauth_callback(request, platform):
    try:
        _require_synthetic()
    except OAuthAdapterError as exc:
        return error_response(exc.error_code, "Synthetic OAuth is disabled in this environment.", status=exc.http_status)
    if platform not in {"shopee", "tiktok"}:
        return error_response(ErrorCode.VALIDATION_ERROR, "Unsupported OAuth platform.", status=400)
    query = {}
    for key in request.query_params:
        values = request.query_params.getlist(key)
        if len(values) != 1:
            return error_response("OAUTH_CALLBACK_INVALID", "Callback fields must occur once.", status=400)
        query[key] = values[0]
    state = query.get("state")
    if not state:
        return error_response("OAUTH_STATE_INVALID", "OAuth state is required.", status=422)
    attempt = None
    operation = None
    try:
        attempt, operation = begin_callback_handoff(platform=platform, state=state, request=request)
        from .oauth_adapters import SyntheticMarketplaceAdapter
        callback = SyntheticMarketplaceAdapter().validate_callback(platform=platform, query=query, expected_state=state)
        if callback.platform_store_id and callback.platform_store_id != f"synthetic-store-{attempt.store_id}":
            raise OAuthAdapterError("OAUTH_STORE_MISMATCH", 422)
        exchange_callback(
            attempt=attempt,
            callback=callback,
            operation_id=operation.operation_id_hash,
            operation_claim=operation,
        )
        return _oauth_redirect(attempt, "success")
    except OAuthAdapterError as exc:
        attempt = attempt or getattr(exc, "attempt", None)
        if operation:
            _update_operation(
                operation.operation_id_hash,
                claim=operation,
                status="failed",
                phase="callback_failed",
                error_code=exc.error_code,
                release=True,
            )
            fail_attempt(attempt, error_code=exc.error_code, actor=attempt.internal_user)
        if exc.error_code == "OAUTH_STATE_CONSUMED":
            return error_response(exc.error_code, "OAuth state was already consumed.", status=409)
        if not attempt:
            return error_response(exc.error_code, "OAuth state is invalid.", status=exc.http_status)
        return _oauth_redirect(attempt, "failed", exc.error_code)
    except Exception:
        if operation:
            _update_operation(
                operation.operation_id_hash,
                claim=operation,
                status="failed",
                phase="callback_failed",
                error_code="OAUTH_CALLBACK_FAILED",
                release=True,
            )
        if attempt:
            fail_attempt(attempt, error_code="OAUTH_CALLBACK_FAILED", actor=attempt.internal_user)
        else:
            return error_response("OAUTH_CALLBACK_FAILED", "OAuth callback failed.", status=503)
        return _oauth_redirect(attempt, "failed", "OAUTH_CALLBACK_FAILED")


def _get_scoped_authorization(request, pk, permission_code):
    queryset = filter_store_authorizations(
        request.user,
        MarketplaceStoreAuthorization.objects.filter(tenant=request.user.tenant).select_related("store", "integration_config"),
        permission_code,
    )
    return get_scoped_object_or_404(queryset, pk=pk)


@api_view(["POST"])
@permission_classes([IsMarketplaceCredentialRotator])
def refresh_store_authorization(request, pk):
    try:
        _require_synthetic()
    except OAuthAdapterError as exc:
        return error_response(exc.error_code, "Synthetic OAuth is disabled in this environment.", status=exc.http_status)
    authorization = _get_scoped_authorization(request, pk, "integrations.credential.rotate")
    if set(request.data) - {"scenario"}:
        raise ValidationError("Only the synthetic scenario field is accepted.")
    action, replay = begin_oauth_action(
        request=request,
        actor=request.user,
        action=MarketplaceOAuthAction.Action.REFRESH,
        object_type="store_authorization",
        object_id=pk,
        payload=request.data,
        authorization=authorization,
    )
    if replay and action.status == MarketplaceOAuthAction.Status.SUCCEEDED:
        return success_response(action.response_data, status=action.response_status)
    if replay and action.status in {MarketplaceOAuthAction.Status.FAILED, MarketplaceOAuthAction.Status.RECONCILE_REQUIRED}:
        return error_response(action.error_code or "OAUTH_ACTION_FAILED", "The OAuth refresh action requires review.", status=503)
    action, claimed = claim_oauth_action(action)
    if not claimed:
        action = wait_for_oauth_action(action)
        if action.status == MarketplaceOAuthAction.Status.SUCCEEDED:
            return success_response(action.response_data, status=action.response_status)
        return error_response("OAUTH_ACTION_IN_PROGRESS", "The OAuth action is already being processed.", status=409)
    operation_id = action.operation_id_hash
    try:
        updated = refresh_authorization(
            authorization=authorization,
            actor=request.user,
            operation_id=operation_id,
            operation_claim=action,
            scenario=request.data.get("scenario", ""),
        )
    except OAuthAdapterError as exc:
        _write_audit_log(authorization.integration_config, request.user, "oauth_refresh_failed", result=IntegrationAuditLog.Result.FAILED, detail={"error_code": exc.error_code, "operation": "synthetic"})
        fail_oauth_action(action, exc.error_code, reconcile=exc.error_code == "OAUTH_REFRESH_RECONCILE_REQUIRED")
        return error_response(exc.error_code, "Synthetic custody refresh failed.", status=exc.http_status)
    except Exception:
        fail_oauth_action(action, "OAUTH_REFRESH_FAILED", reconcile=True)
        return error_response("OAUTH_REFRESH_RECONCILE_REQUIRED", "Refresh requires reconciliation before retry.", status=503)
    data = {**MarketplaceStoreAuthorizationSerializer(updated).data, "api_status": "mock"}
    complete_oauth_action(action, data, authorization=updated)
    return success_response(data)


@api_view(["POST"])
@permission_classes([IsMarketplaceStoreRevoker])
def revoke_store_authorization(request, pk):
    try:
        _require_synthetic()
    except OAuthAdapterError as exc:
        return error_response(exc.error_code, "Synthetic OAuth is disabled in this environment.", status=exc.http_status)
    authorization = _get_scoped_authorization(request, pk, "integrations.store.revoke")
    if set(request.data) - {"scenario"}:
        raise ValidationError("Only the synthetic scenario field is accepted.")
    action, replay = begin_oauth_action(
        request=request,
        actor=request.user,
        action=MarketplaceOAuthAction.Action.REVOKE,
        object_type="store_authorization",
        object_id=pk,
        payload=request.data,
        authorization=authorization,
    )
    if replay and action.status == MarketplaceOAuthAction.Status.SUCCEEDED:
        return success_response(action.response_data, status=action.response_status)
    if replay and action.status in {MarketplaceOAuthAction.Status.FAILED, MarketplaceOAuthAction.Status.RECONCILE_REQUIRED}:
        return error_response(action.error_code or "OAUTH_ACTION_FAILED", "The OAuth revoke action requires review.", status=503)
    action, claimed = claim_oauth_action(action)
    if not claimed:
        action = wait_for_oauth_action(action)
        if action.status == MarketplaceOAuthAction.Status.SUCCEEDED:
            return success_response(action.response_data, status=action.response_status)
        return error_response("OAUTH_ACTION_IN_PROGRESS", "The OAuth action is already being processed.", status=409)
    operation_id = action.operation_id_hash
    try:
        updated = revoke_authorization(
            authorization=authorization,
            actor=request.user,
            operation_id=operation_id,
            operation_claim=action,
            scenario=request.data.get("scenario", ""),
        )
    except OAuthAdapterError as exc:
        _write_audit_log(authorization.integration_config, request.user, "oauth_revoke_failed", result=IntegrationAuditLog.Result.FAILED, detail={"error_code": exc.error_code, "operation": "synthetic"})
        fail_oauth_action(action, exc.error_code, reconcile=True)
        return error_response(exc.error_code, "Synthetic custody revoke failed; local authorization was not changed.", status=exc.http_status)
    except Exception:
        fail_oauth_action(action, "OAUTH_REVOKE_RECONCILE_REQUIRED", reconcile=True)
        return error_response("OAUTH_REVOKE_RECONCILE_REQUIRED", "Revoke requires reconciliation before retry.", status=503)
    data = {**MarketplaceStoreAuthorizationSerializer(updated).data, "api_status": "mock"}
    complete_oauth_action(action, data, authorization=updated)
    return success_response(data)


@api_view(["POST"])
@permission_classes([IsMarketplaceStoreRetryRunner])
def retry_store_authorization(request, pk):
    try:
        _require_synthetic()
    except OAuthAdapterError as exc:
        return error_response(exc.error_code, "Synthetic OAuth is disabled in this environment.", status=exc.http_status)
    authorization = _get_scoped_authorization(request, pk, "integrations.store.retry")
    if request.data:
        raise ValidationError("Retry does not accept a request body.")
    if authorization.status not in {
        MarketplaceStoreAuthorization.Status.ERROR,
        MarketplaceStoreAuthorization.Status.RECONCILE_REQUIRED,
    }:
        raise StateConflict("Only failed authorizations can be retried.")
    action, replay = begin_oauth_action(
        request=request,
        actor=request.user,
        action=MarketplaceOAuthAction.Action.RETRY,
        object_type="store_authorization",
        object_id=pk,
        payload=request.data,
        authorization=authorization,
    )
    if replay and action.status == MarketplaceOAuthAction.Status.SUCCEEDED:
        return success_response(dict(action.response_data), status=action.response_status)
    if replay and action.status in {MarketplaceOAuthAction.Status.FAILED, MarketplaceOAuthAction.Status.RECONCILE_REQUIRED}:
        return error_response(action.error_code or "OAUTH_ACTION_FAILED", "The OAuth retry action requires review.", status=503)
    action, claimed = claim_oauth_action(action)
    if not claimed:
        action = wait_for_oauth_action(action)
        if action.status == MarketplaceOAuthAction.Status.SUCCEEDED:
            return success_response(action.response_data, status=action.response_status)
        return error_response("OAUTH_ACTION_IN_PROGRESS", "The OAuth action is already being processed.", status=409)
    payload = {
        "integration_config_id": authorization.integration_config_id,
        "store_id": authorization.store_id,
        "platform": authorization.platform,
        "region": authorization.region,
        "redirect_target_code": "integrations",
    }
    try:
        attempt, authorization_url, created = initiate_oauth(
            request=request,
            payload=payload,
            actor=request.user,
            permission_code="integrations.store.retry",
        )
        data = {**MarketplaceOAuthAttemptSerializer(attempt).data, "attempt_id": attempt.pk, "api_status": "mock"}
        if authorization_url:
            data["authorization_url"] = authorization_url
        complete_oauth_action(action, {key: value for key, value in data.items() if key != "authorization_url"}, response_status=201 if created else 200, attempt=attempt)
        return success_response(data, status=201 if created else 200)
    except OAuthAdapterError as exc:
        fail_oauth_action(action, exc.error_code, reconcile=True)
        return error_response(exc.error_code, "Synthetic OAuth retry failed.", status=exc.http_status)
    except Exception:
        fail_oauth_action(action, "OAUTH_RETRY_FAILED", reconcile=True)
        return error_response("OAUTH_RETRY_FAILED", "OAuth retry requires reconciliation.", status=503)


@api_view(["POST"])
@permission_classes([IsIntegrationManager])
def disable_integration_config(request, pk):
    config = _get_config_for_user(request, pk, "integrations.manage")
    config.status = PlatformIntegrationConfig.Status.DISABLED
    config.save(update_fields=["status", "updated_at"])
    _write_audit_log(config, request.user, "disable", detail={"status": config.status})
    return success_response(PlatformIntegrationConfigSerializer(config).data)


@api_view(["POST"])
@permission_classes([IsIntegrationManager])
def verify_integration_config(request, pk):
    config = _get_config_for_user(request, pk, "integrations.manage")
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
    if not integration_values_allowed(
        request.user,
        "integrations.manage",
        platform=integration_config.platform,
        config_id=integration_config.id,
        resource_type=serializer.validated_data["resource_type"],
    ):
        raise DataScopeDenied(
            "Sync job is outside the authorized data scope.",
            error_code=ErrorCode.DATA_SCOPE_FORBIDDEN,
        )
    job = serializer.save(tenant=request.user.tenant)
    return success_response(SyncJobSerializer(job, context={"request": request}).data, status=201)


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
