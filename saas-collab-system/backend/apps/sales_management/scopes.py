from django.db.models import Q

from apps.permissions.models import DataScope
from apps.permissions.services import get_permission_data_scopes
from apps.masterdata.models import StoreMaster


SAFE_SCOPE_KEYS = ("store_ids", "platforms", "regions")
SCOPE_FIELD_MAP = {"store_ids": "store_id", "platforms": "platform__platform_type", "regions": "region"}
FILTER_SCOPE_KEYS = {
    "store_ids": ("store_ids", "store_id"),
    "platforms": ("platforms", "platform"),
    "regions": ("regions", "region"),
}


def safe_scope_snapshot(user, permission_code):
    return [
        {
            "scope_type": scope["scope_type"],
            "config": {key: scope.get("config", {}).get(key, []) for key in SAFE_SCOPE_KEYS if scope.get("config", {}).get(key)},
        }
        for scope in get_permission_data_scopes(user, permission_code)
    ]


def filter_sales_queryset(user, permission_code, queryset, scope_field_map=None):
    scopes = get_permission_data_scopes(user, permission_code)
    if getattr(user, "is_superuser", False) or any(scope["scope_type"] == DataScope.ScopeType.ALL for scope in scopes):
        return queryset
    combined = Q(pk__in=[])
    has_custom_scope = False
    for scope in scopes:
        if scope["scope_type"] != DataScope.ScopeType.CUSTOM:
            continue
        branch = Q()
        constrained = False
        config = scope.get("config") or {}
        for scope_key, model_field in (scope_field_map or SCOPE_FIELD_MAP).items():
            values = config.get(scope_key) or []
            if values:
                branch &= Q(**{f"{model_field}__in": [str(value) for value in values]})
                constrained = True
        if constrained:
            combined |= branch
            has_custom_scope = True
    return queryset.filter(combined) if has_custom_scope else queryset.none()


def _custom_scope_configs(user, permission_code):
    scopes = get_permission_data_scopes(user, permission_code)
    if getattr(user, "is_superuser", False) or any(
        scope["scope_type"] == DataScope.ScopeType.ALL for scope in scopes
    ):
        return None
    return [scope.get("config") or {} for scope in scopes if scope["scope_type"] == DataScope.ScopeType.CUSTOM]


def _stores_for_config(user, config):
    stores = StoreMaster.objects.filter(tenant=user.tenant)
    store_values = [str(value) for value in config.get("store_ids") or []]
    if store_values:
        store_ids = [int(value) for value in store_values if value.isdigit()]
        stores = stores.filter(Q(pk__in=store_ids) | Q(code__in=store_values))
    regions = [str(value) for value in config.get("regions") or []]
    if regions:
        stores = stores.filter(country_code__in=regions)
    return stores


def filter_inventory_queryset(user, permission_code, queryset):
    configs = _custom_scope_configs(user, permission_code)
    if configs is None:
        return queryset
    allowed = Q(pk__in=[])
    for config in configs:
        branch = Q()
        constrained = False
        platforms = [str(value) for value in config.get("platforms") or []]
        if platforms:
            branch &= Q(source_run__sync_job__integration_config__platform__in=platforms)
            constrained = True
        if config.get("store_ids") or config.get("regions"):
            sites = set(_stores_for_config(user, config).values_list("country_code", flat=True))
            if config.get("regions") and not config.get("store_ids"):
                sites.update(str(value) for value in config["regions"])
            branch &= Q(site_code__in=sites)
            constrained = True
        if constrained:
            allowed |= branch
    return queryset.filter(allowed).distinct()


def filter_sync_job_queryset(user, permission_code, queryset):
    configs = _custom_scope_configs(user, permission_code)
    if configs is None:
        return queryset
    allowed = Q(pk__in=[])
    for config in configs:
        branch = Q()
        constrained = False
        platforms = [str(value) for value in config.get("platforms") or []]
        if platforms:
            branch &= Q(integration_config__platform__in=platforms)
            constrained = True
        if config.get("store_ids") or config.get("regions"):
            store_codes = _stores_for_config(user, config).values_list("code", flat=True)
            branch &= Q(integration_config__account_alias__in=store_codes)
            constrained = True
        if constrained:
            allowed |= branch
    return queryset.filter(allowed).distinct()


