from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.common.error_codes import ErrorCode
from apps.common.exceptions import DataScopeDenied, get_scoped_object_or_404
from apps.common.responses import success_response
from apps.common.query import pagination_query, positive_int
from apps.common.responses import paginated_data
from apps.workflows.models import CollaborationEvent
from apps.workflows.serializers import CollaborationEventSerializer
from apps.workflows.services import receive_mock_collaboration_event
from apps.permissions.api_permissions import (
    IsIntegrationCredentialRotator,
    IsIntegrationManager,
    IsIntegrationReadOrManage,
    IsIntegrationRunner,
    IsIntegrationViewer,
    IsMarketplaceCredentialRotator,
    IsMarketplaceStoreAuthorizer,
    IsMarketplaceStoreMappingManager,
    IsMarketplaceStoreRevoker,
    IsMarketplaceStoreViewer,
)
from apps.permissions.ui_p6_scopes import (
    filter_integration_configs,
    filter_product_mappings,
    filter_store_mappings,
    filter_sync_jobs,
    filter_sync_runs,
    integration_values_allowed,
    filter_store_authorizations,
)

from .credential_service import reject_raw_credential_fields, rotate_config_references
from .marketplace_oauth_service import (
    complete_marketplace_oauth_callback,
    refresh_marketplace_authorization,
    revoke_marketplace_authorization,
    start_marketplace_oauth,
)
from .models import (
    IntegrationAuditLog,
    MarketplaceProductMapping,
    MarketplaceStoreAuthorization,
    MarketplaceStoreMapping,
    PlatformChoices,
    PlatformIntegrationConfig,
    SyncJob,
    SyncRun,
)
from .product_mapping_service import (
    confirm_product_mapping,
    create_product_mapping,
    deactivate_product_mapping,
    suggest_product_mapping,
)
from .serializers import (
    MarketplaceOAuthStartSerializer,
    MarketplaceProductMappingSerializer,
    MarketplaceStoreAuthorizationSerializer,
    MarketplaceStoreMappingSerializer,
    PlatformIntegrationConfigSerializer,
    ProductMappingCreateSerializer,
    ProductMappingUpdateSerializer,
    RotateCredentialsSerializer,
    StoreMappingCreateSerializer,
    StoreMappingUpdateSerializer,
    SyncJobSerializer,
    SyncRunSerializer,
)
from .store_mapping_service import create_store_mapping, update_store_mapping
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


def _get_store_authorization_for_user(request, pk, permission_code):
    queryset = filter_store_authorizations(
        request.user,
        MarketplaceStoreAuthorization.objects.filter(tenant=request.user.tenant),
        permission_code,
    )
    return get_scoped_object_or_404(queryset, pk=pk)


@api_view(["POST"])
@permission_classes([IsMarketplaceStoreAuthorizer, IsMarketplaceCredentialRotator])
def refresh_store_authorization(request, pk):
    reject_raw_credential_fields(request.data)
    record = _get_store_authorization_for_user(request, pk, "integrations.credential.rotate")
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
        queryset = filter_store_mappings(request.user, queryset, "integrations.store.view")
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
            "integrations.store.authorize",
        ),
        pk=data["authorization_id"],
    )
    if not integration_values_allowed(
        request.user,
        "integrations.store.authorize",
        platform=authorization.platform,
        store_id=data["store_id"],
    ):
        raise DataScopeDenied(
            "Store mapping is outside the authorized data scope.",
            error_code=ErrorCode.DATA_SCOPE_FORBIDDEN,
        )
    from apps.masterdata.models import StoreMaster

    store = get_object_or_404(StoreMaster, tenant=request.user.tenant, pk=data["store_id"])
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
    permission_code = "integrations.store.view" if request.method == "GET" else "integrations.store.authorize"
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
    if not integration_values_allowed(
        request.user,
        "integrations.store.authorize",
        platform=mapping.platform,
        store_id=mapping.store_id,
    ):
        raise DataScopeDenied(
            "Store mapping update is outside the authorized data scope.",
            error_code=ErrorCode.DATA_SCOPE_FORBIDDEN,
        )
    mapping = update_store_mapping(
        mapping,
        actor=request.user,
        status=serializer.validated_data.get("status"),
        store_timezone=serializer.validated_data.get("timezone"),
        currency=serializer.validated_data.get("currency"),
    )
    return success_response(MarketplaceStoreMappingSerializer(mapping).data)


@api_view(["GET", "POST"])
@permission_classes([IsMarketplaceStoreMappingManager])
def product_mapping_collection(request):
    if request.method == "GET":
        allowed_query = {"page", "page_size", "platform", "status", "store_mapping_id"}
        if set(request.query_params) - allowed_query:
            raise ValidationError("Unknown product mapping query parameter.")
        queryset = MarketplaceProductMapping.objects.filter(tenant=request.user.tenant).select_related("sku")
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
        queryset = filter_product_mappings(request.user, queryset, "integrations.store.view")
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
    store_mapping = get_scoped_object_or_404(
        filter_store_mappings(
            request.user,
            MarketplaceStoreMapping.objects.filter(tenant=request.user.tenant),
            "integrations.store.authorize",
        ),
        pk=data["store_mapping_id"],
    )
    if not integration_values_allowed(
        request.user,
        "integrations.store.authorize",
        platform=store_mapping.platform,
        store_id=store_mapping.store_id,
    ):
        raise DataScopeDenied(
            "Product mapping is outside the authorized data scope.",
            error_code=ErrorCode.DATA_SCOPE_FORBIDDEN,
        )
    mapping = create_product_mapping(
        tenant=request.user.tenant,
        actor=request.user,
        store_mapping=store_mapping,
        platform_product_id=data["platform_product_id"],
        platform_variant_id=data["platform_variant_id"],
        platform_sku=data["platform_sku"],
    )
    return success_response(MarketplaceProductMappingSerializer(mapping).data, status=201)


@api_view(["GET", "PATCH"])
@permission_classes([IsMarketplaceStoreMappingManager])
def product_mapping_detail(request, pk):
    permission_code = "integrations.store.view" if request.method == "GET" else "integrations.store.authorize"
    queryset = filter_product_mappings(
        request.user,
        MarketplaceProductMapping.objects.filter(tenant=request.user.tenant).select_related("sku"),
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
    if not integration_values_allowed(
        request.user,
        "integrations.store.authorize",
        platform=mapping.platform,
        store_id=mapping.store_mapping.store_id,
    ):
        raise DataScopeDenied(
            "Product mapping update is outside the authorized data scope.",
            error_code=ErrorCode.DATA_SCOPE_FORBIDDEN,
        )
    sku = None
    if data.get("sku_id"):
        from apps.products.models import ProductSKU

        sku = get_object_or_404(ProductSKU, tenant=request.user.tenant, pk=data["sku_id"])
    if data.get("status") == MarketplaceProductMapping.Status.INACTIVE:
        mapping = deactivate_product_mapping(mapping, actor=request.user)
    elif data.get("manually_confirmed"):
        mapping = confirm_product_mapping(mapping, actor=request.user, sku=sku, manually_confirmed=True)
    else:
        if sku is None or "confidence" not in data:
            raise ValidationError("Product mapping suggestions require a SKU and a confidence score.")
        mapping = suggest_product_mapping(mapping, actor=request.user, sku=sku, confidence=data["confidence"])
    return success_response(MarketplaceProductMappingSerializer(mapping).data)


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
