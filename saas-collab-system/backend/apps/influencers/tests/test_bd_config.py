from types import SimpleNamespace
from unittest.mock import patch

from apps.influencers.bd_config import BD_PERFORMANCE_CONFIG_DEFAULTS, bd_performance_settings


@patch("apps.influencers.bd_config.TenantConfigVersion.objects")
def test_bd_performance_settings_use_safe_defaults_without_effective_version(version_objects):
    version_objects.filter.return_value.order_by.return_value.first.return_value = None

    assert bd_performance_settings(tenant_id=7) == BD_PERFORMANCE_CONFIG_DEFAULTS


@patch("apps.influencers.bd_config.TenantConfigVersion.objects")
def test_bd_performance_settings_allow_only_supported_values(version_objects):
    version_objects.filter.return_value.order_by.return_value.first.return_value = SimpleNamespace(
        value={
            "default_metrics": "full",
            "daily_attribution_reconciliation_enabled": False,
            "sample_video_overdue_days": 30,
            "sample_overdue_notification_enabled": True,
            "ignored": "value",
        }
    )

    assert bd_performance_settings(tenant_id=7) == {
        "default_metrics": "full",
        "daily_attribution_reconciliation_enabled": False,
        "sample_video_overdue_days": 30,
        "sample_overdue_notification_enabled": True,
    }


@patch("apps.influencers.bd_config.TenantConfigVersion.objects")
def test_bd_performance_settings_reject_invalid_values(version_objects):
    version_objects.filter.return_value.order_by.return_value.first.return_value = SimpleNamespace(
        value={
            "default_metrics": "everything",
            "daily_attribution_reconciliation_enabled": "false",
            "sample_video_overdue_days": 0,
            "sample_overdue_notification_enabled": "false",
        }
    )

    assert bd_performance_settings(tenant_id=7) == BD_PERFORMANCE_CONFIG_DEFAULTS


@patch("apps.influencers.bd_config.TenantConfigVersion.objects")
def test_bd_performance_settings_reject_out_of_range_or_boolean_overdue_days(version_objects):
    for overdue_days in (366, True):
        version_objects.filter.return_value.order_by.return_value.first.return_value = SimpleNamespace(
            value={"sample_video_overdue_days": overdue_days}
        )
        assert bd_performance_settings(tenant_id=7)["sample_video_overdue_days"] == 20
