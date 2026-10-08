from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rest_framework.exceptions import ValidationError

from apps.integrations.readonly_clients import TikTokReadonlyClient


def _client(search_orders, detail_orders):
    client = object.__new__(TikTokReadonlyClient)
    client.authorization = SimpleNamespace(shop_cipher="approved-cipher")
    client._runtime_path = Mock(side_effect=lambda _name, fallback: fallback)
    client._request = Mock(side_effect=[
        {"data": {"orders": search_orders, "next_page_token": "next-page"}},
        {"data": {"orders": detail_orders}},
    ])
    return client


@pytest.mark.parametrize("details", [
    [{"id": "order-1"}],
    [{"id": "order-1"}, {"id": "order-1"}],
    [{"id": "order-1"}, {"id": "wrong-order"}],
    [{"id": "order-1"}, {}],
])
def test_incomplete_order_detail_fails_before_cursor_is_returned(details):
    client = _client([{"id": "order-1"}, {"id": "order-2"}], details)
    with pytest.raises(ValidationError, match="order detail"):
        client.fetch_orders("", {"time_from": 100, "time_to": 200, "page_size": 100, "time_basis": "created"})


def test_complete_order_detail_returns_exact_records_and_cursor():
    details = [{"id": "order-2"}, {"id": "order-1"}]
    client = _client([{"id": "order-1"}, {"id": "order-2"}], details)
    result = client.fetch_orders("", {"time_from": 100, "time_to": 200, "page_size": 100, "time_basis": "created"})
    assert result["records"] == details
    assert result["next_cursor"] == "next-page"
