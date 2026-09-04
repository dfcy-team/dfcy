import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings

from apps.common.module_gate import clear_module_gate_cache, get_module_status, is_module_readonly


def setup_function():
    clear_module_gate_cache()


def teardown_function():
    clear_module_gate_cache()


@override_settings(DEBUG=False, ENABLED_MODULES=["core", "api_integrations"])
def test_production_allowlist_disables_unlisted_modules():
    assert get_module_status("core") == "enabled"
    assert get_module_status("product_development") == "disabled"


@override_settings(DEBUG=True, LOCAL_SANDBOX_MODULE="procurement", ENABLED_MODULES=[])
def test_local_profile_enables_only_profile_modules():
    assert get_module_status("supply_chain") == "enabled"
    assert get_module_status("rpa") == "disabled"


@override_settings(DEBUG=False, ENABLED_MODULES=[])
def test_unconfigured_environment_preserves_legacy_behavior():
    assert get_module_status("workflow") == "enabled"


@override_settings(DEBUG=False, ENABLED_MODULES=["api_integrations"])
def test_pilot_readonly_is_reported_as_readonly(monkeypatch):
    monkeypatch.setattr("apps.common.module_gate._database_state", lambda code: "pilot_readonly" if code == "api_integrations" else None)
    assert is_module_readonly("api_integrations") is True


@override_settings(DEBUG=False, ENABLED_MODULES=["core"])
def test_disabled_global_listing_blocks_production_queue():
    from apps.integrations.production_settings import assert_listing_production_allowed

    with pytest.raises(ValidationError, match="global listing module is disabled"):
        assert_listing_production_allowed(
            platform="shopee",
            action="create",
            store_id=1,
            confirm_production=True,
            config={},
        )
