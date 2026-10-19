from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.core.exceptions import ValidationError

from apps.integrations import automatic_refresh, live_providers
from apps.integrations.live_providers import TikTokLiveOAuthProvider, _integration_config_overrides
from apps.integrations.models import MarketplaceStoreAuthorization
from apps.integrations.oauth_errors import OAuthFlowError
from apps.integrations.production_settings import validate_runtime_config
from apps.integrations.tiktok_renewal_policy import binding_matches


@pytest.fixture(params=["TK1PH", "TKKJ1PH"])
def managed(monkeypatch, request):
    config = SimpleNamespace(
        pk=17, tenant_id=3, platform="tiktok", environment="production", status="verified",
        account_alias="Shared Shop application", credential_id="FAKE_REF", callback_url="",
        platform_config={"api_type": "marketplace", "app_key": "FAKE_APP"}, sync_read_enabled=False,
    )
    record = MarketplaceStoreAuthorization(
        tenant_id=3, store_id=4, integration_config_id=17, platform="tiktok", status="active",
        region="PH", platform_store_id="90001", token_id="FAKE_TOKEN_REF", shop_cipher="FAKE_CIPHER",
    )
    record._state.fields_cache["integration_config"] = config
    record._state.fields_cache["store"] = SimpleNamespace(tenant_id=3, code=request.param)
    identity = {"tenant_id": 3, "store_code": request.param, "region": "PH",
                "platform_store_id": "90001", "integration_config_id": 17}
    runtime = {"auto_refresh_enabled": False, "auto_refresh_bindings": [identity]}
    monkeypatch.setattr(live_providers, "require_live_mode", lambda *_: None)
    monkeypatch.setattr(live_providers, "integration_config_oauth_blockers", lambda *_: ["callback_missing"])
    monkeypatch.setattr(live_providers, "get_runtime_platform_config", lambda *_: runtime)
    monkeypatch.setattr(automatic_refresh, "get_runtime_platform_config", lambda *_: runtime)
    provider = TikTokLiveOAuthProvider({
        "contract_approved": True, **_integration_config_overrides("tiktok", config),
    }, custody=Mock(), http_client=Mock())
    return config, record, identity, runtime, provider


@pytest.mark.parametrize("operation", ["refresh", "authorized-shop verification"])
def test_shared_production_refresh_uses_exact_record_without_enabling_sync(managed, operation):
    config, record, _, _, provider = managed
    provider._preflight(operation, record)
    assert automatic_refresh._refresh_enabled_for_record(record)
    assert automatic_refresh._tiktok_configuration_blockers(record) == []
    assert not config.sync_read_enabled
    provider.http.request.assert_not_called()
    provider.custody.retrieve_secret.assert_not_called()


@pytest.mark.parametrize("operation", ["authorization", "token exchange", "revoke"])
def test_shared_refresh_exception_never_enables_other_oauth_operations(managed, operation):
    _, record, _, _, provider = managed
    with pytest.raises(OAuthFlowError):
        provider._preflight(operation, record)
    provider.http.request.assert_not_called()


@pytest.mark.parametrize("field,value", [
    ("tenant_id", 9), ("store_code", "OTHER"), ("region", "TH"),
    ("platform_store_id", "90002"), ("integration_config_id", 18),
])
def test_any_mismatched_policy_dimension_fails_before_custody_or_network(managed, field, value):
    _, record, identity, _, provider = managed
    identity[field] = value
    with pytest.raises(OAuthFlowError):
        provider._preflight("refresh", record)
    assert not automatic_refresh._refresh_enabled_for_record(record)
    provider.http.request.assert_not_called()
    assert not provider.custody.mock_calls


def test_shared_config_requires_explicit_config_approval(managed):
    _, record, identity, _, provider = managed
    identity.pop("integration_config_id")
    assert binding_matches(record, [identity])  # Legacy pilot metadata remains readable.
    with pytest.raises(OAuthFlowError):
        provider._preflight("refresh", record)
    assert automatic_refresh._tiktok_configuration_blockers(record) == ["callback_missing"]


def test_global_tiktok_switch_cannot_expand_owned_shops(managed):
    _, record, identity, runtime, _ = managed
    runtime["auto_refresh_enabled"] = True
    assert automatic_refresh._refresh_enabled_for_record(record)
    identity["store_code"] = "OTHER"
    assert not automatic_refresh._refresh_enabled_for_record(record)


