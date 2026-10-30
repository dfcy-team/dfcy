from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection
from django.db.models import Max
from django.shortcuts import get_object_or_404

from apps.common.error_codes import ErrorCode
from apps.common.exceptions import DataScopeDenied
from apps.masterdata.models import (
    StoreMaster,
    WarehouseMaster,
    WAREHOUSE_SERVICE_PLATFORM_TYPES,
    WAREHOUSE_TYPE_TO_PLATFORM_TYPE,
)
from apps.permissions.ui_p6_scopes import (
    filter_integration_configs,
    filter_store_authorizations,
    integration_values_allowed,
)
from apps.permissions.services import check_user_permission, get_permission_data_scopes

from .automatic_refresh import credential_refresh_state, credential_scheduler_health
from .live_providers import integration_config_oauth_blockers
from .models import MarketplaceStoreAuthorization, PlatformIntegrationConfig, SyncJob, TikTokAdsAdvertiserMapping, WarehouseAuthorization
from .platform_capabilities import get_platform_capability
from .platform_schema_service import integration_platform_key
from .production_settings import get_runtime_platform_config


VISIBLE_CONFIG_STATUSES = {"configured", "verified", "active"}
ACTIVE_AUTHORIZATION_STATUSES = {"authorized", "active"}
UNKNOWN_REGION_SENTINEL = "__UNKNOWN__"


def _token_policy(platform):
    if platform == "tiktok":
        return "tiktok-per-binding-policy"
    if platform not in {"lazada", "shopee", "jifeng_wms"}:
        return "platform-default"
    if not get_runtime_platform_config(platform).get("auto_refresh_enabled", False):
        return "manual-refresh"
    return "oauth-auto-refresh" if platform == "lazada" else "auto-refresh"


def _subject_regions(country_code):
    """Return one concrete region for subject-scoped permission checks.

    An empty integration-config region list means that the config is global,
    but it must not turn a concrete warehouse into a global permission
    candidate.  A missing warehouse country is also denied when a role uses a
    regional scope instead of being treated as an unconstrained candidate.
    """
    value = str(country_code or "").strip().upper()
    return [value] if value else [UNKNOWN_REGION_SENTINEL]


def _table_columns(table_name):
    with connection.cursor() as cursor:
        if table_name not in connection.introspection.table_names(cursor):
            return set()
        return {column.name for column in connection.introspection.get_table_description(cursor, table_name)}


def _raw_map(table_name, columns, ids):
    ids = list(ids)
    available = _table_columns(table_name)
    selected = [column for column in columns if column in available]
    if not ids or "id" not in selected:
        return {}
    placeholders = ",".join(["%s"] * len(ids))
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT {','.join(selected)} FROM {table_name} WHERE id IN ({placeholders})",
            ids,
        )
        return {row[0]: dict(zip(selected, row)) for row in cursor.fetchall()}


def _api_type(config, raw_config):
    value = str(raw_config.get("api_type") or (config.platform_config or {}).get("api_type") or "").strip()
    if value:
        return value
    return "inventory" if config.platform == "jifeng_wms" else "marketplace"


def _last_run_map(subject_field, authorization_ids):
    if subject_field not in {"store_authorization_id", "warehouse_authorization_id"} or not authorization_ids:
        return {}
    rows = (
        SyncJob.objects.filter(**{f"{subject_field}__in": authorization_ids})
        .values(subject_field)
        .annotate(last_run=Max("last_run_at"))
    )
    return {row[subject_field]: row["last_run"] for row in rows}


