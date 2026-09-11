"""Synthetic OAuth failures: no platform traffic or real credentials."""
import json
from unittest.mock import Mock

import pytest

from apps.integrations.live_providers import ShopeeLiveOAuthProvider
from apps.integrations.net_guard import HttpResponse, PlatformHttpClient
from apps.integrations.oauth_errors import OAuthFlowError


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr("apps.integrations.net_guard.assert_host_allowed", lambda url: None)
    monkeypatch.setattr(ShopeeLiveOAuthProvider, "_preflight", lambda *args: None)
    custody = Mock()
    custody.retrieve_secret.return_value = "FAKE_DEVELOPER_SECRET"
    custody.retrieve_access_token.return_value = "FAKE_ACCESS"
    custody.store_secrets.return_value = {"credential_id": "fake-new-ref", "token_id": "fake-new-token"}
    client = PlatformHttpClient(transport=Mock(), max_retries=2, sleeper=lambda delay: None)
    return ShopeeLiveOAuthProvider({
        "app_id": "123", "app_secret_reference": "fake-secret-ref", "api_host": "https://example.test",
        "token_path": "/token", "shop_path": "/shop", "region": "PH",
    }, http_client=client, custody=custody)


PAYLOAD = {"code": "FAKE_CODE", "platform_store_id": "42", "merchant_subject_id": "42"}


def response(data, status=200):
    return HttpResponse(status, {}, json.dumps(data))


def tokens():
    return response({"access_token": "FAKE_ACCESS", "refresh_token": "FAKE_REFRESH", "expire_in": 3600})


@pytest.mark.parametrize("failure,category", [
    (TimeoutError("FAKE_CODE"), "timeout_uncertain"),
    (response({"error": "FAKE_SECRET", "message": "FAKE_CODE"}, 503), "service_uncertain"),
    (response({"error": "error_auth", "request_id": "FAKE_REQUEST"}, 401), "authentication_rejected"),
])
def test_code_exchange_is_never_retried(provider, failure, category):
    if isinstance(failure, Exception):
        provider.http._transport.side_effect = failure
    else:
        provider.http._transport.return_value = failure
    with pytest.raises(OAuthFlowError) as caught:
        provider.exchange_authorization_code(PAYLOAD)
    assert provider.http._transport.call_count == 1
    assert caught.value.stage == "exchange_token"
    assert caught.value.category == category
    provider.custody.store_secrets.assert_not_called()
    assert "FAKE_" not in str(caught.value)


def test_platform_body_error_is_allowlisted_not_echoed(provider):
    provider.http._transport.return_value = response({
        "error": "FAKE_SECRET", "message": "FAKE_CODE", "request_id": "FAKE_REQUEST",
    })
    with pytest.raises(OAuthFlowError) as caught:
        provider.exchange_authorization_code(PAYLOAD)
    assert caught.value.platform_error_code == "UNCLASSIFIED"
    assert caught.value.stage == "exchange_token"
    assert caught.value.http_status == 200
    assert caught.value.request_id_mask.startswith("req-")
    assert "FAKE_" not in str(caught.value)


@pytest.mark.parametrize("code,controlled", [
    ("error_auth", "OAUTH_AUTH_REJECTED"), ("error_param", "OAUTH_PROVIDER_ERROR"),
    ("UNRECOGNIZED_FAKE_SECRET", "OAUTH_PROVIDER_ERROR"),
])
def test_body_errors_are_not_all_classified_as_authentication(provider, code, controlled):
    provider.http._transport.return_value = response({"error": code})
    with pytest.raises(OAuthFlowError) as caught:
        provider.exchange_authorization_code(PAYLOAD)
    assert caught.value.controlled_code == controlled
    assert provider.http._transport.call_count == 1