def test_explicit_two_shop_set_does_not_authorize_a_third_shop(managed):
    _, record, identity, runtime, provider = managed
    first = {**identity, "store_code": "TK1PH"}
    second = {**identity, "store_code": "TKKJ1PH", "platform_store_id": "90002"}
    runtime["auto_refresh_bindings"] = [first, second]
    record.store.code, record.platform_store_id = "TK1PH", "90001"
    provider._preflight("refresh", record)
    record.store.code, record.platform_store_id = "TKKJ1PH", "90002"
    provider._preflight("refresh", record)
    record.store.code = "TK3PH"
    with pytest.raises(OAuthFlowError):
        provider._preflight("refresh", record)
    assert not automatic_refresh._refresh_enabled_for_record(record)
    runtime["auto_refresh_bindings"] = []
    assert not automatic_refresh._refresh_enabled_for_record(record)


@pytest.mark.parametrize("blocker", ["network_not_approved", "credential_not_configured", "write_sync_enabled", "contract_not_approved"])
def test_shared_policy_does_not_bypass_network_custody_contract_or_write_gate(managed, monkeypatch, blocker):
    config, record, _, _, provider = managed
    monkeypatch.setattr(live_providers, "integration_config_oauth_blockers", lambda *_: ["callback_missing", blocker])
    provider.config.update(_integration_config_overrides("tiktok", config))
    with pytest.raises(OAuthFlowError):
        provider._preflight("refresh", record)
    assert blocker in automatic_refresh._tiktok_configuration_blockers(record)


@pytest.mark.parametrize("case", ["wrong_store_tenant", "wrong_config_tenant", "revoked", "no_token", "no_cipher", "ads"])
def test_invalid_saved_authorization_is_not_managed(managed, case):
    config, record, _, _, provider = managed
    if case == "wrong_store_tenant":
        record.store.tenant_id = 8
    elif case == "wrong_config_tenant":
        config.tenant_id = 8
    elif case == "revoked":
        record.status = "revoked"
    elif case == "no_token":
        record.token_id = ""
    elif case == "no_cipher":
        record.shop_cipher = ""
    else:
        config.platform_config["api_type"] = "advertising"
        provider.config.update(_integration_config_overrides("tiktok", config))
    with pytest.raises(OAuthFlowError):
        provider._preflight("refresh", record)


@pytest.mark.parametrize("value", [True, 0, "17", -1])
def test_runtime_config_binding_id_must_be_positive_integer(managed, value):
    _, _, identity, _, _ = managed
    with pytest.raises(ValidationError):
        validate_runtime_config({"platforms": {"tiktok": {"auto_refresh_bindings": [
            {**identity, "integration_config_id": value},
        ]}}})


def test_runtime_config_preserves_approved_binding_config(managed):
    _, _, identity, _, _ = managed
    result = validate_runtime_config({"platforms": {"tiktok": {"auto_refresh_bindings": [identity]}}})
    assert result["platforms"]["tiktok"]["auto_refresh_bindings"] == [identity]


def test_tiktok_ads_never_resolves_a_shop_provider(managed, monkeypatch):
    from apps.integrations.marketplace_oauth_service import resolve_oauth_provider
    config, _, _, _, _ = managed
    config.platform_config["api_type"] = "advertising"
    build = Mock()
    monkeypatch.setattr(live_providers, "build_live_provider", build)
    with pytest.raises(OAuthFlowError):
        resolve_oauth_provider("tiktok", config)
    build.assert_not_called()


def test_operator_permission_does_not_substitute_for_stored_renewal_principal(managed, monkeypatch):
    _, record, _, _, _ = managed
    stored_actor = SimpleNamespace(pk=88, is_active=True, user_type="internal", tenant_id=3)
    record._state.fields_cache["updated_by"] = stored_actor
    monkeypatch.setattr(automatic_refresh, "user_has_integration_permission", lambda actor, _: actor.pk == 77)
    monkeypatch.setattr(automatic_refresh, "integration_values_allowed", lambda *_args, **_kwargs: True)
    assert not automatic_refresh._actor_allowed(record)
    stored_actor.pk = 77
    assert automatic_refresh._actor_allowed(record)