def filter_quality_queryset(user, permission_code, queryset):
    configs = _custom_scope_configs(user, permission_code)
    if configs is None:
        return queryset
    allowed = Q(pk__in=[])
    for config in configs:
        branch = Q()
        constrained = False
        platforms = [str(value) for value in config.get("platforms") or []]
        if platforms:
            branch &= Q(sync_log__task__platform__in=platforms)
            constrained = True
        if config.get("store_ids") or config.get("regions"):
            stores = _stores_for_config(user, config)
            store_ids = [str(value) for value in stores.values_list("id", flat=True)]
            store_codes = list(stores.values_list("code", flat=True))
            branch &= (
                Q(sync_log__task__config__store_id__in=store_ids)
                | Q(sync_log__task__config__store_code__in=store_codes)
            )
            constrained = True
        if constrained:
            allowed |= branch
    return queryset.filter(allowed).distinct()


def scope_allows_filters(user, permission_code, filters):
    scopes = get_permission_data_scopes(user, permission_code)
    if getattr(user, "is_superuser", False) or any(scope["scope_type"] == DataScope.ScopeType.ALL for scope in scopes):
        return True
    requested = {}
    for scope_key, filter_keys in FILTER_SCOPE_KEYS.items():
        values = []
        for filter_key in filter_keys:
            value = filters.get(filter_key)
            if isinstance(value, list):
                values.extend(value)
            elif value not in (None, ""):
                values.append(value)
        requested[scope_key] = {str(value) for value in values}
    for scope in scopes:
        if scope["scope_type"] != DataScope.ScopeType.CUSTOM:
            continue
        config = scope.get("config") or {}
        if all(not requested[key] or requested[key] <= {str(value) for value in config.get(key, [])} for key in SAFE_SCOPE_KEYS):
            return True
    return False


def scope_snapshot_is_visible(user, permission_code, snapshot):
    if not _is_safe_scope_snapshot(snapshot):
        return False
    current_scopes = get_permission_data_scopes(user, permission_code)
    if getattr(user, "is_superuser", False) or any(
        scope["scope_type"] == DataScope.ScopeType.ALL for scope in current_scopes
    ):
        return True
    current_custom = [scope.get("config") or {} for scope in current_scopes if scope["scope_type"] == DataScope.ScopeType.CUSTOM]
    for historical_scope in snapshot:
        if not isinstance(historical_scope, dict) or historical_scope.get("scope_type") != DataScope.ScopeType.CUSTOM:
            return False
        historical_config = historical_scope.get("config") or {}
        if not any(_scope_branch_covers(current, historical_config) for current in current_custom):
            return False
    return True


def _is_safe_scope_snapshot(snapshot):
    if not isinstance(snapshot, list) or not snapshot:
        return False
    for scope in snapshot:
        if not isinstance(scope, dict) or set(scope) - {"scope_type", "config"}:
            return False
        if scope.get("scope_type") not in {DataScope.ScopeType.ALL, DataScope.ScopeType.CUSTOM}:
            return False
        config = scope.get("config") or {}
        if not isinstance(config, dict) or set(config) - set(SAFE_SCOPE_KEYS):
            return False
        if any(
            not isinstance(values, list) or any(not isinstance(value, str) for value in values)
            for values in config.values()
        ):
            return False
    return True


def _scope_branch_covers(current, historical):
    current_is_constrained = False
    for key in SAFE_SCOPE_KEYS:
        current_values = {str(value) for value in current.get(key, [])}
        if not current_values:
            continue
        current_is_constrained = True
        historical_values = {str(value) for value in historical.get(key, [])}
        if not historical_values or not historical_values <= current_values:
            return False
    return current_is_constrained
