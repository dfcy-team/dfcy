"""Only synthetic URLs/credentials; no provider, production or network access."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError

from apps.integrations import live_providers, serializers, views
from apps.integrations.tiktok_callback_policy import expected_oauth_callback

SHOP = "https://saas.example.test/integrations/tiktok/shop-callback"
ADS = "https://saas.example.test/integrations/tiktok-ads/direct-callback"
LEGACY = "https://legacy.example.test/callback"
PRODUCTS = [("marketplace", SHOP, "TIKTOK_SHOP_DIRECT_CALLBACK_URL"),
            ("advertising", ADS, "TIKTOK_ADS_DIRECT_CALLBACK_URL")]


@pytest.fixture
def policy(settings, monkeypatch):
    settings.TIKTOK_SHOP_DIRECT_CALLBACK_URL = SHOP
    settings.TIKTOK_ADS_DIRECT_CALLBACK_URL = ADS
    runtime = {"redirect_uri": LEGACY, "contract_approved": True, "app_id": "synthetic-app"}
    network = {"oauth_redirect_allowlist": [LEGACY, SHOP, ADS], "mode": "approved-live-test",
               "security_approved": True, "allowed_hosts": ["api.example.test"]}
    for module in (serializers, live_providers):
        monkeypatch.setattr(module, "get_runtime_platform_config", lambda *a: runtime)
        monkeypatch.setattr(module, "get_runtime_setting", lambda group, key, default=None: network.get(key, default))
    monkeypatch.setattr(live_providers, "approved_custody_configured", lambda: True)
    return runtime, network


@pytest.mark.parametrize("api_type,callback,setting", PRODUCTS)
def test_each_product_direct_callback_preserves_legacy_expectation(policy, api_type, callback, setting):
    runtime, _ = policy
    assert expected_oauth_callback("tiktok", callback_url=callback, api_type=api_type, legacy_callback=LEGACY) == callback
    assert serializers.validate_marketplace_callback_url(callback, environment="production", platform="tiktok", api_type=api_type) == callback
    assert runtime["redirect_uri"] == LEGACY


@pytest.mark.parametrize("api_type,callback,setting", PRODUCTS)
@pytest.mark.parametrize("allowlist", [[], [LEGACY]])
def test_direct_setting_is_not_allowlist_approval(policy, api_type, callback, setting, allowlist):
    policy[1]["oauth_redirect_allowlist"] = allowlist
    with pytest.raises(ValidationError):
        serializers.validate_marketplace_callback_url(callback, environment="production", platform="tiktok", api_type=api_type)


@pytest.mark.parametrize("api_type,callback", [("marketplace", ADS), ("advertising", SHOP), ("inventory", SHOP)])
def test_cross_product_is_rejected_even_when_global_and_allowlist_match(policy, api_type, callback):
    policy[0]["redirect_uri"] = callback
    with pytest.raises(ValidationError):
        serializers.validate_marketplace_callback_url(callback, environment="production", platform="tiktok", api_type=api_type)


@pytest.mark.parametrize("api_type,callback,setting", PRODUCTS)
@pytest.mark.parametrize("invalid", ["", "http://saas.example.test/wrong", "https://saas.example.test/wrong", None, 42])
def test_invalid_relevant_setting_cannot_fall_back(policy, settings, api_type, callback, setting, invalid):
    setattr(settings, setting, invalid)
    policy[0]["redirect_uri"] = callback
    with pytest.raises(ValidationError):
        serializers.validate_marketplace_callback_url(callback, environment="production", platform="tiktok", api_type=api_type)


@pytest.mark.parametrize("api_type,callback,setting", PRODUCTS)
@pytest.mark.parametrize("suffix", ["?", "?state=bad", "#", "#fragment", "/", "\\bad"])
def test_direct_url_is_exact_not_prefix_match(policy, settings, api_type, callback, setting, suffix):
    candidate = callback + suffix
    setattr(settings, setting, candidate)
    policy[0]["redirect_uri"] = candidate
    policy[1]["oauth_redirect_allowlist"].append(candidate)
    with pytest.raises(ValidationError):
        serializers.validate_marketplace_callback_url(candidate, environment="production", platform="tiktok", api_type=api_type)


@pytest.mark.parametrize("api_type,callback,setting", PRODUCTS)
def test_legacy_config_ignores_unrelated_invalid_direct_settings(policy, settings, api_type, callback, setting):
    settings.TIKTOK_SHOP_DIRECT_CALLBACK_URL = "invalid-shop-setting"
    settings.TIKTOK_ADS_DIRECT_CALLBACK_URL = "invalid-ads-setting"
    assert serializers.validate_marketplace_callback_url(LEGACY, environment="production", platform="tiktok", api_type=api_type) == LEGACY
    with pytest.raises(ValidationError):
        serializers.validate_marketplace_callback_url("https://other.example.test/callback", environment="production", platform="tiktok", api_type=api_type)


@pytest.mark.parametrize("platform", ["shopee", "lazada"])
def test_non_tk_callback_behavior_is_unchanged(policy, settings, platform):
    settings.TIKTOK_SHOP_DIRECT_CALLBACK_URL = SHOP
    assert serializers.validate_marketplace_callback_url(LEGACY, environment="production", platform=platform) == LEGACY
    with pytest.raises(ValidationError):
        serializers.validate_marketplace_callback_url(SHOP, environment="production", platform=platform)


@pytest.mark.parametrize("values", [[42], "not-an-object", None])
def test_config_serializer_malformed_values_reach_existing_schema_rejection(policy, values):
    serializer = serializers.PlatformIntegrationConfigSerializer(data={})
    with pytest.raises((ValidationError, DjangoValidationError)):
        serializer.validate({"platform": "tiktok", "environment": "production", "contract_version": "202407",
            "regions": ["PH"], "scopes": ["seller.authorization.info"], "platform_config": values,
            "callback_url": SHOP})


@pytest.mark.parametrize("api_type,callback,setting", PRODUCTS)
def test_readiness_uses_same_policy_and_still_requires_allowlist(policy, api_type, callback, setting):
    config = SimpleNamespace(platform="tiktok", environment="production", status="verified", network_enabled=True,
        sync_write_enabled=False, credential_status="configured", credential_id="synthetic-ref",
        contract_version="202407", callback_url=callback,
        platform_config={"api_type": api_type, "app_key": "synthetic-app"})
    assert live_providers.integration_config_oauth_blockers("tiktok", config) == []
    policy[1]["oauth_redirect_allowlist"] = [LEGACY]
    assert "callback_not_allowlisted" in live_providers.integration_config_oauth_blockers("tiktok", config)
    policy[1]["oauth_redirect_allowlist"] = [LEGACY, SHOP, ADS]
    config.callback_url = ADS if api_type == "marketplace" else SHOP
    assert "callback_mismatch" in live_providers.integration_config_oauth_blockers("tiktok", config)


@pytest.mark.parametrize("api_type,callback,setting", PRODUCTS)
def test_credential_update_validates_selected_product_before_custody(policy, monkeypatch, api_type, callback, setting):
    custody = Mock(side_effect=AssertionError("No custody access expected"))
    monkeypatch.setattr(views, "get_custody_backend", custody)
    config = SimpleNamespace(platform="tiktok", environment="production", callback_url=LEGACY,
        platform_config={"api_type": api_type, "app_key": "synthetic-app", "service_id": "123456789", "app_id": "123456789"})
    values = {"redirect_uri": callback, **({"ads_secret": "SYNTHETIC_ONLY"} if api_type == "advertising" else {"app_secret": "SYNTHETIC_ONLY"})}
    secrets, candidate, selected = views._credential_update_parts(config, values)
    assert selected == callback and candidate["api_type"] == api_type and secrets
    assert config.callback_url == LEGACY
    values["redirect_uri"] = ADS if api_type == "marketplace" else SHOP
    with pytest.raises(ValidationError):
        views._credential_update_parts(config, values)
    policy[1]["oauth_redirect_allowlist"] = [LEGACY]
    values["redirect_uri"] = callback
    with pytest.raises(ValidationError):
        views._credential_update_parts(config, values)
    custody.assert_not_called()
