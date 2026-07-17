import re

from django.db.models import Q

from apps.common.error_codes import ErrorCode
from apps.common.exceptions import DataScopeDenied

from .models import DataScope
from .services import get_permission_data_scopes


def _invalid_scope(message="The declared permission has an invalid data scope."):
    raise DataScopeDenied(message, error_code=ErrorCode.DATA_SCOPE_INVALID)


def _is_positive_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _validate_positive_int_values(values, message):
    if any(not _is_positive_int(value) for value in values):
        _invalid_scope(message)


def _validate_non_empty_string_values(values, message):
    if any(not isinstance(value, str) or not value.strip() for value in values):
        _invalid_scope(message)


INTEGRATION_SCOPE_KEYS = {"platforms", "integration_config_ids", "resource_types"}


def permission_scope_configs(user, permission_code, relevant_keys, *, allowed_keys=None):
    scopes = get_permission_data_scopes(user, permission_code)
    if not scopes:
        raise DataScopeDenied("The declared permission has no data scope.", error_code=ErrorCode.DATA_SCOPE_MISSING)
    if any(scope["scope_type"] == DataScope.ScopeType.ALL for scope in scopes):
        return None
    if any(scope["scope_type"] in {DataScope.ScopeType.OWN, DataScope.ScopeType.DEPARTMENT} for scope in scopes):
        raise DataScopeDenied(
            "The declared permission uses an unsupported data scope type.",
            error_code=ErrorCode.DATA_SCOPE_UNSUPPORTED,
        )

    configs = []
    for scope in scopes:
        if scope["scope_type"] != DataScope.ScopeType.CUSTOM:
            raise DataScopeDenied("The declared permission has an invalid data scope.", error_code=ErrorCode.DATA_SCOPE_INVALID)
        config = scope.get("config") or {}
        if not isinstance(config, dict):
            _invalid_scope()
        allowed_keys = set(allowed_keys or relevant_keys)
        unknown_keys = set(config) - allowed_keys
        if unknown_keys:
            _invalid_scope("The declared permission data scope contains unsupported keys.")
        selected = {key: config[key] for key in relevant_keys if key in config}
        if not selected:
            continue
        if any(not isinstance(values, list) or not values for values in selected.values()):
            _invalid_scope()
        configs.append(selected)
    if not configs:
        raise DataScopeDenied("The declared permission has no applicable data scope.", error_code=ErrorCode.DATA_SCOPE_MISSING)
    return configs


def analytics_dimension_configs(user, permission_code):
    configs = permission_scope_configs(user, permission_code, {"analytics_dimensions"})
    if configs is None:
        return None
    result = []
    allowed_keys = {"platform", "store_id", "country", "product_id", "sku_id", "warehouse_id"}
    string_keys = {"platform", "store_id", "country"}
    integer_keys = {"product_id", "sku_id", "warehouse_id"}
    for config in configs:
        dimensions = config["analytics_dimensions"]
        if any(not isinstance(item, dict) or not item or set(item) - allowed_keys for item in dimensions):
            _invalid_scope("Analytics data scope is invalid.")
        for item in dimensions:
            if any(not isinstance(item[key], str) or not item[key].strip() for key in set(item) & string_keys):
                _invalid_scope("Analytics data scope contains an invalid string dimension.")
            if any(not _is_positive_int(item[key]) for key in set(item) & integer_keys):
                _invalid_scope("Analytics data scope contains an invalid identifier dimension.")
        result.extend(dimensions)
    return result


def filter_analytics_queryset(user, queryset, permission_code):
    configs = analytics_dimension_configs(user, permission_code)
    if configs is None:
        return queryset
    allowed = Q(pk__in=[])
    for dimensions in configs:
        condition = Q()
        for key, value in dimensions.items():
            condition &= Q(**{f"dimensions__{key}": value})
        allowed |= condition
    return queryset.filter(allowed)


def analytics_dimensions_allowed(user, permission_code, dimensions):
    configs = analytics_dimension_configs(user, permission_code)
    if configs is None:
        return True
    return any(all(dimensions.get(key) == value for key, value in scope.items()) for scope in configs)


def filter_lifecycle_queryset(user, queryset, permission_code):
    configs = permission_scope_configs(user, permission_code, {"spu_ids", "sku_ids"})
    if configs is None:
        return queryset
    for config in configs:
        for key in {"spu_ids", "sku_ids"} & set(config):
            _validate_positive_int_values(config[key], "Lifecycle data scope contains an invalid identifier.")
    allowed = Q(pk__in=[])
    for config in configs:
        condition = Q()
        if "spu_ids" in config:
            condition &= Q(spu_id__in=config["spu_ids"])
        if "sku_ids" in config:
            condition &= Q(sku_id__in=config["sku_ids"])
        allowed |= condition
    return queryset.filter(allowed).distinct()


def lifecycle_target_allowed(user, permission_code, *, spu_id=None, sku_id=None):
    configs = permission_scope_configs(user, permission_code, {"spu_ids", "sku_ids"})
    if configs is None:
        return True
    for config in configs:
        for key in {"spu_ids", "sku_ids"} & set(config):
            _validate_positive_int_values(config[key], "Lifecycle data scope contains an invalid identifier.")
        if "spu_ids" in config and spu_id not in set(config["spu_ids"]):
            continue
        if "sku_ids" in config and sku_id not in set(config["sku_ids"]):
            continue
        return True
    return False


