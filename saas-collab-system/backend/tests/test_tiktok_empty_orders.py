from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rest_framework.exceptions import ValidationError

from apps.integrations.readonly_clients import TikTokReadonlyClient, _tiktok_explicit_empty_orders


@pytest.mark.parametrize("token", [None, ""])
def test_explicit_empty_order_response_accepts_only_documented_zero_shape(token):
    payload = {"code": 0, "data": {"total_count": 0, "next_page_token": token}}

    assert _tiktok_explicit_empty_orders(payload, payload["data"])


@pytest.mark.parametrize("payload,data", [
    ({"data": {"total_count": 0, "next_page_token": ""}}, {"total_count": 0, "next_page_token": ""}),
    ({"code": False, "data": {"total_count": 0, "next_page_token": ""}}, {"total_count": 0, "next_page_token": ""}),
    ({"code": "0", "data": {"total_count": 0, "next_page_token": ""}}, {"total_count": 0, "next_page_token": ""}),
    ({"code": 1, "data": {"total_count": 0, "next_page_token": ""}}, {"total_count": 0, "next_page_token": ""}),
    ({"code": 0, "data": {"next_page_token": ""}}, {"next_page_token": ""}),
    ({"code": 0, "data": {"total_count": False, "next_page_token": ""}}, {"total_count": False, "next_page_token": ""}),
    ({"code": 0, "data": {"total_count": "0", "next_page_token": ""}}, {"total_count": "0", "next_page_token": ""}),
    ({"code": 0, "data": {"total_count": 0}}, {"total_count": 0}),
    ({"code": 0, "data": {"total_count": 0, "next_page_token": "next"}}, {"total_count": 0, "next_page_token": "next"}),
    ({"code": 0, "data": {"total_count": 0, "next_page_token": "", "orders": []}}, {"total_count": 0, "next_page_token": "", "orders": []}),
    ({"code": 0, "data": {"total_count": 0, "next_page_token": "", "orders": None}}, {"total_count": 0, "next_page_token": "", "orders": None}),
])
def test_other_order_response_shapes_are_not_explicit_empty(payload, data):
    assert not _tiktok_explicit_empty_orders(payload, data)


@pytest.mark.parametrize("token", [None, ""])
def test_fetch_orders_accepts_explicit_empty_page_without_detail_request(token):
    client = object.__new__(TikTokReadonlyClient)
    client.authorization = SimpleNamespace(shop_cipher="approved-cipher")
    client._runtime_path = Mock(side_effect=lambda _name, fallback: fallback)
    payload = {"code": 0, "data": {"total_count": 0, "next_page_token": token}}
    client._request = Mock(return_value=payload)

    result = client.fetch_orders("", {"time_from": 100, "time_to": 200, "page_size": 100, "time_basis": "created"})

    assert result["records"] == []
    assert result["next_cursor"] == ""
    assert result["raw_responses"] == [{"endpoint": client.ORDER_LIST_PATH, "payload": payload}]
    client._request.assert_called_once()


@pytest.mark.parametrize("data", [
    {"total_count": 0},
    {"total_count": False, "next_page_token": ""},
    {"total_count": 0, "next_page_token": "", "orders": None},
])
def test_fetch_orders_keeps_rejecting_malformed_empty_page(data):
    client = object.__new__(TikTokReadonlyClient)
    client.authorization = SimpleNamespace(shop_cipher="approved-cipher")
    client._runtime_path = Mock(side_effect=lambda _name, fallback: fallback)
    client._request = Mock(return_value={"code": 0, "data": data})

    with pytest.raises(ValidationError, match="missing data.orders"):
        client.fetch_orders("", {"time_from": 100, "time_to": 200, "page_size": 100, "time_basis": "created"})
