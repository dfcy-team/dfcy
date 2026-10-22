from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.utils import timezone

from apps.integrations import readonly_clients as clients
from apps.integrations.oauth_errors import OAUTH_PROVIDER_UNAVAILABLE, OAuthFlowError


def configured(monkeypatch):
    monkeypatch.setattr(clients, "get_runtime_platform_config", lambda platform: {})
    monkeypatch.setattr(clients, "get_runtime_setting", lambda *args, **kwargs: True)
    monkeypatch.setattr(clients, "is_module_enabled", lambda *args: True)
    monkeypatch.setattr(clients, "require_live_mode", lambda *args: None)
    config = SimpleNamespace(
        platform="shopee", environment="production", status="verified",
        platform_config={"partner_id": "123"}, network_enabled=True, sync_read_enabled=True,
        sync_write_enabled=False, credential_id="FAKE_REFERENCE", connect_timeout_seconds=1,
        read_timeout_seconds=1,
    )
    authorization = SimpleNamespace(
        status="active", Status=SimpleNamespace(ACTIVE="active"), token_id="FAKE_TOKEN_REFERENCE",
        platform_store_id="456", expires_at=timezone.now() + timedelta(hours=1),
    )
    return clients.ShopeeReadonlyClient(config, authorization, http_client=Mock(), custody=Mock())


def test_refund_list_failure_has_safe_diagnostics_and_preserves_retry_metadata(monkeypatch):
    client = configured(monkeypatch)
    secret = "buyer@example.test return-sn=private-return token=private-token"
    original = OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, secret)
    original.category = "timeout_uncertain"
    original_codes = original.get_codes()
    original_full_details = original.get_full_details()

    def request(path, query):
        assert path == client.RETURN_LIST_PATH
        assert query["page_no"] == 0
        assert query["page_size"] == 40
        raise original

    monkeypatch.setattr(client, "_request", request)
    with pytest.raises(OAuthFlowError) as raised:
        client.fetch_returns("", {"time_from": 1, "time_to": 2, "page_size": 40})

    assert raised.value is original
    assert raised.value.controlled_code == OAUTH_PROVIDER_UNAVAILABLE
    assert raised.value.category == "timeout_uncertain"
    message = str(raised.value)
    assert "Shopee refund request timed out" in message
    assert "stage=list" in message
    assert "page_no=0" in message
    assert "page_size=40" in message
    assert "elapsed_ms=" in message
    assert all(value not in message for value in ("buyer@example.test", "private-return", "private-token"))
    assert raised.value.get_codes() == original_codes
    assert raised.value.get_full_details() == {
        "message": message,
        "code": original_full_details["code"],
    }


def test_refund_detail_failure_has_safe_diagnostics_and_preserves_retry_metadata(monkeypatch):
    client = configured(monkeypatch)
    secret_return_id = "buyer@example.test-private-return"
    unsafe_category = "sensitive-category-buyer@example.test"
    original = OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, f"timeout for {secret_return_id}; token=private-token")
    original.category = unsafe_category

    def request(path, query):
        if path == client.RETURN_LIST_PATH:
            return {"response": {"return": [{"return_sn": secret_return_id}], "more": False}}
        assert path == client.RETURN_DETAIL_PATH
        assert query == {"return_sn": secret_return_id}
        raise original

    monkeypatch.setattr(client, "_request", request)
    with pytest.raises(OAuthFlowError) as raised:
        client.fetch_returns("", {"time_from": 1, "time_to": 2, "page_size": 25})

    assert raised.value is original
    assert raised.value.controlled_code == OAUTH_PROVIDER_UNAVAILABLE
    assert raised.value.category == unsafe_category
    message = str(raised.value)
    assert message.startswith(f"{OAUTH_PROVIDER_UNAVAILABLE}: Shopee refund request failed;")
    assert "stage=detail" in message
    assert "page_no=0" in message
    assert "page_size=25" in message
    assert "elapsed_ms=" in message
    assert all(value not in message for value in ("buyer@example.test", secret_return_id, "private-token", unsafe_category))


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("tls_failure", "Shopee refund request failed during TLS setup"),
        ("network_uncertain", "Shopee refund request failed due to a network issue"),
    ],
)
def test_refund_diagnostics_use_fixed_category_phrases(monkeypatch, category, expected):
    client = configured(monkeypatch)
    original = OAuthFlowError(OAUTH_PROVIDER_UNAVAILABLE, "sensitive provider text")
    original.category = category

    monkeypatch.setattr(client, "_request", Mock(side_effect=original))
    with pytest.raises(OAuthFlowError) as raised:
        client.fetch_returns("", {"time_from": 1, "time_to": 2, "page_size": 5})

    assert raised.value is original
    assert expected in str(raised.value)
    assert category not in str(raised.value)
    assert "sensitive provider text" not in str(raised.value)


def test_successful_refund_list_and_detail_response_is_unchanged(monkeypatch):
    client = configured(monkeypatch)
    requests = []

    def request(path, query):
        requests.append((path, query))
        if path == client.RETURN_LIST_PATH:
            return {"response": {"return": [{"return_sn": "safe-id"}], "more": True}}
        return {"response": {"refund_id": "refund-id"}}

    monkeypatch.setattr(client, "_request", request)
    page = client.fetch_returns("", {"time_from": 1, "time_to": 2, "page_size": 10})

    assert page == {
        "records": [{"return_sn": "safe-id", "refund_id": "refund-id"}],
        "next_cursor": "1",
        "raw_responses": [
            {"endpoint": client.RETURN_LIST_PATH, "payload": {"response": {"return": [{"return_sn": "safe-id"}], "more": True}}},
            {"endpoint": client.RETURN_DETAIL_PATH, "payload": {"response": {"refund_id": "refund-id"}}},
        ],
    }
    assert requests[0][1]["page_no"] == 0
    assert requests[0][1]["page_size"] == 10
