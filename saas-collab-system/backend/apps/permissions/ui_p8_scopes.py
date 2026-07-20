import re

from django.db.models import Q

from apps.common.error_codes import ErrorCode
from apps.common.exceptions import DataScopeDenied

from .models import DataScope
from .services import get_permission_data_scopes


SCOPE_KEYS = {
    "pilot.control.view": {"pilot_environments"},
    "pilot.security_review.view": {"pilot_environments", "security_review_ids"},
    "pilot.security_review.plan": {"pilot_environments", "security_review_ids"},
    "pilot.security_review.review": {"pilot_environments", "security_review_ids"},
    "pilot.verification.view": {"pilot_environments", "verification_run_ids"},
    "pilot.verification.plan": {"pilot_environments", "verification_run_ids"},
    "pilot.verification.review": {"pilot_environments", "verification_run_ids"},
    "pilot.verification.record": {"pilot_environments", "verification_run_ids"},
    "pilot.verification.cancel": {"pilot_environments", "verification_run_ids"},
    "pilot.performance.view": {"pilot_environments", "performance_run_ids"},
    "pilot.performance.plan": {"pilot_environments", "performance_run_ids"},
    "pilot.performance.review": {"pilot_environments", "performance_run_ids"},
    "pilot.performance.record": {"pilot_environments", "performance_run_ids"},
    "pilot.performance.cancel": {"pilot_environments", "performance_run_ids"},
    "pilot.entry.view": {"pilot_environments", "entry_decision_ids"},
    "pilot.entry.plan": {"pilot_environments", "entry_decision_ids"},
    "pilot.entry.review": {"pilot_environments", "entry_decision_ids"},
}

RESOURCE_KEYS = {
    "security_review_ids": "SecurityReview",
    "verification_run_ids": "VerificationRun",
    "performance_run_ids": "PerformanceRun",
    "entry_decision_ids": "EntryDecision",
}


def _deny(message):
    raise DataScopeDenied(message, error_code=ErrorCode.DATA_SCOPE_INVALID)


def _registered_values(user, key, values):
    if key == "pilot_environments":
        from apps.pilot.models import PilotEnvironment

        found = set(PilotEnvironment.objects.filter(code__in=values, status="controlled").values_list("code", flat=True))
    else:
        from apps.pilot import models as pilot_models

        model = getattr(pilot_models, RESOURCE_KEYS[key])
        found = set(model.objects.filter(tenant=user.tenant, pk__in=values).values_list("pk", flat=True))
    if found != set(values):
        _deny(f"UI-P8 {key} contains values outside the registered tenant boundary.")


def permission_scope_configs(user, permission_code):
    allowed = SCOPE_KEYS.get(permission_code)
    if not allowed:
        _deny("The permission has no UI-P8 data-scope contract.")
    scopes = get_permission_data_scopes(user, permission_code)
    if not scopes:
        _deny("The declared permission has no data scope.")
    if any(scope["scope_type"] == DataScope.ScopeType.ALL for scope in scopes):
        return None
    if any(scope["scope_type"] != DataScope.ScopeType.CUSTOM for scope in scopes):
        _deny("UI-P8 supports only ALL or CUSTOM data scopes.")

    configs = []
    for scope in scopes:
        config = scope.get("config") or {}
        if not isinstance(config, dict) or not config or set(config) - allowed:
            _deny("UI-P8 data scope contains unknown or empty keys.")
        for key, values in config.items():
            if not isinstance(values, list) or not values or len(values) != len(set(values)):
                _deny(f"UI-P8 {key} must be a non-empty unique array.")
            maximum = 20 if key == "pilot_environments" else 100
            if len(values) > maximum:
                _deny(f"UI-P8 {key} exceeds {maximum} values.")
            if key == "pilot_environments":
                if any(not isinstance(value, str) or not re.fullmatch(r"(?:sandbox|pilot)", value) for value in values):
                    _deny("UI-P8 pilot_environments contains an invalid value.")
            elif any(not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in values):
                _deny(f"UI-P8 {key} must contain positive integers.")
            _registered_values(user, key, values)
        configs.append(config)
    return configs


def authorize_create(user, permission_code, environment):
    configs = permission_scope_configs(user, permission_code)
    if configs is None:
        return True
    if any("pilot_environments" in config and environment in config["pilot_environments"] for config in configs):
        return True
    _deny("Creation requires an explicit authorized pilot environment.")


def filter_resource_queryset(user, queryset, permission_code, resource_key):
    configs = permission_scope_configs(user, permission_code)
    queryset = queryset.filter(tenant=user.tenant, environment__status="controlled")
    if configs is None:
        return queryset
    allowed = Q(pk__in=[])
    for config in configs:
        condition = Q()
        if "pilot_environments" in config:
            condition &= Q(environment__code__in=config["pilot_environments"])
        if resource_key in config:
            condition &= Q(pk__in=config[resource_key])
        allowed |= condition
    return queryset.filter(allowed)


def authorize_action(user, instance, permission_code, resource_key, *, source_environment=None, target_environment=None):
    configs = permission_scope_configs(user, permission_code)
    if configs is None:
        return True
    for config in configs:
        if resource_key not in config or instance.pk not in config[resource_key]:
            continue
        environment_values = set(config.get("pilot_environments", []))
        if environment_values and instance.environment.code not in environment_values:
            continue
        if source_environment is not None and source_environment not in environment_values:
            continue
        if target_environment is not None and target_environment not in environment_values:
            continue
        return True
    _deny("The action target is outside the exact permission data scope.")


def finance_values_allowed(user, finance_scope):
    from apps.permissions.services import check_user_permission
    from apps.permissions.ui_p6_scopes import permission_scope_configs as p6_scope_configs

    if not check_user_permission(user, "finance.view"):
        raise DataScopeDenied("Finance boundary reviews require finance.view.", error_code=ErrorCode.PERMISSION_DENIED)
    configs = p6_scope_configs(user, "finance.view", {"platforms", "currencies"})
    if configs is None:
        return True
    platforms = set(finance_scope["platforms"])
    currencies = set(finance_scope["currencies"])
    if any(
        platforms <= set(config.get("platforms", platforms))
        and currencies <= set(config.get("currencies", currencies))
        for config in configs
    ):
        return True
    _deny("Finance scope exceeds the finance.view data scope.")
