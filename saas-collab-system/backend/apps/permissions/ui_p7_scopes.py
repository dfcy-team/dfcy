import re

from django.db.models import Q

from apps.common.error_codes import ErrorCode
from apps.common.exceptions import DataScopeDenied

from .models import DataScope
from .services import get_permission_data_scopes


SCOPE_KEYS = {
    "governance.api.view": {"modules", "api_contract_ids", "statuses"},
    "governance.api.check": {"modules", "api_contract_ids", "statuses"},
    "governance.assistants.view": {"assistant_ids", "data_classes"},
    "governance.assistants.evaluate": {"assistant_ids", "data_classes"},
    "pilot.readiness.view": {"environment_ids", "gate_codes"},
    "pilot.topology.view": {"environment_ids", "service_names", "network_zones"},
    "pilot.topology.verify": {"environment_ids", "service_names", "network_zones"},
    "pilot.recovery.view": {"environment_ids", "recovery_plan_ids"},
    "pilot.recovery.plan": {"environment_ids", "recovery_plan_ids"},
    "pilot.recovery.review": {"environment_ids", "recovery_plan_ids"},
    "pilot.recovery.record": {"environment_ids", "recovery_plan_ids"},
    "pilot.release.view": {"environment_ids", "release_plan_ids", "release_channels"},
    "pilot.release.plan": {"environment_ids", "release_plan_ids", "release_channels"},
    "pilot.release.review": {"environment_ids", "release_plan_ids", "release_channels"},
    "pilot.release.record": {"environment_ids", "release_plan_ids", "release_channels"},
    "pilot.release.rollback": {"environment_ids", "release_plan_ids", "release_channels"},
    "pilot.capacity.view": {"environment_ids", "service_names", "metric_codes"},
}

ENUM_VALUES = {
    "statuses": {"pending", "mock", "sandbox", "connected", "degraded", "disabled", "stale"},
    "data_classes": {"public_demo", "internal_demo", "restricted_demo"},
    "gate_codes": {"code", "ci", "security", "config", "database", "network", "backup", "recovery", "rollback", "capacity"},
    "service_names": {"nginx", "backend", "celery_worker", "celery_beat", "redis", "mysql"},
    "network_zones": {"controlled_app", "controlled_db"},
    "release_channels": {"demo", "controlled_pilot"},
    "metric_codes": {"cpu_percent", "memory_percent", "http_rps", "queue_depth", "db_connections"},
}


def _denied(message, code=ErrorCode.DATA_SCOPE_INVALID):
    raise DataScopeDenied(message, error_code=code)


def _validate_registered_values(user, key, values):
    if len(values) != len(set(values)):
        _denied(f"UI-P7 {key} scope contains duplicate values.")
    maximum = 20 if key == "environment_ids" else 100
    if len(values) > maximum:
        _denied(f"UI-P7 {key} scope exceeds the maximum of {maximum} values.")

    if key == "environment_ids":
        from apps.pilot.models import PilotEnvironment
        registered = set(PilotEnvironment.objects.filter(code__in=values, status="controlled").values_list("code", flat=True))
    elif key == "modules":
        from apps.governance.models import ApiContract
        registered = set(ApiContract.objects.filter(module__in=values).values_list("module", flat=True))
    elif key == "api_contract_ids":
        from apps.governance.models import ApiContract
        registered = set(
            ApiContract.objects.filter(Q(tenant__isnull=True) | Q(tenant=user.tenant), pk__in=values)
            .values_list("pk", flat=True)
        )
    elif key == "assistant_ids":
        from apps.governance.models import AssistantDefinition
        registered = set(
            AssistantDefinition.objects.filter(Q(tenant__isnull=True) | Q(tenant=user.tenant), pk__in=values)
            .values_list("pk", flat=True)
        )
    elif key == "recovery_plan_ids":
        from apps.pilot.models import RecoveryPlan
        registered = set(RecoveryPlan.objects.filter(tenant=user.tenant, pk__in=values).values_list("pk", flat=True))
    elif key == "release_plan_ids":
        from apps.pilot.models import ReleasePlan
        registered = set(ReleasePlan.objects.filter(tenant=user.tenant, pk__in=values).values_list("pk", flat=True))
    else:
        return
    if registered != set(values):
        _denied(f"UI-P7 {key} scope contains unregistered values.")


