import pytest
from django.core.exceptions import ValidationError

from apps.integrations.marketplace_providers import (
    SyntheticShopeeOAuthProvider,
    SyntheticTikTokOAuthProvider,
    get_oauth_provider,
    synthetic_callback_signature,
)
from apps.integrations.oauth_errors import OAUTH_CALLBACK_REJECTED, OAUTH_PROVIDER_UNAVAILABLE, OAuthFlowError


def shopee_callback_params(code="synthetic-auth-code", shop_id="demo-shop-1", state="state-1"):
    params = {"code": code, "shop_id": shop_id, "state": state}
    params["sign"] = synthetic_callback_signature("shopee", **params)
    return params


def tiktok_callback_params(auth_code="synthetic-auth-code", shop_id="demo-shop-1", state="state-1", shop_cipher="CIPHER-ABCDEFGH"):
    params = {"auth_code": auth_code, "shop_id": shop_id, "state": state, "shop_cipher": shop_cipher}
    params["sign"] = synthetic_callback_signature("tiktok", **params)
    return params


def test_registry_only_exposes_synthetic_providers():
    assert isinstance(get_oauth_provider("shopee"), SyntheticShopeeOAuthProvider)
    assert isinstance(get_oauth_provider("tiktok"), SyntheticTikTokOAuthProvider)
    with pytest.raises(ValidationError):
        get_oauth_provider("bigseller")
    with pytest.raises(ValidationError):
        get_oauth_provider("")


def test_authorization_url_carries_state_redirect_and_platform_params():
    context = {"state": "state-abc", "redirect_uri": "https://callback.example.test/return/"}

    shopee = get_oauth_provider("shopee").build_authorization_url(context)
    assert "partner_id=synthetic-shopee-partner" in shopee["url"]
    assert "state=state-abc" in shopee["url"]
    assert "redirect=https://callback.example.test/return/" in shopee["url"]

    tiktok = get_oauth_provider("tiktok").build_authorization_url(context)
    assert "app_key=synthetic-tiktok-app-key" in tiktok["url"]
    assert "state=state-abc" in tiktok["url"]


def test_shopee_callback_signature_validation():
    provider = get_oauth_provider("shopee")
    context = {"state": "state-1", "region": "SG"}

    payload = provider.validate_callback(shopee_callback_params(), context)
    assert payload["platform_store_id"] == "demo-shop-1"

    tampered = shopee_callback_params()
    tampered["sign"] = "0" * 64
    with pytest.raises(OAuthFlowError) as exc_info:
        provider.validate_callback(tampered, context)
    assert exc_info.value.controlled_code == OAUTH_CALLBACK_REJECTED

    missing = shopee_callback_params()
    del missing["shop_id"]
    missing["sign"] = synthetic_callback_signature("shopee", code=missing["code"], state=missing["state"])
    with pytest.raises(OAuthFlowError):
        provider.validate_callback(missing, context)

    wrong_state = shopee_callback_params()
    with pytest.raises(OAuthFlowError):
        provider.validate_callback(wrong_state, {"state": "other-state", "region": "SG"})


def test_exchange_returns_standardized_synthetic_result_without_raw_tokens():
    provider = get_oauth_provider("shopee")
    payload = provider.validate_callback(shopee_callback_params(), {"state": "state-1", "region": "SG", "scopes": ["orders.read"]})
    payload["scopes"] = ["orders.read"]
    result = provider.exchange_authorization_code(payload)

    assert set(result) == {
        "credential_id",
        "token_id",
        "credential_mask",
        "reference_version",
        "expires_at",
        "authorized_scopes",
        "platform_subject",
        "platform_store_records",
        "provider_request_id_mask",
    }
    assert result["credential_id"].startswith("synthetic-shopee-credential-")
    assert result["token_id"].startswith("synthetic-shopee-token-")
    assert result["reference_version"] == 1
    assert result["platform_store_records"][0]["platform_store_id"] == "demo-shop-1"
    forbidden = {"access_token", "refresh_token", "secret", "api_key", "api_secret", "credentials"}
    assert forbidden.isdisjoint(result)


def test_tiktok_callback_requires_shop_cipher():
    provider = get_oauth_provider("tiktok")
    context = {"state": "state-1", "region": "SG"}

    payload = provider.validate_callback(tiktok_callback_params(), context)
    assert payload["shop_cipher"] == "CIPHER-ABCDEFGH"

    missing_cipher = tiktok_callback_params(shop_cipher="")
    with pytest.raises(OAuthFlowError):
        provider.validate_callback(missing_cipher, context)

    whitespace_cipher = tiktok_callback_params(shop_cipher="BAD CIPHER")
    with pytest.raises(OAuthFlowError):
        provider.validate_callback(whitespace_cipher, context)


def test_refresh_increments_reference_version():
    from types import SimpleNamespace

    provider = get_oauth_provider("shopee")
    authorization = SimpleNamespace(platform_store_id="demo-shop-1", credential_reference_version=3)
    result = provider.refresh_authorization(authorization)
    assert result["reference_version"] == 4
    assert result["credential_id"] == "synthetic-shopee-credential-demo-shop-1-v4"
    assert result["token_id"] == "synthetic-shopee-token-demo-shop-1-v4"


def test_revoke_and_fetch_authorized_stores_are_reference_only():
    from types import SimpleNamespace

    provider = get_oauth_provider("tiktok")
    authorization = SimpleNamespace(
        platform_store_id="demo-shop-9",
        region="SG",
        merchant_subject_id="synthetic-tiktok-merchant-demo-shop-9",
    )
    assert provider.revoke_authorization(authorization) == {"status": "revoked", "error_code": ""}
    stores = provider.fetch_authorized_stores(authorization)
    assert stores == [
        {
            "platform_store_id": "demo-shop-9",
            "region": "SG",
            "merchant_subject_id": "synthetic-tiktok-merchant-demo-shop-9",
        }
    ]


def test_normalize_error_maps_transport_and_flow_failures():
    provider = get_oauth_provider("shopee")

    class TransportError(Exception):
        provider_status = 429

    class ServerError(Exception):
        provider_status = 503

    assert provider.normalize_error(TransportError()) == OAUTH_PROVIDER_UNAVAILABLE
    assert provider.normalize_error(ServerError()) == OAUTH_PROVIDER_UNAVAILABLE
    assert provider.normalize_error(Exception("unknown")) == OAUTH_CALLBACK_REJECTED
    flow_error = OAuthFlowError(OAUTH_CALLBACK_REJECTED)
    assert provider.normalize_error(flow_error) == OAUTH_CALLBACK_REJECTED
