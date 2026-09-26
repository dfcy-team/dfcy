from django.utils import timezone

from apps.configcenter.models import SystemConfigDefinition, TenantConfigVersion

BD_PERFORMANCE_CONFIG_KEY = "influencers.bd.performance"
BD_PERFORMANCE_CONFIG_DEFAULTS = {
    "default_metrics": "core",
    "daily_attribution_reconciliation_enabled": True,
    "sample_video_overdue_days": 20,
    "sample_overdue_notification_enabled": False,
    "outreach_task_number_edit_enabled": False,
}
SAMPLE_VIDEO_OVERDUE_DAYS_MIN = 1
SAMPLE_VIDEO_OVERDUE_DAYS_MAX = 365


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
    metrics = str(value.get("default_metrics") or "").strip().lower()
    if metrics in {"core", "full"}:
        settings["default_metrics"] = metrics
    enabled = value.get("daily_attribution_reconciliation_enabled")
    if isinstance(enabled, bool):
        settings["daily_attribution_reconciliation_enabled"] = enabled
    notification_enabled = value.get("sample_overdue_notification_enabled")
    if isinstance(notification_enabled, bool):
        settings["sample_overdue_notification_enabled"] = notification_enabled
    number_edit_enabled = value.get("outreach_task_number_edit_enabled")
    if isinstance(number_edit_enabled, bool):
        settings["outreach_task_number_edit_enabled"] = number_edit_enabled
    overdue_days = value.get("sample_video_overdue_days")
    # bool is an int subclass, but must never be accepted as a duration.
    if isinstance(overdue_days, int) and not isinstance(overdue_days, bool):
        if SAMPLE_VIDEO_OVERDUE_DAYS_MIN <= overdue_days <= SAMPLE_VIDEO_OVERDUE_DAYS_MAX:
            settings["sample_video_overdue_days"] = overdue_days
    return settings


def sample_video_overdue_days(tenant_id):
    """Return the validated per-tenant deadline used for newly dated samples."""
    return bd_performance_settings(tenant_id)["sample_video_overdue_days"]


def bd_performance_config_definition():
    return SystemConfigDefinition.objects.filter(config_key=BD_PERFORMANCE_CONFIG_KEY).first()