def _tiktok_ads_mappings(user, subject, config_map):
    if str(subject.platform.platform_type or subject.platform.code).lower() != "tiktok":
        return None

    advertising_configs = {
        config_id: config
        for config_id, (config, api_type) in config_map.items()
        if config.tenant_id == user.tenant_id
        and config.platform == "tiktok"
        and api_type == "advertising"
    }
    if not advertising_configs:
        return []

    rows = TikTokAdsAdvertiserMapping.objects.filter(
        tenant_id=user.tenant_id,
        store_id=subject.id,
        integration_config_id__in=advertising_configs,
        store__tenant_id=user.tenant_id,
        integration_config__tenant_id=user.tenant_id,
    ).select_related("store", "store__platform", "integration_config").order_by("id")

    result = []
    for mapping in rows:
        config = advertising_configs.get(mapping.integration_config_id)
        if (
            config is None
            or mapping.tenant_id != user.tenant_id
            or mapping.store_id != subject.id
            or mapping.store.tenant_id != user.tenant_id
            or mapping.store.platform_id != subject.platform_id
            or mapping.integration_config.tenant_id != user.tenant_id
            or mapping.integration_config.platform != "tiktok"
        ):
            # Fail closed if persisted mapping relationships no longer match
            # the concrete tenant/store/config intersection used above.
            raise DataScopeDenied(
                "TikTok Ads 映射与当前租户、店铺或广告配置不一致。",
                error_code=ErrorCode.DATA_SCOPE_FORBIDDEN,
            )
        from .models import AdsOAuthSession
        verified = any(
            candidate.get("advertiser_id") == mapping.advertiser_id
            and candidate.get("verify_state") == "verified" and candidate.get("verified_at")
            and candidate.get("currency") == mapping.currency and candidate.get("timezone") == mapping.timezone
            for session in AdsOAuthSession.objects.filter(tenant_id=user.tenant_id, store_id=subject.id,
                integration_config_id=config.pk, token_id=mapping.token_id, status="bound")
            if any(item.get("mapping_id") == mapping.pk and item.get("advertiser_id") == mapping.advertiser_id
                for item in session.binding_results)
            for candidate in session.candidates
        )
        result.append({
            "mapping_id": mapping.id,
            "binding_kind": "tiktok_ads_mapping",
            "advertiser_id": mapping.advertiser_id,
            "store_id": mapping.store_id,
            "store_code": mapping.store.code,
            "store_name": mapping.store.name,
            "integration_config_id": mapping.integration_config_id,
            "account_alias": config.account_alias,
            "currency": mapping.currency,
            "timezone": mapping.timezone,
            "created_at": mapping.created_at,
            "updated_at": mapping.updated_at,
            "sync_enabled": bool(
                mapping.enabled
                and config.network_enabled
                and config.sync_read_enabled
                and not config.sync_write_enabled
            ),
            "mapping_enabled": bool(mapping.enabled),
            "network_enabled": bool(config.network_enabled),
            "read_enabled": bool(config.sync_read_enabled),
            "credential_configured": bool(mapping.token_id),
            "state": "verified" if verified else "mapped",
        })
    return result


def _marketplace_renewal_payload(record):
    state = credential_refresh_state(record)
    state = state if isinstance(state, dict) else {}
    payload = {"renewal": state, "renewal_mode": "expiry-driven" if state.get("enabled") else "manual"}
    if state.get("enabled") is True:
        payload["renewal_owner"] = "saas"
    elif record.platform == "tiktok":
        payload["renewal_owner"] = "external"
    return payload


def _config_payload(config, api_type):
    check_oauth = config.platform == "shopee" or (
        config.platform == "tiktok" and api_type == "marketplace" and config.environment in {"pilot", "production"})
    oauth_blockers = integration_config_oauth_blockers(config.platform, config) if check_oauth else []
    from .capability import live_network_mode_enabled
    if config.platform == "tiktok" and live_network_mode_enabled():
        from rest_framework.exceptions import ValidationError
        from .tiktok_direct_callback import configured_callback as shop_callback
        from .tiktok_ads_direct import configured_callback as ads_callback
        try:
            direct = (ads_callback if api_type == "advertising" else shop_callback)()
            if not direct:
                oauth_blockers.append("direct_callback_missing")
            elif config.callback_url != direct:
                oauth_blockers.append("direct_callback_mismatch")
        except ValidationError:
            oauth_blockers.append("direct_callback_invalid")
    return {
        "id": config.id,
        "platform": config.platform,
        "api_type": api_type,
        "account_alias": config.account_alias,
        "environment": config.environment,
        "status": config.status,
        "regions": config.regions or [],
        "callback_url": config.callback_url,
        "scopes": config.scopes or [],
        "oauth_ready": not oauth_blockers,
        "ads_oauth_ready": bool(config.platform == "tiktok" and api_type == "advertising"
            and not oauth_blockers
            and config.status in {"verified", "active"} and config.environment in {"pilot", "production"}
            and config.network_enabled and config.sync_read_enabled and not config.sync_write_enabled
            and config.credential_id and config.credential_status == "configured"
            and config.callback_url and config.platform_config.get("app_id")),
        "oauth_blockers": oauth_blockers,
    }


