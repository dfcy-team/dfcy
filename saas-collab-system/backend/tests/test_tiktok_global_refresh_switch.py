import pytest

from apps.integrations import automatic_refresh
from apps.integrations.models import MarketplaceStoreAuthorization


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("bindings", [[], [{"tenant_id": 99, "store_code": "OTHER"}]])
def test_shop_inherits_switch_independently_of_legacy_bindings(monkeypatch, enabled, bindings):
    record = MarketplaceStoreAuthorization(platform="tiktok", tenant_id=1)
    monkeypatch.setattr(automatic_refresh, "get_runtime_platform_config", lambda _: {
        "auto_refresh_enabled": enabled, "auto_refresh_bindings": bindings,
    })
    assert automatic_refresh._refresh_enabled_for_record(record) is enabled


def test_missing_switch_defaults_off(monkeypatch):
    monkeypatch.setattr(automatic_refresh, "get_runtime_platform_config", lambda _: {})
    assert not automatic_refresh._refresh_enabled_for_record(
        MarketplaceStoreAuthorization(platform="tiktok", tenant_id=1)
    )


def test_lazada_nonrefreshable_scope_is_unchanged(monkeypatch):
    monkeypatch.setattr(automatic_refresh, "get_runtime_platform_config", lambda _: {
        "auto_refresh_enabled": True,
    })
    record = MarketplaceStoreAuthorization(platform="lazada", scopes=["local:no-refresh"])
    assert not automatic_refresh._refresh_enabled_for_record(record)


@pytest.mark.parametrize("status,token", [("revoked", "FAKE"), ("active", "")])
def test_enabled_switch_does_not_allow_invalid_authorization(monkeypatch, status, token):
    monkeypatch.setattr(automatic_refresh, "get_runtime_platform_config", lambda _: {
        "auto_refresh_enabled": True,
    })
    record = MarketplaceStoreAuthorization(platform="tiktok", status=status, token_id=token)
    assert not automatic_refresh.automatic_refresh_allowed(record)