def permission_scope_configs(user, permission_code):
    allowed = SCOPE_KEYS.get(permission_code)
    if not allowed:
        _denied("The permission does not have a UI-P7 data-scope contract.")
    scopes = get_permission_data_scopes(user, permission_code)
    if not scopes:
        _denied("The declared permission has no data scope.", ErrorCode.DATA_SCOPE_MISSING)
    if any(scope["scope_type"] == DataScope.ScopeType.ALL for scope in scopes):
        return None
    if any(scope["scope_type"] in {DataScope.ScopeType.OWN, DataScope.ScopeType.DEPARTMENT} for scope in scopes):
        _denied("OWN and DEPARTMENT are not supported for UI-P7.", ErrorCode.DATA_SCOPE_UNSUPPORTED)
    configs = []
    for scope in scopes:
        if scope["scope_type"] != DataScope.ScopeType.CUSTOM:
            _denied("Unsupported UI-P7 data-scope type.")
        config = scope.get("config") or {}
        if not isinstance(config, dict) or not config or set(config) - allowed:
            _denied("UI-P7 data scope contains unknown or empty keys.")
        for key, values in config.items():
            if not isinstance(values, list) or not values:
                _denied("UI-P7 data-scope values must be non-empty arrays.")
            if key == "environment_ids":
                if any(not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", value) for value in values):
                    _denied("UI-P7 environment scope is invalid.")
            elif key.endswith("_ids"):
                if any(not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in values):
                    _denied("UI-P7 identifier scopes must contain positive integers.")
            elif key in ENUM_VALUES:
                if any(value not in ENUM_VALUES[key] for value in values):
                    _denied(f"UI-P7 {key} scope is invalid.")
            elif any(not isinstance(value, str) or not value.strip() for value in values):
                _denied(f"UI-P7 {key} scope is invalid.")
            _validate_registered_values(user, key, values)
        configs.append(config)
    return configs


def _matches(config, values):
    return all(key in values and values[key] in set(allowed) for key, allowed in config.items())


def values_allowed(user, permission_code, **values):
    configs = permission_scope_configs(user, permission_code)
    return configs is None or any(_matches(config, values) for config in configs)


def environment_allowed(user, permission_code, environment_code):
    """Authorize the parent environment without discarding child scope keys."""
    from apps.pilot.models import PilotEnvironment

    if not PilotEnvironment.objects.filter(code=environment_code, status="controlled").exists():
        _denied("The pilot environment is not registered as controlled.")
    configs = permission_scope_configs(user, permission_code)
    if configs is None:
        return True
    return any(
        "environment_ids" not in config or environment_code in config["environment_ids"]
        for config in configs
    )


def filter_api_contracts(user, queryset, permission_code):
    configs = permission_scope_configs(user, permission_code)
    if configs is None:
        if "environment" in {field.name for field in queryset.model._meta.fields}:
            return queryset.filter(environment__status="controlled")
        return queryset
    allowed = Q(pk__in=[])
    for config in configs:
        condition = Q()
        if "modules" in config:
            condition &= Q(module__in=config["modules"])
        if "api_contract_ids" in config:
            condition &= Q(pk__in=config["api_contract_ids"])
        if "statuses" in config:
            condition &= Q(status__in=config["statuses"])
        allowed |= condition
    return queryset.filter(allowed)


def filter_assistants(user, queryset, permission_code):
    configs = permission_scope_configs(user, permission_code)
    if configs is None:
        return queryset
    allowed = Q(pk__in=[])
    for config in configs:
        condition = Q()
        if "assistant_ids" in config:
            condition &= Q(pk__in=config["assistant_ids"])
        if "data_classes" in config:
            condition &= Q(data_class__in=config["data_classes"])
        allowed |= condition
    return queryset.filter(allowed)


def filter_environment_queryset(
    user,
    queryset,
    permission_code,
    *,
    environment_field="environment__code",
    service_field=None,
    metric_field=None,
    network_zone_field=None,
    gate_field=None,
):
    configs = permission_scope_configs(user, permission_code)
    if configs is None:
        field_names = {field.name for field in queryset.model._meta.fields}
        if "environment" in field_names:
            return queryset.filter(environment__status="controlled")
        if "recovery_plan" in field_names:
            return queryset.filter(recovery_plan__environment__status="controlled")
        if "status" in field_names and queryset.model.__name__ == "PilotEnvironment":
            return queryset.filter(status="controlled")
        return queryset
    allowed = Q(pk__in=[])
    for config in configs:
        condition = Q()
        if "environment_ids" in config:
            condition &= Q(**{f"{environment_field}__in": config["environment_ids"]})
        if service_field and "service_names" in config:
            condition &= Q(**{f"{service_field}__in": config["service_names"]})
        if metric_field and "metric_codes" in config:
            condition &= Q(**{f"{metric_field}__in": config["metric_codes"]})
        if network_zone_field and "network_zones" in config:
            condition &= Q(**{f"{network_zone_field}__in": config["network_zones"]})
        if gate_field and "gate_codes" in config:
            condition &= Q(**{f"{gate_field}__in": config["gate_codes"]})
        allowed |= condition
    return queryset.filter(allowed)


def filter_plan_queryset(user, queryset, permission_code, *, plan_key, channel_field=None):
    configs = permission_scope_configs(user, permission_code)
    if configs is None:
        return queryset.filter(environment__status="controlled")
    allowed = Q(pk__in=[])
    for config in configs:
        condition = Q()
        if "environment_ids" in config:
            condition &= Q(environment__code__in=config["environment_ids"])
        if plan_key in config:
            condition &= Q(pk__in=config[plan_key])
        if channel_field and "release_channels" in config:
            condition &= Q(**{f"{channel_field}__in": config["release_channels"]})
        allowed |= condition
    return queryset.filter(allowed)
