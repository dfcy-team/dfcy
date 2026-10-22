import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError

from apps.integrations import tiktok_callback_settings as resolver
from apps.integrations.production_settings import validate_runtime_config
from apps.integrations import tiktok_direct_callback, tiktok_ads_direct

SHOP = "https://saas.example.test/integrations/tiktok/shop-callback"
ADS = "https://saas.example.test/integrations/tiktok-ads/direct-callback"


def snapshot(monkeypatch, values, allowlist=(), source="database"):
    monkeypatch.setattr(resolver, "runtime_snapshot", lambda: {
        "source": source, "config": {"platforms": {"tiktok": values},
        "network": {"oauth_redirect_allowlist": list(allowlist)}}})


def test_web_callbacks_override_environment(monkeypatch, settings):
    settings.TIKTOK_SHOP_DIRECT_CALLBACK_URL = "https://old.invalid/"
    settings.TIKTOK_ADS_DIRECT_CALLBACK_URL = "https://old.invalid/"
    snapshot(monkeypatch, {"shop_direct_callback_url": SHOP, "ads_direct_callback_url": ADS}, [SHOP, ADS])
    assert tiktok_direct_callback.configured_callback() == SHOP
    assert tiktok_ads_direct.configured_callback() == ADS


def test_explicit_empty_disables_env(monkeypatch, settings):
    settings.TIKTOK_SHOP_DIRECT_CALLBACK_URL = SHOP
    snapshot(monkeypatch, {"shop_direct_callback_url": ""})
    assert resolver.callback_setting() == ""


def test_missing_field_preserves_environment(monkeypatch, settings):
    settings.TIKTOK_SHOP_DIRECT_CALLBACK_URL = SHOP
    snapshot(monkeypatch, {})
    assert resolver.callback_setting() == SHOP


def test_allowlist_required(monkeypatch):
    snapshot(monkeypatch, {"shop_direct_callback_url": SHOP})
    with pytest.raises(ValidationError):
        resolver.callback_setting()


def test_invalid_snapshot_never_falls_back(monkeypatch, settings):
    settings.TIKTOK_SHOP_DIRECT_CALLBACK_URL = SHOP
    snapshot(monkeypatch, {}, source="invalid_database")
    with pytest.raises(ValidationError):
        resolver.callback_setting()


@pytest.mark.parametrize("key,value", [
    ("shop_direct_callback_url", ADS), ("ads_direct_callback_url", SHOP),
    ("shop_direct_callback_url", SHOP.replace("https:", "http:")),
    ("shop_direct_callback_url", SHOP + "?code=placeholder"),
    ("shop_direct_callback_url", SHOP + "#fragment"),
])
def test_invalid_web_callback_rejected(key, value):
    with pytest.raises(DjangoValidationError):
        validate_runtime_config({"platforms": {"tiktok": {key: value}}})


def test_valid_fields_survive_validation():
    values = {"shop_direct_callback_url": SHOP, "ads_direct_callback_url": ADS}
    result = validate_runtime_config({"platforms": {"tiktok": values}})
    assert all(result["platforms"]["tiktok"][key] == value for key, value in values.items())