def _visible_configs(user, *, platform, country_code):
    queryset = filter_integration_configs(
        user,
        PlatformIntegrationConfig.objects.filter(tenant=user.tenant, platform=platform),
        "integrations.view",
    )
    configs = [config for config in queryset if config.status in VISIBLE_CONFIG_STATUSES]
    raw = _raw_map("integrations_platformintegrationconfig", ["id", "api_type"], [item.id for item in configs])
    country_code = str(country_code or "").upper()
    return [
        (config, _api_type(config, raw.get(config.id, {})))
        for config in configs
        if not config.regions or country_code in {str(region).upper() for region in config.regions}
    ]


def _store_visible_configs(user, *, platform, country_code, store_id):
    """Return marketplace configs visible through both integration scopes.

    The subject endpoint is mounted behind the generic integrations viewer,
    but its response includes store authorization metadata.  Keep the two
    permission domains separate and require the same concrete candidate to be
    allowed by both before exposing a config to the page.
    """
    queryset = PlatformIntegrationConfig.objects.filter(
        tenant=user.tenant,
        platform=platform,
    )
    configs = [config for config in queryset if config.status in VISIBLE_CONFIG_STATUSES]
    raw = _raw_map("integrations_platformintegrationconfig", ["id", "api_type"], [item.id for item in configs])
    country_code = str(country_code or "").upper()
    result = []
    for config in configs:
        config_regions = config.regions or []
        if config_regions and country_code not in {str(region).upper() for region in config_regions}:
            continue
        candidate = {
            "platform": config.platform,
            "environment": config.environment,
            "regions": config_regions or [country_code],
            "config_id": config.id,
            "store_id": store_id,
        }
        if not integration_values_allowed(user, "integrations.view", **candidate):
            continue
        if not integration_values_allowed(user, "integrations.store.view", **candidate):
            continue
        result.append((config, _api_type(config, raw.get(config.id, {}))))
    return result


def _warehouse_visible_configs(user, *, provider, country_code, warehouse_id):
    """Return configs allowed by both generic and warehouse API scopes.

    The generic ``integrations.view`` permission controls the page itself,
    while ``integrations.warehouse.view`` controls the inventory resource.  A
    config is only returned when the full candidate tuple is in both scopes;
    checking only the provider or warehouse would allow a restricted config
    to appear in the subject dialog.
    """
    queryset = PlatformIntegrationConfig.objects.filter(
        tenant=user.tenant,
        platform=provider,
    )
    configs = [config for config in queryset if config.status in VISIBLE_CONFIG_STATUSES]
    raw = _raw_map("integrations_platformintegrationconfig", ["id", "api_type"], [item.id for item in configs])
    country_code = str(country_code or "").upper()
    result = []
    for config in configs:
        config_regions = config.regions or []
        if config_regions and country_code not in {str(region).upper() for region in config_regions}:
            continue
        api_type = _api_type(config, raw.get(config.id, {}))
        generic_candidate = {
            "platform": config.platform,
            "environment": config.environment,
            # Global configs inherit the concrete warehouse region for
            # permission evaluation.  Passing [] here would make
            # _regions_fit_scope treat the config as globally visible.
            "regions": config_regions or _subject_regions(country_code),
            "config_id": config.id,
            "resource_type": SyncJob.ResourceType.INVENTORY_SNAPSHOT,
            "warehouse_id": warehouse_id,
        }
        if not integration_values_allowed(user, "integrations.view", **generic_candidate):
            continue
        warehouse_candidate = dict(generic_candidate)
        # A global config (no regions) still has a concrete subject region for
        # the warehouse permission.  This prevents a MY-scoped role from
        # seeing a global config on an SG warehouse.
        warehouse_candidate["regions"] = config_regions or _subject_regions(country_code)
        if not integration_values_allowed(user, "integrations.warehouse.view", **warehouse_candidate):
            continue
        result.append((config, api_type))
    return result