def filter_integration_configs(user, queryset, permission_code):
    configs = permission_scope_configs(
        user,
        permission_code,
        {"platforms", "integration_config_ids"},
        allowed_keys=INTEGRATION_SCOPE_KEYS,
    )
    if configs is None:
        return queryset
    _validate_integration_configs(configs)
    allowed = Q(pk__in=[])
    for config in configs:
        condition = Q()
        if "platforms" in config:
            condition &= Q(platform__in=[str(value) for value in config["platforms"]])
        if "integration_config_ids" in config:
            condition &= Q(pk__in=config["integration_config_ids"])
        allowed |= condition
    return queryset.filter(allowed).distinct()


def integration_values_allowed(user, permission_code, *, platform=None, config_id=None, resource_type=None):
    configs = permission_scope_configs(
        user,
        permission_code,
        INTEGRATION_SCOPE_KEYS,
    )
    if configs is None:
        return True
    _validate_integration_configs(configs)
    for config in configs:
        if "platforms" in config and platform not in set(config["platforms"]):
            continue
        if "integration_config_ids" in config and config_id not in set(config["integration_config_ids"]):
            continue
        if "resource_types" in config and resource_type not in set(config["resource_types"]):
            continue
        return True
    return False


def filter_sync_jobs(user, queryset, permission_code):
    configs = permission_scope_configs(
        user,
        permission_code,
        INTEGRATION_SCOPE_KEYS,
    )
    if configs is None:
        return queryset
    _validate_integration_configs(configs)
    allowed = Q(pk__in=[])
    for config in configs:
        condition = Q()
        if "platforms" in config:
            condition &= Q(integration_config__platform__in=[str(value) for value in config["platforms"]])
        if "integration_config_ids" in config:
            condition &= Q(integration_config_id__in=config["integration_config_ids"])
        if "resource_types" in config:
            condition &= Q(resource_type__in=[str(value) for value in config["resource_types"]])
        allowed |= condition
    return queryset.filter(allowed).distinct()


def filter_sync_runs(user, queryset, permission_code):
    configs = permission_scope_configs(
        user,
        permission_code,
        INTEGRATION_SCOPE_KEYS,
    )
    if configs is None:
        return queryset
    _validate_integration_configs(configs)
    allowed = Q(pk__in=[])
    for config in configs:
        condition = Q()
        if "platforms" in config:
            condition &= Q(sync_job__integration_config__platform__in=[str(value) for value in config["platforms"]])
        if "integration_config_ids" in config:
            condition &= Q(sync_job__integration_config_id__in=config["integration_config_ids"])
        if "resource_types" in config:
            condition &= Q(sync_job__resource_type__in=[str(value) for value in config["resource_types"]])
        allowed |= condition
    return queryset.filter(allowed).distinct()


def filter_finance_queryset(user, queryset, permission_code, *, platform_field="platform", currency_field="currency"):
    configs = permission_scope_configs(user, permission_code, {"platforms", "currencies"})
    if configs is None:
        return queryset
    for config in configs:
        if "platforms" in config:
            _validate_non_empty_string_values(config["platforms"], "Finance data scope contains an invalid platform.")
        if "currencies" in config:
            _validate_non_empty_string_values(config["currencies"], "Finance data scope contains an invalid currency.")
            if any(not re.fullmatch(r"[A-Z]{3}", value) for value in config["currencies"]):
                _invalid_scope("Finance data scope currencies must use uppercase ISO 4217 codes.")
    allowed = Q(pk__in=[])
    for config in configs:
        condition = Q()
        if "platforms" in config:
            condition &= Q(**{f"{platform_field}__in": [str(value) for value in config["platforms"]]})
        if "currencies" in config:
            condition &= Q(**{f"{currency_field}__in": [str(value).upper() for value in config["currencies"]]})
        allowed |= condition
    return queryset.filter(allowed).distinct()


REPORT_TYPES = {
    "analytics_summary",
    "inventory_alerts",
    "replenishment",
    "lifecycle",
    "business_alerts",
    "finance_summary",
}


def _validate_integration_configs(configs):
    for config in configs:
        if "platforms" in config:
            _validate_non_empty_string_values(config["platforms"], "Integration data scope contains an invalid platform.")
        if "integration_config_ids" in config:
            _validate_positive_int_values(
                config["integration_config_ids"],
                "Integration data scope contains an invalid configuration identifier.",
            )
        if "resource_types" in config:
            _validate_non_empty_string_values(
                config["resource_types"],
                "Integration data scope contains an invalid resource type.",
            )


def report_types_for_permission(user, permission_code):
    configs = permission_scope_configs(user, permission_code, {"report_types"})
    if configs is None:
        return None
    report_types = set()
    for config in configs:
        _validate_non_empty_string_values(config["report_types"], "Report data scope contains an invalid report type.")
        values = set(config["report_types"])
        if not values <= REPORT_TYPES:
            raise DataScopeDenied("Report data scope is invalid.", error_code=ErrorCode.DATA_SCOPE_INVALID)
        report_types.update(values)
    return report_types


def report_type_allowed(user, permission_code, report_type):
    report_types = report_types_for_permission(user, permission_code)
    return report_types is None or report_type in report_types


def filter_report_exports(user, queryset, permission_code):
    report_types = report_types_for_permission(user, permission_code)
    if report_types is None:
        return queryset
    return queryset.filter(report_type__in=report_types)
