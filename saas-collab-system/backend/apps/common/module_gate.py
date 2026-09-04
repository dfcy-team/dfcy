"""Environment/runtime module rollout gates.

The gate is intentionally small and dependency-light so HTTP views, Celery
tasks and management commands can share one decision.  Production settings
versions (when available) take precedence; local Sandbox profiles remain an
explicit development override.  An unset production allowlist preserves the
legacy behavior until an operator creates an approved module configuration.
"""

from __future__ import annotations

import os
from functools import lru_cache

from django.conf import settings


MODULE_STATES = frozenset({"disabled", "mock_only", "pilot_readonly", "enabled"})

MODULE_CODES = (
    "core", "masterdata", "product_development", "supply_chain", "inventory",
    "global_listing", "sales", "influencer", "finance", "analytics", "decision",
    "reports", "workflow", "rpa", "api_integrations", "system", "governance",
)

LOCAL_PROFILE_MODULES = {
    "core": {"core", "masterdata", "system", "governance"},
    "sales-inventory-finance-reconciliation": {"core", "masterdata", "sales", "inventory", "finance", "analytics", "decision", "reports"},
    "creator-management": {"core", "masterdata", "influencer"},
    "procurement": {"core", "masterdata", "supply_chain"},
    "integration": set(MODULE_CODES),
}


def _environment_allowlist() -> set[str] | None:
    raw = getattr(settings, "ENABLED_MODULES", None)
    if not raw:
        raw = os.getenv("ENABLED_MODULES", "")
    if isinstance(raw, str):
        values = {item.strip().lower() for item in raw.split(",") if item.strip()}
    else:
        values = {str(item).strip().lower() for item in (raw or []) if str(item).strip()}
    return values or None


def _local_profile_allowlist() -> set[str] | None:
    if not getattr(settings, "DEBUG", False):
        return None
    profile = str(getattr(settings, "LOCAL_SANDBOX_MODULE", "") or os.getenv("LOCAL_SANDBOX_MODULE", "")).strip().lower()
    if not profile:
        return None
    return LOCAL_PROFILE_MODULES.get(profile)


@lru_cache(maxsize=1)
def _env_states() -> dict[str, str]:
    allowlist = _local_profile_allowlist() or _environment_allowlist()
    if allowlist is None:
        return {code: "enabled" for code in MODULE_CODES}
    return {code: ("enabled" if code in allowlist else "disabled") for code in MODULE_CODES}


def _database_state(code: str) -> str | None:
    """Read an approved production module status without making it mandatory."""
    if getattr(settings, "DEBUG", False):
        return None
    try:
        from apps.integrations.production_settings import get_runtime_setting

        value = get_runtime_setting("modules", code, default=None)
    except Exception:  # noqa: BLE001 - a missing DB/config must fail open to env compatibility
        return None
    return value if value in MODULE_STATES else None


def get_module_status(code: str) -> str:
    normalized = str(code or "").strip().lower()
    if normalized not in MODULE_CODES:
        return "disabled"
    return _database_state(normalized) or _env_states().get(normalized, "enabled")


def is_module_enabled(code: str) -> bool:
    return get_module_status(code) in {"pilot_readonly", "enabled"}


def is_module_readonly(code: str) -> bool:
    return get_module_status(code) == "pilot_readonly"


def module_statuses() -> dict[str, str]:
    return {code: get_module_status(code) for code in MODULE_CODES}


def clear_module_gate_cache() -> None:
    _env_states.cache_clear()


__all__ = [
    "MODULE_CODES", "MODULE_STATES", "get_module_status", "is_module_enabled",
    "is_module_readonly", "module_statuses", "clear_module_gate_cache",
]
