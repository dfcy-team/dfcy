from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

from platforms.tiktok.test_env import tts_client


def test_pilot_shop_uses_saas_without_local_refresh(monkeypatch):
    monkeypatch.setenv("TTS_SAAS_TOKEN_URL", "https://saas.example.test/api/internal-readonly/v1/tiktok-shop-token/")
    monkeypatch.setenv("TTS_SAAS_CLIENT_ID", "synthetic-client")
    monkeypatch.setenv("TTS_SAAS_CLIENT_SECRET", "synthetic-secret")
    monkeypatch.setenv("TTS_SHOP_CIPHER", "cipher-TK1PH")
    monkeypatch.delenv("TTS_SAAS_SHOP_CODE", raising=False)
    config = Path("config_TK1PH.env")
    monkeypatch.setattr(tts_client, "_shop_config_path", lambda path=None: config)
    response = Mock()
    response.json.return_value = {
        "success": True,
        "data": {
            "store_code": "TK1PH", "app_key": "public-app-key", "shop_cipher": "cipher-TK1PH",
            "access_token": "synthetic-access",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        },
    }
    get = Mock(return_value=response)
    monkeypatch.setattr(tts_client.requests, "get", get)
    client = tts_client.TikTokShopClient("public-app-key", "synthetic-app-secret")
    client.token_refresh = Mock()

    assert tts_client.get_shop_token(client, config) == "synthetic-access"
    assert client.access_token == "synthetic-access"
    assert tts_client.refresh_shop_token(client, config, quiet=True) is None
    client.token_refresh.assert_not_called()
    assert get.call_args.kwargs["auth"] == ("synthetic-client", "synthetic-secret")


def test_wrong_shop_response_does_not_fall_back(monkeypatch):
    monkeypatch.setenv("TTS_SAAS_TOKEN_URL", "https://saas.example.test/token/")
    monkeypatch.setenv("TTS_SAAS_CLIENT_ID", "synthetic-client")
    monkeypatch.setenv("TTS_SAAS_CLIENT_SECRET", "synthetic-secret")
    monkeypatch.setenv("TTS_SHOP_CIPHER", "cipher-TKKJ1PH")
    monkeypatch.delenv("TTS_SAAS_SHOP_CODE", raising=False)
    monkeypatch.setattr(tts_client, "_shop_config_path", lambda path=None: Path("config_TKKJ1PH.env"))
    response = Mock()
    response.json.return_value = {
        "success": True,
        "data": {"store_code": "TK1PH", "app_key": "public-app-key", "shop_cipher": "cipher-TK1PH",
                 "access_token": "wrong-shop-token", "expires_at": "2099-01-01T00:00:00+00:00"},
    }
    monkeypatch.setattr(tts_client.requests, "get", Mock(return_value=response))
    client = tts_client.TikTokShopClient("public-app-key", "synthetic-app-secret")
    client.token_refresh = Mock()

    assert tts_client.get_shop_token(client) is None
    client.token_refresh.assert_not_called()
    assert client.access_token == ""


def test_wrong_cipher_does_not_accept_saas_token(monkeypatch):
    monkeypatch.setenv("TTS_SAAS_TOKEN_URL", "https://saas.example.test/token/")
    monkeypatch.setenv("TTS_SAAS_CLIENT_ID", "synthetic-client")
    monkeypatch.setenv("TTS_SAAS_CLIENT_SECRET", "synthetic-secret")
    monkeypatch.setenv("TTS_SHOP_CIPHER", "local-other-shop")
    monkeypatch.delenv("TTS_SAAS_SHOP_CODE", raising=False)
    monkeypatch.setattr(tts_client, "_shop_config_path", lambda path=None: Path("config_TK1PH.env"))
    response = Mock()
    response.json.return_value = {
        "success": True,
        "data": {"store_code": "TK1PH", "app_key": "public-app-key", "shop_cipher": "saas-pilot-shop",
                 "access_token": "wrong-cipher-token", "expires_at": "2099-01-01T00:00:00+00:00"},
    }
    monkeypatch.setattr(tts_client.requests, "get", Mock(return_value=response))
    client = tts_client.TikTokShopClient("public-app-key", "synthetic-app-secret")
    assert tts_client.get_shop_token(client) is None
    assert client.access_token == ""


def test_pilot_shop_rejects_direct_local_refresh_and_exchange(monkeypatch):
    monkeypatch.delenv("TTS_SAAS_SHOP_CODE", raising=False)
    monkeypatch.setattr(tts_client, "_shop_config_path", lambda path=None: Path("config_TKKJ1PH.env"))
    get = Mock()
    monkeypatch.setattr(tts_client.requests, "get", get)
    client = tts_client.TikTokShopClient("public-app-key", "synthetic-app-secret")

    with pytest.raises(RuntimeError, match="SaaS"):
        client.token_refresh("old-refresh-token")
    with pytest.raises(RuntimeError, match="SaaS"):
        client.token_by_code("old-auth-code")
    get.assert_not_called()


def test_explicit_pilot_shop_must_match_config_file(monkeypatch):
    monkeypatch.setenv("TTS_SAAS_SHOP_CODE", "TK1PH")
    with pytest.raises(RuntimeError, match="不一致"):
        tts_client._saas_pilot_shop(Path("config_TK2PH.env"))


def test_expired_pilot_token_refetches_from_saas_only(monkeypatch):
    monkeypatch.delenv("TTS_SAAS_SHOP_CODE", raising=False)
    client = tts_client.TikTokShopClient("public-app-key", "synthetic-app-secret")
    client.config_path = Path("config_TK1PH.env")
    broker = Mock(return_value="new-synthetic-access")
    monkeypatch.setattr(tts_client, "_saas_shop_token", broker)
    client.token_refresh = Mock()

    assert client._retry_after_refresh({"code": 105002}, "old-synthetic-access") == "new-synthetic-access"
    broker.assert_called_once_with(client, "TK1PH")
    client.token_refresh.assert_not_called()


def test_unmanaged_direct_reader_keeps_existing_token_behavior(monkeypatch):
    monkeypatch.delenv("TTS_SAAS_SHOP_CODE", raising=False)
    monkeypatch.setenv("TTS_ACCESS_TOKEN", "existing-local-access")
    monkeypatch.setenv("TTS_REFRESH_TOKEN", "existing-local-refresh")
    monkeypatch.setattr(tts_client, "_shop_config_path", lambda path=None: Path("config_TK2PH.env"))
    get = Mock()
    monkeypatch.setattr(tts_client.requests, "get", get)
    client = tts_client.TikTokShopClient("public-app-key", "synthetic-app-secret")
    client.token_refresh = Mock()

    assert tts_client.get_shop_token(client, refresh_unmanaged=False) == "existing-local-access"
    assert client.config_path is None
    client.token_refresh.assert_not_called()
    get.assert_not_called()
