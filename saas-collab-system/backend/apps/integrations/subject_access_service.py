from django.db import connection
from django.shortcuts import get_object_or_404

from apps.masterdata.models import StoreMaster, WarehouseMaster
from apps.permissions.ui_p2_scopes import filter_master_data
from apps.permissions.ui_p6_scopes import filter_integration_configs, filter_store_authorizations

from .models import MarketplaceStoreAuthorization, PlatformIntegrationConfig


VISIBLE_CONFIG_STATUSES = {"configured", "verified", "active"}
ACTIVE_AUTHORIZATION_STATUSES = {"authorized", "active"}


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
    columns = _table_columns("integrations_syncjob")
    if subject_field not in columns or "last_run_at" not in columns or not authorization_ids:
        return {}
    placeholders = ",".join(["%s"] * len(authorization_ids))
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT {subject_field},MAX(last_run_at) FROM integrations_syncjob "
            f"WHERE {subject_field} IN ({placeholders}) GROUP BY {subject_field}",
            list(authorization_ids),
        )
        return dict(cursor.fetchall())


def _config_payload(config, api_type):
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


def _store_access(user, subject_id):
    subject = get_object_or_404(
        filter_master_data(
            user,
            StoreMaster.objects.filter(tenant=user.tenant).select_related("platform"),
            "masterdata.view",
            "stores",
        ),
        pk=subject_id,
    )
    platform = str(subject.platform.platform_type or subject.platform.code).lower()
    configs = _visible_configs(user, platform=platform, country_code=subject.country_code)
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
        })
    return {
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
        "token_policy": "tiktok-split-policy" if platform == "tiktok" else "oauth-auto-refresh" if platform == "lazada" else "auto-refresh" if platform == "shopee" else "platform-default",
    }


def _warehouse_bindings(user, subject, config_map):
    table = "integrations_warehouseauthorization"
    columns = _table_columns(table)
    required = {"id", "tenant_id", "warehouse_id", "integration_config_id", "status"}
    if not required.issubset(columns) or not config_map:
        return []
    selected = [
        column for column in (
            "id", "integration_config_id", "provider", "status", "authorized_at",
            "last_verified_at", "last_error_code",
        ) if column in columns
    ]
    placeholders = ",".join(["%s"] * len(config_map))
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT {','.join(selected)} FROM {table} WHERE tenant_id=%s AND warehouse_id=%s "
            f"AND integration_config_id IN ({placeholders}) ORDER BY updated_at DESC",
            [user.tenant_id, subject.id, *config_map],
        )
        rows = [dict(zip(selected, row)) for row in cursor.fetchall()]
    last_runs = _last_run_map("warehouse_authorization_id", [row["id"] for row in rows])
    return [
        {
            **row,
            "api_type": config_map[row["integration_config_id"]][1],
            "account_alias": config_map[row["integration_config_id"]][0].account_alias,
            "last_run_at": last_runs.get(row["id"]),
        }
        for row in rows
    ]


def _warehouse_access(user, subject_id):
    subject = get_object_or_404(
        filter_master_data(
            user,
            WarehouseMaster.objects.filter(tenant=user.tenant),
            "masterdata.view",
            "warehouses",
        ),
        pk=subject_id,
    )
    configs = _visible_configs(user, platform="jifeng_wms", country_code=subject.country_code)
    config_map = {config.id: (config, api_type) for config, api_type in configs}
    return {
        "subject_type": "warehouse",
        "subject": {
            "id": subject.id,
            "code": subject.code,
            "name": subject.name,
            "country_code": subject.country_code,
            "platform": "jifeng_wms",
            "platform_name": "极风 WMS",
        },
        "api_types": ["inventory"],
        "configs": [_config_payload(config, api_type) for config, api_type in configs],
        "bindings": _warehouse_bindings(user, subject, config_map),
        "token_policy": "auto-refresh",
    }


def subject_api_access(user, subject_type, subject_id):
    if subject_type == "store":
        return _store_access(user, subject_id)
    if subject_type == "warehouse":
        return _warehouse_access(user, subject_id)
    raise ValueError("业务主体类型无效")
