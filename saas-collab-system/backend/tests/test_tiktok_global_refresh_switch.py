import pytest

from apps.integrations import automatic_refresh
from apps.integrations.models import MarketplaceStoreAuthorization


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("verified", [False, True])
def test_shop_requires_global_switch_and_verified_binding(monkeypatch, enabled, verified):
    record = MarketplaceStoreAuthorization(platform="tiktok", tenant_id=1)
    monkeypatch.setattr(automatic_refresh, "get_runtime_platform_config", lambda _: {
        "auto_refresh_enabled": enabled,
    })
    monkeypatch.setattr("apps.integrations.tiktok_renewal_policy.binding_matches", lambda *_: False)
    monkeypatch.setattr("apps.integrations.tiktok_renewal_policy.has_verified_oauth_binding", lambda _: verified)
    assert automatic_refresh._refresh_enabled_for_record(record) is (enabled and verified)


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