def _store_access(user, subject_id):
    if not check_user_permission(user, "integrations.store.view"):
        raise DataScopeDenied(
            "当前角色没有查看店铺 API 授权的权限。",
            error_code=ErrorCode.PERMISSION_DENIED,
        )
    if not get_permission_data_scopes(user, "integrations.store.view"):
        raise DataScopeDenied(
            "店铺 API 授权查看权限尚未声明数据范围。",
            error_code=ErrorCode.DATA_SCOPE_MISSING,
        )
    subject = get_object_or_404(
        StoreMaster.objects.filter(tenant=user.tenant).select_related("platform"),
        pk=subject_id,
    )
    platform = str(subject.platform.platform_type or subject.platform.code).lower()
    configs = _store_visible_configs(
        user,
        platform=platform,
        country_code=subject.country_code,
        store_id=subject.id,
    )
    config_map = {config.id: (config, api_type) for config, api_type in configs}
    authorizations = list(
        filter_store_authorizations(
            user,
            MarketplaceStoreAuthorization.objects.filter(
                tenant=user.tenant,
                store=subject,
                integration_config_id__in=config_map,
            ).select_related("integration_config"),
            "integrations.view",
        ).order_by("-updated_at")
    )
    last_runs = _last_run_map("store_authorization_id", [item.id for item in authorizations])
    bindings = []
    for item in authorizations:
        config, api_type = config_map[item.integration_config_id]
        bindings.append({
            "id": item.id,
            "api_type": api_type,
            "status": item.status,
            "integration_config_id": config.id,
            "account_alias": config.account_alias,
            "platform_store_id": item.platform_store_id,
            "authorized_at": item.authorized_at,
            "last_verified_at": item.refreshed_at,
            "last_run_at": last_runs.get(item.id),
            "last_error_code": item.last_error_code,
            **_marketplace_renewal_payload(item),
        })
    payload = {
        "subject_type": "store",
        "subject": {
            "id": subject.id,
            "code": subject.code,
            "name": subject.name,
            "country_code": subject.country_code,
            "platform": platform,
            "platform_name": subject.platform.name,
        },
        "api_types": ["marketplace"] if platform == "lazada" else ["marketplace", "advertising"],
        "configs": [_config_payload(config, api_type) for config, api_type in configs],
        "bindings": bindings,
        "token_policy": _token_policy(platform),
    }
    if platform == "tiktok":
        payload["renewal_scheduler"] = credential_scheduler_health()
        ads_mappings = _tiktok_ads_mappings(user, subject, config_map)
        if ads_mappings is not None:
            payload["ads_mappings"] = ads_mappings
    return payload


def _warehouse_bindings(user, subject, config_map):
    if not config_map:
        return []
    rows = list(
        WarehouseAuthorization.objects.filter(
            tenant_id=user.tenant_id,
            warehouse=subject,
            integration_config_id__in=config_map,
        ).order_by("-updated_at")
    )
    sync_jobs = {
        (job.warehouse_authorization_id, job.integration_config_id): job
        for job in SyncJob.objects.filter(
            tenant_id=user.tenant_id,
            warehouse_authorization_id__in=[row.id for row in rows],
            integration_config_id__in=list(config_map),
            resource_type=SyncJob.ResourceType.INVENTORY_SNAPSHOT,
        ).order_by("id")
    }
    return [
        {
            "id": row.id,
            "integration_config_id": row.integration_config_id,
            "provider": row.provider,
            # The provider-issued warehouse identity is binding-scoped.  It
            # must be returned by the subject drawer so a reload/rebind keeps
            # the value the operator entered instead of falling back to the
            # local archive code or a shared config credential.
            "external_warehouse_code": row.external_warehouse_code,
            "external_warehouse_region": row.external_warehouse_region,
            "email": row.email,
            "token_configured": bool(row.bootstrap_credential_id),
            "bootstrap_consumed_at": row.bootstrap_consumed_at,
            "oauth_token_available": bool(row.token_id and row.oauth_user_id and row.oauth_expires_at),
            "validation_status": row.validation_status,
            "status": row.status,
            "authorized_at": row.authorized_at,
            "last_verified_at": row.last_verified_at,
            "last_error_code": row.last_error_code,
            "api_type": config_map[row.integration_config_id][1],
            "account_alias": config_map[row.integration_config_id][0].account_alias,
            "has_sync_job": (row.id, row.integration_config_id) in sync_jobs,
            "sync_job_id": sync_jobs[(row.id, row.integration_config_id)].id
            if (row.id, row.integration_config_id) in sync_jobs
            else None,
            "last_run_at": sync_jobs[(row.id, row.integration_config_id)].last_run_at
            if (row.id, row.integration_config_id) in sync_jobs
            else None,
        }
        for row in rows
    ]


