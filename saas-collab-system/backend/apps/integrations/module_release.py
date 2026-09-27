"""Versioned system module-release controls.

Module rollout is deliberately stored under its own configuration key.  Older
deployments stored a modules-only document in the production runtime stream;
the compatibility reader preserves that approved state until an administrator
creates the first independent module-release version.
"""

from __future__ import annotations

from copy import deepcopy

from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.db.utils import OperationalError, ProgrammingError
from django.utils import timezone


MODULE_RELEASE_CONFIG_KEY = "system.module.release_control"
MODULE_STATES = frozenset({"disabled", "mock_only", "pilot_readonly", "enabled"})
MODULE_CODES = (
    "core", "masterdata", "product_development", "supply_chain", "inventory",
    "global_listing", "sales", "influencer", "finance", "analytics", "decision",
    "reports", "workflow", "rpa", "api_integrations", "system", "governance",
)
DEFAULT_MODULES = {code: "enabled" for code in MODULE_CODES}


def is_legacy_module_release_config(value) -> bool:
    """Identify the accidental modules-only production-runtime history rows."""
    return isinstance(value, dict) and set(value) == {"modules"} and isinstance(value.get("modules"), dict)


def contains_module_release_data(value) -> bool:
    """Detect all legacy production-runtime documents carrying module state."""
    return isinstance(value, dict) and "modules" in value


def validate_module_release_config(value):
    if not isinstance(value, dict) or set(value) != {"modules"}:
        raise ValidationError("Module release configuration must contain only a modules object.")
    modules = value["modules"]
    if not isinstance(modules, dict):
        raise ValidationError("modules must be an object.")
    unknown = set(modules) - set(MODULE_CODES)
    if unknown:
        raise ValidationError(f"Unsupported module code(s): {', '.join(sorted(unknown))}.")
    missing = set(MODULE_CODES) - set(modules)
    if missing:
        raise ValidationError(f"Missing module code(s): {', '.join(sorted(missing))}.")
    if any(state not in MODULE_STATES for state in modules.values()):
        raise ValidationError(f"Module state must be one of: {', '.join(sorted(MODULE_STATES))}.")
    return {"modules": {code: modules[code] for code in MODULE_CODES}}


def _latest_effective(config_key):
    from apps.configcenter.models import SystemConfigDefinition, TenantConfigVersion

    return (
        TenantConfigVersion.objects.select_related("definition", "created_by", "approved_by")
        .filter(
            config_key=config_key,
            scope_key="system",
            status=TenantConfigVersion.Status.EFFECTIVE,
            definition__scope_type=SystemConfigDefinition.ScopeType.SYSTEM,
            effective_at__lte=timezone.now(),
        )
        .order_by("-version", "-id")
        .first()
    )


def get_effective_module_release_version():
    """Use the independent key first, then retain the last legacy modules row."""
    try:
        version = _latest_effective(MODULE_RELEASE_CONFIG_KEY)
        if version is not None:
            return version

        from apps.integrations.production_settings import CONFIG_KEY
        from apps.configcenter.models import TenantConfigVersion

        # A later full production-runtime approval supersedes the legacy row.
        # It must not erase a module decision made before this split, so inspect
        # both effective and superseded legacy records until the new key exists.
        for candidate in (
            TenantConfigVersion.objects.select_related("definition", "created_by", "approved_by")
            .filter(
                config_key=CONFIG_KEY,
                scope_key="system",
                status__in=(TenantConfigVersion.Status.EFFECTIVE, TenantConfigVersion.Status.SUPERSEDED),
                effective_at__lte=timezone.now(),
            )
            .order_by("-version", "-id")
        ):
            if is_legacy_module_release_config(candidate.value):
                return candidate
    except (DatabaseError, OperationalError, ProgrammingError, RuntimeError):
        return None
    return None


def get_module_release_config():
    version = get_effective_module_release_version()
    if version is None:
        return deepcopy(DEFAULT_MODULES)
    try:
        return validate_module_release_config(version.value)["modules"]
    except ValidationError:
        return deepcopy(DEFAULT_MODULES)