def test_custody_timeout_retains_uncertain_outcome(provider):
    provider.http._transport.return_value = tokens()
    failure = OAuthFlowError("OAUTH_PROVIDER_UNAVAILABLE")
    failure.category = "timeout_uncertain"
    provider.custody.store_secrets.side_effect = failure
    with pytest.raises(OAuthFlowError) as caught:
        provider.exchange_authorization_code(PAYLOAD)
    assert caught.value.stage == "save_token"
    assert caught.value.category == "timeout_uncertain"


def test_shop_parameter_rejection_is_not_an_identity_mismatch(provider):
    provider.http._transport.side_effect = [tokens(), response({"error": "error_param"})]
    with pytest.raises(OAuthFlowError) as caught:
        provider.exchange_authorization_code(PAYLOAD)
    assert caught.value.stage == "verify_store"
    assert caught.value.category == "platform_error"
    assert caught.value.platform_error_code == "error_param"


def test_ip_allowlist_rejection_has_actionable_safe_category(provider):
    provider.http._transport.return_value = response({
        "error": "ip_test_only", "message": "Check source IP 203.0.113.7 in your whitelist. FAKE_SECRET",
    }, 403)
    with pytest.raises(OAuthFlowError) as caught:
        provider.exchange_authorization_code(PAYLOAD)
    assert caught.value.category == "ip_allowlist_rejected"
    assert caught.value.platform_error_code == "UNCLASSIFIED"
    assert caught.value.stage == "exchange_token"
    assert provider.http._transport.call_count == 1
    assert "FAKE_SECRET" not in str(caught.value)
    assert "203.0.113.7" not in str(caught.value)


@pytest.mark.parametrize("platform,status,code,message", [
    ("shopee", 401, "ip_test_only", "IP whitelist"),
    ("tiktok", 403, "ip_test_only", "IP whitelist"),
    ("shopee", 403, "error_auth", "Consider checking the IP whitelist"),
    ("shopee", 403, "ip_test_only", "An unrelated failure"),
])
def test_other_failures_are_not_assumed_to_be_ip_allowlist(platform, status, code, message):
    from apps.integrations.oauth_diagnostics import response_metadata
    metadata = response_metadata(response({"error": code, "message": message}, status), platform)
    assert metadata.get("category") != "ip_allowlist_rejected"


def test_custody_auth_is_not_platform_auth(provider):
    provider.custody.retrieve_secret.side_effect = OAuthFlowError("OAUTH_AUTH_REJECTED")
    with pytest.raises(OAuthFlowError) as caught:
        provider.exchange_authorization_code(PAYLOAD)
    assert caught.value.stage == "read_developer_secret"
    assert caught.value.category == "custody_authentication_rejected"
    provider.http._transport.assert_not_called()


def test_token_save_failure_is_distinct(provider):
    provider.http._transport.return_value = tokens()
    provider.custody.store_secrets.side_effect = RuntimeError("FAKE_ACCESS")
    with pytest.raises(OAuthFlowError) as caught:
        provider.exchange_authorization_code(PAYLOAD)
    assert caught.value.stage == "save_token"
    assert caught.value.category == "custody_failure"
    assert provider.http._transport.call_count == 1


@pytest.mark.parametrize("shop,evidence", [
    ({}, "shop_id_missing"), ({"shop_id": 99}, "shop_id_mismatch"),
    (["FAKE_SECRET"], "invalid_shop_response"),
])
def test_missing_or_wrong_identity_is_not_success(provider, shop, evidence):
    provider.http._transport.side_effect = [tokens(), response({"response": shop, "request_id": "FAKE_REQUEST"})]
    with pytest.raises(OAuthFlowError) as caught:
        provider.exchange_authorization_code(PAYLOAD)
    assert caught.value.stage == "verify_store"
    assert caught.value.identity_evidence == evidence
    assert caught.value.http_status == 200
    assert caught.value.request_id_mask.startswith("req-")
    provider.custody.revoke.assert_called_once_with("fake-new-ref", "fake-new-token")


