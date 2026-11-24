from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from apps.integrations.oauth_errors import OAUTH_RATE_LIMITED, OAuthFlowError
from apps.integrations.readonly_clients import TikTokReadonlyClient


def test_creator_search_first_page_and_shared_backoff():
    request = Mock(return_value={"data": {"creators": [{"username": "sample"}]}})
    client = SimpleNamespace(http=SimpleNamespace(max_retries=3), _request=request,
                             authorization=SimpleNamespace(shop_cipher="shop-one", scopes=["creator.read"]))
    search = TikTokReadonlyClient.search_marketplace_creator_handle
    broker = Mock()
    broker.ttl.return_value = -2
    runtime = {"affiliate_seller_creator_read_approved": True, "affiliate_seller_creator_scope": "creator.read"}
    with patch("redis.Redis.from_url", return_value=broker), patch(
        "apps.integrations.readonly_clients.get_runtime_platform_config", return_value=runtime
    ):
        assert search(client, "sample") == [{"username": "sample"}]
        request.assert_called_once_with("/affiliate_seller/202508/marketplace_creators/search", method="POST",
                                        query={"shop_cipher": "shop-one", "page_size": 12},
                                        body={"keyword": "sample"})
        assert client.http.max_retries == 0
        request.side_effect = OAuthFlowError(OAUTH_RATE_LIMITED)
        with pytest.raises(OAuthFlowError):
            search(client, "sample")
        broker.eval.assert_called_once()
        broker.ttl.return_value = 280
        client.authorization.shop_cipher = "shop-two"
        with pytest.raises(OAuthFlowError) as caught:
            search(client, "another")
        assert caught.value.retry_after == 280
        assert request.call_count == 2
