"""Strict report-specific scope adapters over operation-authorized role scopes."""
from django.core.exceptions import ValidationError
from apps.permissions.models import DataScope
from apps.permissions.resource_policies import validate_resource_policy
from apps.permissions.services import get_permission_data_scopes
from apps.permissions.ui_p6_scopes import REPORT_TYPES


def report_scope(user, resource_code, dimension, report_type, *, inventory=False):
    """Return (has_explicit_policy, allowed_ids); None ids means unrestricted legacy ALL."""
    scopes = get_permission_data_scopes(user, "reports.view", resource_code=resource_code)
    explicit = any(scope.get("source") == "resource_policy" for scope in scopes)
    if not explicit:
        return False, None

    allowed = set()
    for scope in scopes:
        config = scope.get("config")
        if scope.get("source") == "resource_policy":
            try:
                clean = validate_resource_policy(user.tenant_id, resource_code, scope.get("scope_type"), config)
            except (ValidationError, KeyError, TypeError, ValueError):
                continue
            if clean == {"all": True}:
                return True, None
            allowed.update(clean.get(dimension, []))
            continue

        # Legacy branches are atomic: mixed or malformed configs contribute nothing.
        if scope.get("scope_type") == DataScope.ScopeType.ALL and config in ({}, {"all": True}):
            return True, None
        if scope.get("scope_type") != DataScope.ScopeType.CUSTOM or not isinstance(config, dict):
            continue
        if set(config) == {"report_types"}:
            values = config["report_types"]
            if (isinstance(values, list) and values and all(isinstance(value, str) for value in values)
                    and set(values) <= REPORT_TYPES and report_type in values):
                return True, None
        if inventory and set(config) == {"warehouse_ids"}:
            values = config["warehouse_ids"]
            if isinstance(values, list) and values and all(type(value) is int and value > 0 for value in values):
                allowed.update(values)
    return True, allowed
