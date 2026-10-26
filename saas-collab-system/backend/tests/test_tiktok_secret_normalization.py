import hashlib
import hmac
from unittest.mock import Mock

import pytest

from apps.integrations.live_providers import TikTokLiveOAuthProvider, ShopeeLiveOAuthProvider
from apps.integrations.oauth_errors import OAuthFlowError


@pytest.mark.parametrize('secret', ['demo-secret', ' demo-secret ', '\tdemo-secret\r\n'])
def test_tiktok_custody_secret_has_canonical_signature(secret, monkeypatch):
    custody = Mock()
    custody.retrieve_secret.return_value = secret
    provider = TikTokLiveOAuthProvider({'app_id':'demo-app', 'app_secret_reference':'synthetic-ref'},
        custody=custody, http_client=Mock())
    monkeypatch.setattr('apps.integrations.live_providers.time.time', lambda: 1700000000)
    path = '/authorization/202309/shops'
    query = provider._signed_open_query(path)
    message = 'demo-secret' + path + 'app_keydemo-apptimestamp1700000000' + 'demo-secret'
    expected = hmac.new(b'demo-secret', message.encode(), hashlib.sha256).hexdigest()
    assert query['sign'] == expected
    assert provider._app_secret() == 'demo-secret'
    assert custody.retrieve_secret.return_value == secret
    provider.http.request.assert_not_called()


@pytest.mark.parametrize('secret', ['', ' ', '\r\n\t'])
def test_empty_tiktok_secret_fails_before_http(secret):
    custody = Mock()
    custody.retrieve_secret.return_value = secret
    provider = TikTokLiveOAuthProvider({'app_secret_reference':'synthetic-ref'}, custody=custody, http_client=Mock())
    with pytest.raises(OAuthFlowError):
        provider._app_secret()
    provider.http.request.assert_not_called()


def test_other_platform_secret_behavior_unchanged():
    custody = Mock()
    custody.retrieve_secret.return_value = ' demo-secret '
    provider = ShopeeLiveOAuthProvider({'app_secret_reference':'synthetic-ref'}, custody=custody, http_client=Mock())
    assert provider._app_secret() == ' demo-secret '
