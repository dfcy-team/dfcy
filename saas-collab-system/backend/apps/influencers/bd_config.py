from django.utils import timezone

from apps.configcenter.models import SystemConfigDefinition, TenantConfigVersion

from .models import SUPPORTED_CURRENCY_CHOICES


BD_PERFORMANCE_CONFIG_KEY = "influencers.bd.performance"
BD_PERFORMANCE_CONFIG_DEFAULTS = {
    "default_currency": "CNY",
    "default_attribution": "strict",
    "default_metrics": "core",
    "daily_attribution_reconciliation_enabled": True,
}


def bd_performance_settings(tenant_id):
    """Return validated tenant settings without allowing unsafe report values."""
    settings = dict(BD_PERFORMANCE_CONFIG_DEFAULTS)
    version = (
        TenantConfigVersion.objects.filter(
            tenant_id=tenant_id,
            config_key=BD_PERFORMANCE_CONFIG_KEY,
            status=TenantConfigVersion.Status.EFFECTIVE,
            effective_at__lte=timezone.now(),
        )
        .order_by("-version", "-id")
        .first()
    )
    if version is None or not isinstance(version.value, dict):
        return settings

    value = version.value
    currency = str(value.get("default_currency") or "").strip().upper()
    attribution = str(value.get("default_attribution") or "").strip().lower()
    metrics = str(value.get("default_metrics") or "").strip().lower()
    supported_currencies = {code for code, _label in SUPPORTED_CURRENCY_CHOICES}
    if currency in supported_currencies:
        settings["default_currency"] = currency
    if attribution in {"strict", "fallback"}:
        settings["default_attribution"] = attribution
    if metrics in {"core", "full"}:
        settings["default_metrics"] = metrics
    enabled = value.get("daily_attribution_reconciliation_enabled")
    if isinstance(enabled, bool):
        settings["daily_attribution_reconciliation_enabled"] = enabled
    return settings


def bd_performance_config_definition():
    return SystemConfigDefinition.objects.filter(config_key=BD_PERFORMANCE_CONFIG_KEY).first()
