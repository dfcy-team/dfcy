"""Narrow compatibility proof for Ads mappings bound before runtime-only changes."""
from copy import deepcopy

from django.utils import timezone

from apps.configcenter.models import SystemConfigDefinition, TenantConfigVersion

from .oauth_state_service import _configuration_digest
from .production_settings import (
    CONFIG_KEY, SAFE_DEFAULTS, _deep_merge, _environment_config,
    get_effective_runtime_version, get_runtime_platform_config,
    runtime_snapshot, validate_runtime_config,
)
from .models import marketplace_authorization_api_type

UNRELATED_PLATFORM_FIELDS = frozenset({
    "creator_query_bindings", "affiliate_seller_creator_scope",
    "affiliate_seller_creator_read_approved", "auto_refresh_bindings",
    "auto_refresh_exclusions",
})


def _platform(value):
    platforms = value.get("platforms") if isinstance(value, dict) else None
    tiktok = platforms.get("tiktok") if isinstance(platforms, dict) else None
    return tiktok if isinstance(tiktok, dict) else None


def _differences(left, right):
    keys = set(left) | set(right)
    return {key for key in keys if left.get(key) != right.get(key)}


def _historical_platform(version):
    try:
        env = validate_runtime_config(_environment_config())
        resolved = _deep_merge(SAFE_DEFAULTS, env)
        value = validate_runtime_config(version.value)
        historical_platform = _platform(value)
        if historical_platform is None:
            return []
        resolved = validate_runtime_config(_deep_merge(resolved, value))
        variants = [resolved["platforms"]["tiktok"]]
        # Runtime-only TikTok Shop fields were added after older approvals.
        # Try historical field-shape variants, but always require an exact hash.
        for key in ("auto_refresh_bindings", "auto_refresh_exclusions", "creator_query_bindings"):
            if key not in historical_platform:
                legacy_variants = []
                for item in variants:
                    if key in item:
                        legacy = deepcopy(item)
                        legacy.pop(key, None)
                        legacy_variants.append(legacy)
                variants.extend(legacy_variants)
        return variants
    except Exception:
        return []


def accepts_bound_session_digest(config, stored_digest):
    """Accept an exact current digest, or prove a narrowly compatible Ads-era digest."""
    try:
        current_version = get_effective_runtime_version()
        if not runtime_snapshot().get("valid"):
            return False
        current_platform = get_runtime_platform_config(config.platform)
        # The active runtime must itself be valid before either proof is considered.
        validate_runtime_config({"platforms": {config.platform: current_platform}})
        current_digest = _configuration_digest(
            config, current_version.pk if current_version else None, current_platform
        )
        if stored_digest and stored_digest == current_digest:
            return True
        if (config.platform != "tiktok" or marketplace_authorization_api_type(config) != "advertising"
                or not stored_digest):
            return False
        now = timezone.now()
        versions = TenantConfigVersion.objects.select_related("definition").filter(
            config_key=CONFIG_KEY, scope_key="system",
            status__in=(TenantConfigVersion.Status.EFFECTIVE, TenantConfigVersion.Status.SUPERSEDED),
            definition__scope_type=SystemConfigDefinition.ScopeType.SYSTEM,
            effective_at__lte=now,
        ).order_by("-version", "-id")[:50]
        for version in versions:
            for historical_platform in _historical_platform(version):
                if not _differences(historical_platform, current_platform) <= UNRELATED_PLATFORM_FIELDS:
                    continue
                if _configuration_digest(config, version.pk, historical_platform) == stored_digest:
                    return True
        return False
    except Exception:
        return False
