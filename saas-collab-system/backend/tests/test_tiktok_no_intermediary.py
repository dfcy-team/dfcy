"""Verify actual connection targets with all legacy proxy settings populated."""
from unittest.mock import Mock
from urllib.parse import urlparse

import pytest
from django.test import override_settings

from apps.integrations import net_guard
from apps.integrations.oauth_errors import OAuthFlowError


@pytest.mark.parametrize("url", [
    "https://auth.tiktok-shops.com/api/v2/token/get",
    "https://auth.tiktok-shops.com/api/v2/token/refresh",
    "https://open-api.tiktokglobalshop.com/authorization/202309/shops",
    "https://open-api.tiktokglobalshop.com/order/202309/orders/search",
    "https://business-api.tiktok.com/open_api/v1.3/oauth2/access_token/",
    "https://business-api.tiktok.com/open_api/v1.3/report/integrated/get/",
    "https://business-api.tiktok.com/open_api/v1.3/gmv_max/report/get/",
])
def test_platform_connection_ignores_all_legacy_proxies(monkeypatch, url):
    connection = Mock()
    connection.sock = None
    response = Mock(status=200)
    response.read.return_value = b"{}"
    response.getheaders.return_value = []
    connection.getresponse.return_value = response
    factory = Mock(return_value=connection)
    monkeypatch.setattr(net_guard.http.client, "HTTPSConnection", factory)
    monkeypatch.setattr(net_guard, "_is_configured_custody_destination", lambda _: False)
    with override_settings(LIVE_HTTPS_PROXY_URL="http://127.0.0.1:17897",
                           LIVE_TIKTOK_TOKEN_PROXY_URL="http://127.0.0.1:17898",
                           LIVE_TIKTOK_ADS_PROXY_URL="http://127.0.0.1:17899"):
        net_guard._default_transport("GET", url)
    assert factory.call_args.args == (urlparse(url).hostname, 443)
    connection.set_tunnel.assert_not_called()
    connection.close.assert_called_once()


@pytest.mark.parametrize("url", [
    "http://business-api.tiktok.com/open_api/v1.3/report/integrated/get/",
    "https://user:placeholder@auth.tiktok-shops.com/api/v2/token/get",
    "https://open-api.tiktokglobalshop.com:444/orders",
    "https://business-api.tiktok.com/report#fragment",
])
def test_direct_transport_preserves_destination_validation(url):
    with pytest.raises(OAuthFlowError):
        net_guard._destination_https_proxy(urlparse(url))