@pytest.mark.parametrize("scope,evidence", [
    ([42], "contains_callback_shop"), ([99], "does_not_contain_callback_shop"),
    (None, "not_provided"), ("FAKE_SECRET", "invalid_shape"),
])
def test_failed_identity_retains_only_safe_token_scope_evidence(provider, scope, evidence, caplog):
    from types import SimpleNamespace
    from apps.integrations.oauth_diagnostics import failure_diagnostic
    provider.http._transport.side_effect = [response({
        "access_token": "FAKE_ACCESS", "refresh_token": "FAKE_REFRESH", "shop_id_list": scope,
    }), response({"response": {}})]
    with pytest.raises(OAuthFlowError) as caught:
        provider.exchange_authorization_code(PAYLOAD)
    diagnostic = failure_diagnostic(caught.value, SimpleNamespace(platform="shopee", integration_config_id=1, pk=1))
    expected_identity = {"does_not_contain_callback_shop": "token_scope_mismatch", "invalid_shape": "invalid_token_scope"}.get(evidence, "shop_id_missing")
    assert diagnostic["identity_evidence"] == expected_identity
    assert diagnostic["token_scope_evidence"] == evidence
    assert "FAKE_" not in json.dumps(diagnostic) + caplog.text
    provider.custody.revoke.assert_called_once()


def test_unknown_identity_diagnostic_text_is_not_emitted(caplog):
    from types import SimpleNamespace
    from apps.integrations.oauth_diagnostics import failure_diagnostic
    exc = OAuthFlowError("OAUTH_CALLBACK_REJECTED")
    exc.identity_evidence = "FAKE_SECRET"
    exc.token_scope_evidence = "FAKE_ACCESS"
    diagnostic = failure_diagnostic(exc, SimpleNamespace(platform="shopee", integration_config_id=1, pk=1))
    assert "identity_evidence" not in diagnostic
    assert "token_scope_evidence" not in diagnostic
    assert "FAKE_" not in json.dumps(diagnostic) + caplog.text


def test_success_requires_stored_tokens_and_explicit_store_identity(provider):
    provider.http._transport.side_effect = [tokens(), response({"response": {"shop_id": 42}})]
    result = provider.exchange_authorization_code(PAYLOAD)
    assert result["platform_store_records"][0]["platform_store_id"] == "42"
    provider.custody.store_secrets.assert_called_once()
    provider.custody.revoke.assert_not_called()


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("scope", [[42], ["42"], [99, 42]])
def test_token_shop_scope_proves_identity_when_shop_info_omits_id(provider, nested, scope):
    shop = {"shop_name": "Synthetic shop", "region": "PH", "status": "NORMAL"}
    provider.http._transport.side_effect = [response({
        "access_token": "FAKE_ACCESS", "refresh_token": "FAKE_REFRESH", "shop_id_list": scope,
    }), response({"response": shop} if nested else shop)]
    result = provider.exchange_authorization_code(PAYLOAD)
    assert result["platform_store_records"][0]["platform_store_id"] == "42"
    assert provider.http._transport.call_count == 2
    provider.custody.store_secrets.assert_called_once()
    provider.custody.revoke.assert_not_called()


@pytest.mark.parametrize("scope,shop", [
    ([42], {"shop_id": 99}), ([99], {"shop_id": 42}), ([], {"shop_id": 42}),
    ("42", {"shop_id": 42}), ([42, {}], {"shop_id": 42}),
    ([42], {}), ([42], {"request_id": "FAKE_REQUEST"}), ([42], {"region": "PH"}),
    ([42], {"response": []}),
    (None, {"shop_name": "Synthetic shop", "region": "PH"}),
])
def test_scope_cannot_override_conflicting_or_incomplete_identity(provider, scope, shop):
    provider.http._transport.side_effect = [response({
        "access_token": "FAKE_ACCESS", "refresh_token": "FAKE_REFRESH", "shop_id_list": scope,
    }), response(shop)]
    with pytest.raises(OAuthFlowError) as caught:
        provider.exchange_authorization_code(PAYLOAD)
    assert caught.value.stage == "verify_store"
    provider.custody.revoke.assert_called_once_with("fake-new-ref", "fake-new-token")
