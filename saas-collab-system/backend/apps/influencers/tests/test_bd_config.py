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
            "default_currency": "php",
            "default_attribution": "fallback",
            "default_metrics": "full",
            "daily_attribution_reconciliation_enabled": False,
            "ignored": "value",
        }
    )

    assert bd_performance_settings(tenant_id=7) == {
        "default_currency": "PHP",
        "default_attribution": "fallback",
        "default_metrics": "full",
        "daily_attribution_reconciliation_enabled": False,
    }


@patch("apps.influencers.bd_config.TenantConfigVersion.objects")
def test_bd_performance_settings_accept_all_supported_country_currencies(version_objects):
    for currency in ("MYR", "THB"):
        version_objects.filter.return_value.order_by.return_value.first.return_value = SimpleNamespace(
            value={"default_currency": currency}
        )
        assert bd_performance_settings(tenant_id=7)["default_currency"] == currency


@patch("apps.influencers.bd_config.TenantConfigVersion.objects")
def test_bd_performance_settings_reject_invalid_values(version_objects):
    version_objects.filter.return_value.order_by.return_value.first.return_value = SimpleNamespace(
        value={
            "default_currency": "BTC",
            "default_attribution": "guess",
            "default_metrics": "everything",
            "daily_attribution_reconciliation_enabled": "false",
        }
    )

    assert bd_performance_settings(tenant_id=7) == BD_PERFORMANCE_CONFIG_DEFAULTS
