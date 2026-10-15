from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.integrations.adapters import ProductionReadonlyAdapter
from apps.integrations import readonly_clients as clients


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


def test_history_returns_resume_details_in_four_item_slices(monkeypatch):
    client = configured(monkeypatch)
    list_queries = []
    detail_ids = []

    def request(path, query):
        if path == client.RETURN_LIST_PATH:
            list_queries.append(query)
            return {"response": {
                "return": [{"return_sn": f"r{i}", "status": "COMPLETED", "customer_name": "omit"} for i in range(9)],
                "more": True,
            }}
        detail_ids.append(query["return_sn"])
        return {"response": {"refund_id": f"refund-{query['return_sn']}"}}

    monkeypatch.setattr(client, "_request", request)
    base_scope = {"time_from": 1, "time_to": 2, "page_size": 20, "_history_details": True}
    cursor = ""
    state = {}
    records = []
    while True:
        scope = {**base_scope, "_detail_state": state}
        page = client.fetch_returns(cursor, scope)
        records.extend(page["records"])
        cursor, state = page["next_cursor"], page["detail_state"]
        if not state:
            break

    assert [query["page_size"] for query in list_queries] == [20]
    assert len(list_queries) == 1
    assert detail_ids == [f"r{i}" for i in range(9)]
    assert [record["return_sn"] for record in records] == [f"r{i}" for i in range(9)]
    assert len({record["return_sn"] for record in records}) == 9
    assert cursor == "1"
    assert all("customer_name" not in summary for summary in page["detail_state"].get("summaries", []))


def test_history_failed_detail_slice_does_not_advance_checkpoint(monkeypatch):
    client = configured(monkeypatch)
    list_calls = []
    detail_calls = []

    def request(path, query):
        if path == client.FINANCE_LIST_PATH:
            list_calls.append(query)
            return {"response": {"order_income_list": [{"order_sn": f"o{i}"} for i in range(6)], "more": True}}
        detail_calls.append(query["order_sn"])
        if query["order_sn"] == "o2" and detail_calls.count("o2") == 1:
            raise RuntimeError("temporary")
        return {"response": {"order_income": {"escrow_amount": 1, "currency": "USD"}}}

    monkeypatch.setattr(client, "_request", request)
    scope = {"time_from": 1, "time_to": 2, "page_size": 50, "_history_details": True}
    with pytest.raises(RuntimeError):
        client.fetch_finance_transactions("", {**scope, "_detail_state": {}})
    first_slice_calls = len(detail_calls)
    page = client.fetch_finance_transactions("", {**scope, "_detail_state": {}})

    assert 1 <= first_slice_calls <= 4
    assert page["detail_progress"]["requests_in_slice"] == 4
    assert len(list_calls) == 2  # The failed, uncommitted slice may be retried from its list page.
    assert [query["page_size"] for query in list_calls] == [50, 50]
    assert len(page["records"]) == 4


def test_history_finance_finishes_frozen_page_without_relisting(monkeypatch):
    client = configured(monkeypatch)
    list_queries = []
    detail_ids = []

    def request(path, query):
        if path == client.FINANCE_LIST_PATH:
            list_queries.append(query)
            return {"response": {
                "order_income_list": [{"order_sn": f"o{i}", "currency": "USD"} for i in range(5)],
                "more": True,
            }}
        detail_ids.append(query["order_sn"])
        return {"response": {"order_income": {"escrow_amount": "1.25", "currency": "USD"}}}

    monkeypatch.setattr(client, "_request", request)
    base_scope = {"time_from": 1, "time_to": 2, "page_size": 50, "_history_details": True}
    cursor = ""
    state = {}
    records = []
    while True:
        page = client.fetch_finance_transactions(cursor, {**base_scope, "_detail_state": state})
        records.extend(page["records"])
        cursor, state = page["next_cursor"], page["detail_state"]
        if not state:
            break

    assert len(list_queries) == 1
    assert list_queries[0]["page_size"] == 50
    assert detail_ids == [f"o{i}" for i in range(5)]
    assert [record["order_id"] for record in records] == [f"o{i}" for i in range(5)]
    assert cursor == "2"


