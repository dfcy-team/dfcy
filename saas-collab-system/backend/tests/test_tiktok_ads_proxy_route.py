from urllib.parse import urlparse

from django.test import SimpleTestCase, override_settings

from apps.integrations.net_guard import _destination_https_proxy
from apps.integrations.oauth_errors import OAuthFlowError


@override_settings(LIVE_HTTPS_PROXY_URL="", LIVE_TIKTOK_TOKEN_PROXY_URL="http://127.0.0.1:17898",
                   LIVE_TIKTOK_ADS_PROXY_URL="http://127.0.0.1:17899")
class TikTokAdsProxyRouteTests(SimpleTestCase):
    def test_ads_auth_and_reads_use_dedicated_route(self):
        for path in ("oauth2/access_token/", "oauth2/advertiser/get/", "advertiser/info/", "report/integrated/get/",
                     "gmv_max/store/list/", "gmv_max/report/get/"):
            self.assertEqual(_destination_https_proxy(urlparse("https://business-api.tiktok.com/open_api/v1.3/" + path)),
                             ("127.0.0.1", 17899))

    def test_shop_route_is_preserved(self):
        self.assertEqual(_destination_https_proxy(urlparse("https://auth.tiktok-shops.com/api/v2/token/get")),
                         ("127.0.0.1", 17898))

    def test_other_paths_and_platforms_unchanged(self):
        for url in ("https://partner.shopeemobile.com/api/v2/auth/token/get", "https://auth.lazada.com/oauth/token",
                    "https://business-api.tiktok.com/open_api/v1.3/campaign/create/",
                    "https://business-api.tiktok.com/open_api/v1.3/file/video/ad/upload/",
                    "https://dingfengchuangyu.com/saas-tk-ads/receipt",
                    "https://business-api.tiktok.com:444/open_api/v1.3/advertiser/info/"):
            self.assertIsNone(_destination_https_proxy(urlparse(url)))

    @override_settings(LIVE_TIKTOK_ADS_PROXY_URL="http://192.168.2.10:1080")
    def test_non_loopback_proxy_fails_closed(self):
        with self.assertRaises(OAuthFlowError):
            _destination_https_proxy(urlparse("https://business-api.tiktok.com/open_api/v1.3/advertiser/info/"))

    @override_settings(LIVE_TIKTOK_ADS_PROXY_URL="")
    def test_default_configuration_is_unchanged(self):
        self.assertIsNone(_destination_https_proxy(urlparse("https://business-api.tiktok.com/open_api/v1.3/advertiser/info/")))
