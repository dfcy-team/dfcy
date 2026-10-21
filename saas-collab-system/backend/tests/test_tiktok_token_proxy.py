"""Synthetic routing and outage tests: never open real proxy/platform connections."""
from unittest.mock import Mock
from urllib.parse import urlparse

import pytest
from django.test import override_settings

from apps.integrations import net_guard
from apps.integrations.oauth_errors import OAuthFlowError

PROXY = "http://127.0.0.1:17898"


@pytest.mark.parametrize("path", ["/api/v2/token/get", "/api/v2/token/refresh"])
def test_tiktok_token_paths_ignore_legacy_proxy(path):
    with override_settings(LIVE_TIKTOK_TOKEN_PROXY_URL=PROXY, LIVE_HTTPS_PROXY_URL="http://127.0.0.1:17897"):
        assert net_guard._destination_https_proxy(urlparse("https://auth.tiktok-shops.com" + path + "?auth_code=FAKE")) is None


@pytest.mark.parametrize("url", [
    "https://partner.shopeemobile.com/api/v2/auth/token/get",
    "https://auth.lazada.com/rest/auth/token/create",
    "https://wms.example.test/api", "https://foreign.example.test/api/v2/token/get",
])
def test_other_routes_keep_the_existing_proxy_selection(url):
    with override_settings(LIVE_TIKTOK_TOKEN_PROXY_URL=PROXY, LIVE_HTTPS_PROXY_URL="http://127.0.0.1:17897"):
        assert net_guard._destination_https_proxy(urlparse(url)) == ("127.0.0.1",17897)


def test_blank_dedicated_setting_preserves_the_existing_route():
    with override_settings(LIVE_TIKTOK_TOKEN_PROXY_URL="", LIVE_HTTPS_PROXY_URL=""):
        assert net_guard._destination_https_proxy(urlparse("https://auth.tiktok-shops.com/api/v2/token/get")) is None


@pytest.mark.parametrize("proxy", ["http://foreign.example.test:17898", "https://127.0.0.1:17898",
    "http://user:FAKE@127.0.0.1:17898", "http://127.0.0.1:0", "http://127.0.0.1:17898/path"])
def test_invalid_legacy_proxy_cannot_intercept_direct_requests(proxy):
    with override_settings(LIVE_TIKTOK_TOKEN_PROXY_URL=proxy, LIVE_HTTPS_PROXY_URL="http://127.0.0.1:17897"):
        assert net_guard._destination_https_proxy(urlparse("https://auth.tiktok-shops.com/api/v2/token/get")) is None
        assert net_guard._destination_https_proxy(urlparse("https://partner.shopeemobile.com/api")) == ("127.0.0.1",17897)


@pytest.mark.parametrize("suffix", ["#fragment", ";params", "?auth_code=FAKE#fragment"])
def test_target_fragments_or_path_parameters_are_rejected(suffix):
    with override_settings(LIVE_TIKTOK_TOKEN_PROXY_URL=PROXY):
        with pytest.raises(OAuthFlowError):
            net_guard._destination_https_proxy(urlparse("https://auth.tiktok-shops.com/api/v2/token/get" + suffix))


def test_custody_stays_direct_even_with_invalid_dedicated_proxy(monkeypatch):
    connection = Mock()
    connection.sock = None
    response = Mock(status=200)
    response.read.return_value = b"{}"
    response.getheaders.return_value = []
    connection.getresponse.return_value = response
    factory = Mock(return_value=connection)
    monkeypatch.setattr(net_guard.http.client, "HTTPSConnection", factory)
    monkeypatch.setattr(net_guard, "_is_configured_custody_destination", lambda _parsed: True)
    monkeypatch.setattr(net_guard, "_validated_custody_ca_file", lambda: "")
    with override_settings(LIVE_TIKTOK_TOKEN_PROXY_URL="INVALID", LIVE_HTTPS_PROXY_URL="INVALID"):
        net_guard._default_transport("GET", "https://custody.example.test/api")
    assert factory.call_args.args == ("custody.example.test",443)
    connection.set_tunnel.assert_not_called()


def test_direct_disconnect_has_no_proxy_fallback_or_extra_attempt(monkeypatch):
    connection = Mock()
    connection.request.side_effect = TimeoutError()
    factory = Mock(return_value=connection)
    monkeypatch.setattr(net_guard.http.client, "HTTPSConnection", factory)
    monkeypatch.setattr(net_guard, "_is_configured_custody_destination", lambda _parsed: False)
    monkeypatch.setattr(net_guard, "assert_host_allowed", lambda _url: None)
    with override_settings(LIVE_TIKTOK_TOKEN_PROXY_URL=PROXY, LIVE_HTTPS_PROXY_URL="http://127.0.0.1:17897"):
        with pytest.raises(OAuthFlowError) as caught:
            net_guard.PlatformHttpClient().request("GET", "https://auth.tiktok-shops.com/api/v2/token/get?auth_code=FAKE",retry=False)
    assert caught.value.category == "timeout_uncertain"
    assert factory.call_count == 1 and factory.call_args.args == ("auth.tiktok-shops.com",443)
    connection.set_tunnel.assert_not_called()
    connection.close.assert_called_once()