def test_adapter_continues_through_detail_slices_and_provider_page_boundary(monkeypatch):
    client = configured(monkeypatch)
    adapter = object.__new__(ProductionReadonlyAdapter)
    list_pages = []
    detail_ids = []

    def request(path, query):
        if path == client.RETURN_LIST_PATH:
            list_pages.append(query["page_no"])
            if query["page_no"] == 0:
                return {"response": {"return": [{"return_sn": f"r{i}"} for i in range(5)], "more": True}}
            return {"response": {"return": [], "more": False}}
        detail_ids.append(query["return_sn"])
        return {"response": {"status": "COMPLETED"}}

    monkeypatch.setattr(client, "_request", request)
    base_scope = {"time_from": 1, "time_to": 2, "page_size": 10, "_history_details": True}
    cursor, state = "", {}
    page = client.fetch_returns(cursor, {**base_scope, "_detail_state": state})
    assert adapter.should_continue(page, 0)
    assert page["next_cursor"] != cursor and len(page["next_cursor"]) < 255
    cursor, state = page["next_cursor"], page["detail_state"]
    with pytest.raises(ValidationError):
        client.fetch_returns(cursor.rsplit(":", 1)[0] + ":5", {**base_scope, "_detail_state": state})
    page = client.fetch_returns(cursor, {**base_scope, "_detail_state": state})
    assert adapter.should_continue(page, cursor)
    assert not page["detail_state"]
    cursor = page["next_cursor"]
    empty_page = client.fetch_returns(cursor, {**base_scope, "_detail_state": {}})
    assert not adapter.should_continue(empty_page, cursor)
    assert list_pages == [0, 1]
    assert detail_ids == [f"r{i}" for i in range(5)]


def test_detail_checkpoint_is_not_mutated_when_next_slice_fails(monkeypatch):
    client = configured(monkeypatch)
    fail = False
    detail_ids = []

    def request(path, query):
        nonlocal fail
        if path == client.RETURN_LIST_PATH:
            return {"response": {"return": [{"return_sn": f"r{i}"} for i in range(9)]}}
        return_id = query["return_sn"]
        detail_ids.append(return_id)
        if fail and return_id == "r4":
            raise RuntimeError("temporary")
        return {"response": {"status": "COMPLETED"}}

    monkeypatch.setattr(client, "_request", request)
    base_scope = {"time_from": 1, "time_to": 2, "page_size": 10, "_history_details": True}
    first = client.fetch_returns("", {**base_scope, "_detail_state": {}})
    saved_state = first["detail_state"]
    state_before_failure = {**saved_state, "summaries": [dict(item) for item in saved_state["summaries"]]}
    fail = True
    with pytest.raises(RuntimeError):
        client.fetch_returns(first["next_cursor"], {**base_scope, "_detail_state": saved_state})
    assert saved_state == state_before_failure
    fail = False
    resumed = client.fetch_returns(first["next_cursor"], {**base_scope, "_detail_state": saved_state})
    assert [record["return_sn"] for record in first["records"]] == [f"r{i}" for i in range(4)]
    assert [record["return_sn"] for record in resumed["records"]] == [f"r{i}" for i in range(4, 8)]
    assert saved_state == state_before_failure
    assert detail_ids.count("r0") == 1 and detail_ids.count("r4") == 2


def test_checkpoint_rejects_unapproved_nested_summary_fields(monkeypatch):
    client = configured(monkeypatch)
    monkeypatch.setattr(client, "_request", lambda path, query: {
        "response": {"return": [{"return_sn": "r1"}, {"return_sn": "r2"}, {"return_sn": "r3"}, {"return_sn": "r4"}, {"return_sn": "r5"}]}
    } if path == client.RETURN_LIST_PATH else {"response": {"status": "COMPLETED"}})
    scope = {"time_from": 1, "time_to": 2, "page_size": 10, "_history_details": True, "_detail_state": {}}
    page = client.fetch_returns("", scope)
    damaged = {**page["detail_state"], "summaries": [dict(item) for item in page["detail_state"]["summaries"]]}
    damaged["summaries"][4]["customer_name"] = "private"
    with pytest.raises(ValidationError):
        client.fetch_returns(page["next_cursor"], {**scope, "_detail_state": damaged})


@pytest.mark.parametrize("state,scope", [
    ({"broken": True}, {"time_from": 1, "time_to": 2, "page_size": 10}),
    ({"version": 1, "resource": "returns", "scope": "wrong", "page_cursor": "", "summaries": [],
      "next_index": 0, "next_cursor": "", "has_more": False},
     {"time_from": 1, "time_to": 2, "page_size": 10}),
])
def test_corrupt_or_mismatched_checkpoint_is_rejected(monkeypatch, state, scope):
    client = configured(monkeypatch)
    request = Mock()
    monkeypatch.setattr(client, "_request", request)
    with pytest.raises(ValidationError):
        client.fetch_returns("", {**scope, "_history_details": True, "_detail_state": state})
    request.assert_not_called()


def test_empty_history_page_preserves_fifteen_day_window_cursor(monkeypatch):
    client = configured(monkeypatch)
    queries = []

    def request(path, query):
        queries.append(query)
        return {"response": {"return": [], "more": False}}

    monkeypatch.setattr(client, "_request", request)
    page = client.fetch_returns("", {
        "time_from": 1, "time_to": 16 * 86400, "page_size": 20,
        "_history_details": True, "_detail_state": {},
    })

    assert queries[0]["page_no"] == 0
    assert page["records"] == []
    assert page["detail_state"] == {}
    assert page["next_cursor"] == f"tw:{15 * 86400 + 1}:"