def _warehouse_provider(subject):
    service_platform = subject.service_platform
    if service_platform is None:
        raise ValueError("仓库尚未绑定仓储服务平台，无法开启库存 API 接入。")
    if service_platform.status != "active":
        raise ValueError("仓库绑定的仓储服务平台已停用，请先启用该平台。")
    if service_platform.platform_type not in WAREHOUSE_SERVICE_PLATFORM_TYPES:
        raise ValueError("仓库绑定的平台不是仓储服务平台类型，已阻断 API 接入。")
    if service_platform.platform_type != WAREHOUSE_TYPE_TO_PLATFORM_TYPE.get(subject.warehouse_type):
        raise ValueError("仓库类型与仓储服务平台类型不一致，已阻断 API 接入。")
    provider = integration_platform_key(
        platform_type=service_platform.platform_type,
        code=service_platform.code,
        name=service_platform.name,
    )
    if not provider:
        raise ValueError("仓储服务平台尚未匹配受支持的库存 API 服务商，请先维护平台档案。")
    try:
        capability = get_platform_capability(provider)
    except DjangoValidationError as exc:
        raise ValueError("仓储服务平台的 API 能力未注册，已阻断库存 API 接入。") from exc
    if "inventory" not in capability.api_types:
        raise ValueError("仓储服务平台未提供库存 API 能力，已阻断接入。")
    return provider


def _warehouse_access(user, subject_id):
    # The generic integrations viewer protects the page, but the warehouse
    # subject API exposes inventory authorization metadata.  Require the
    # concrete warehouse-view action even when the tenant has no managed
    # config yet; otherwise an integrations.view-only role could enumerate a
    # warehouse API subject shell.
    if not check_user_permission(user, "integrations.warehouse.view"):
        raise DataScopeDenied(
            "当前角色没有查看仓库 API 授权的权限。",
            error_code=ErrorCode.PERMISSION_DENIED,
        )
    if not get_permission_data_scopes(user, "integrations.warehouse.view"):
        raise DataScopeDenied(
            "仓库 API 授权查看权限尚未声明数据范围。",
            error_code=ErrorCode.DATA_SCOPE_MISSING,
        )
    subject = get_object_or_404(
        WarehouseMaster.objects.filter(tenant=user.tenant).select_related("service_platform"),
        pk=subject_id,
    )
    provider = _warehouse_provider(subject)
    configs = _warehouse_visible_configs(
        user,
        provider=provider,
        country_code=subject.country_code,
        warehouse_id=subject.id,
    )
    if not configs:
        # An empty result is valid when the tenant has no visible config yet,
        # but the subject shell still represents a concrete inventory API
        # resource.  Always check that resource against both data scopes;
        # otherwise a MY/warehouse-A role could enumerate an SG/warehouse-B
        # shell whenever all configs are disabled or hidden.
        base_candidate = {
            "platform": provider,
            "regions": _subject_regions(subject.country_code),
            "resource_type": SyncJob.ResourceType.INVENTORY_SNAPSHOT,
            "warehouse_id": subject.id,
        }
        if not integration_values_allowed(user, "integrations.view", **base_candidate) or not integration_values_allowed(
            user,
            "integrations.warehouse.view",
            **base_candidate,
        ):
            raise DataScopeDenied(
                "仓库 API 授权超出当前角色的数据范围。",
                error_code=ErrorCode.DATA_SCOPE_FORBIDDEN,
            )
    config_map = {config.id: (config, api_type) for config, api_type in configs}
    return {
        "subject_type": "warehouse",
        "subject": {
            "id": subject.id,
            "code": subject.code,
            "name": subject.name,
            "country_code": subject.country_code,
            "platform": provider,
            "platform_name": subject.service_platform.name,
            "service_platform_id": subject.service_platform.id,
            "service_platform_type": subject.service_platform.platform_type,
        },
        "api_types": ["inventory"],
        "configs": [_config_payload(config, api_type) for config, api_type in configs],
        "bindings": _warehouse_bindings(user, subject, config_map),
        "token_policy": _token_policy(provider),
    }


def subject_api_access(user, subject_type, subject_id):
    if subject_type == "store":
        return _store_access(user, subject_id)
    if subject_type == "warehouse":
        return _warehouse_access(user, subject_id)
    raise ValueError("业务主体类型无效")
