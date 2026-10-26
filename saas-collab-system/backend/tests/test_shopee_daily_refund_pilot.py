from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

from django.utils import timezone

from apps.integrations.adapters import _shopee_refund_pilot_enabled
from apps.integrations import readonly_clients as clients
from apps.integrations.sync_services import _freeze_adapter_scope


def configured(monkeypatch):
    monkeypatch.setattr(clients, "get_runtime_platform_config", lambda platform: {})
    monkeypatch.setattr(clients, "get_runtime_setting", lambda *args, **kwargs: True)
    monkeypatch.setattr(clients, "is_module_enabled", lambda *args: True)
    monkeypatch.setattr(clients, "require_live_mode", lambda *args: None)
    config = SimpleNamespace(
        platform="shopee", environment="production", status="verified",
        platform_config={"partner_id": "123"}, network_enabled=True,
        sync_read_enabled=True, sync_write_enabled=False,
        credential_id="FAKE_REFERENCE", connect_timeout_seconds=1, read_timeout_seconds=1,
    )
    authorization = SimpleNamespace(
        status="active", Status=SimpleNamespace(ACTIVE="active"), token_id="FAKE_TOKEN",
        platform_store_id="456", expires_at=timezone.now() + timedelta(hours=1),
    )
    custody = Mock()
    custody.retrieve_secret.return_value = "FAKE_SECRET"
    custody.retrieve_access_token.return_value = "FAKE_ACCESS"
    return clients.ShopeeReadonlyClient(config, authorization, http_client=Mock(), custody=custody)


def test_daily_pilot_advances_pages_then_days_and_keeps_partial_final_day(monkeypatch):
    client = configured(monkeypatch)
    queries = []

    def request(path, query, **kwargs):
        queries.append(query)
        return {"response": {"return": [], "more": query["create_time_from"] == 1 and query["page_no"] == 0}}

    monkeypatch.setattr(client, "_refund_request", request)
    scope = {"time_from": 1, "time_to": 2 * 86400 + 123, "page_size": 100, "_refund_daily_pilot": True}
    cursor = ""
    for _ in range(4):
        page = client.fetch_returns(cursor, scope)
        cursor = page["next_cursor"]

    assert [(q["create_time_from"], q["create_time_to"], q["page_no"], q["page_size"]) for q in queries] == [
        (1, 86400, 0, 20), (1, 86400, 1, 20),
        (86401, 172800, 0, 20), (172801, 172923, 0, 20),
    ]
    assert cursor == ""


def test_daily_pilot_keeps_old_nonempty_cursor_on_old_strategy(monkeypatch):
    client = configured(monkeypatch)
    queries = []

    def request(path, query, **kwargs):
        queries.append(query)
        return {"response": {"return": [], "more": False}}

    monkeypatch.setattr(client, "_refund_request", request)
    scope = {"time_from": 1, "time_to": 15 * 86400, "page_size": 100, "_refund_daily_pilot": True}
    page = client.fetch_returns("7", scope)

    assert queries[0]["page_no"] == 7
    assert queries[0]["page_size"] == 100
    assert (queries[0]["create_time_from"], queries[0]["create_time_to"]) == (1, 15 * 86400)
    assert page["next_cursor"] == ""


def test_daily_pilot_preserves_full_fifteen_day_scope(monkeypatch):
    client = configured(monkeypatch)
    starts = []

    def request(path, query, **kwargs):
        starts.append((query["create_time_from"], query["create_time_to"]))
        return {"response": {"return": [], "more": False}}

    monkeypatch.setattr(client, "_refund_request", request)
    scope = {"time_from": 1, "time_to": 15 * 86400, "page_size": 100, "_refund_daily_pilot": True}
    cursor = ""
    while True:
        page = client.fetch_returns(cursor, scope)
        cursor = page["next_cursor"]
        if not cursor:
            break

    assert len(starts) == 15
    assert starts[0] == (1, 86400)
    assert starts[-1] == (14 * 86400 + 1, 15 * 86400)


def test_old_time_window_cursor_keeps_legacy_strategy(monkeypatch):
    client = configured(monkeypatch)
    queries = []

    def request(path, query, **kwargs):
        queries.append(query)
        return {"response": {"return": [], "more": True}}

    monkeypatch.setattr(client, "_refund_request", request)
    scope = {"time_from": 1, "time_to": 20 * 86400, "page_size": 100, "_refund_daily_pilot": True}
    page = client.fetch_returns("tw:1:7", scope)

    assert queries[0]["page_no"] == 7
    assert queries[0]["page_size"] == 100
    assert (queries[0]["create_time_from"], queries[0]["create_time_to"]) == (1, 15 * 86400)
    assert page["next_cursor"] == "tw:1:8"


def test_rd1_cursor_resumes_even_when_whitelist_flag_is_now_off(monkeypatch):
    client = configured(monkeypatch)
    queries = []

    def request(path, query, **kwargs):
        queries.append(query)
        return {"response": {"return": [], "more": False}}

    monkeypatch.setattr(client, "_refund_request", request)
    scope = {"time_from": 1, "time_to": 2 * 86400, "page_size": 100}
    fingerprint = __import__("hashlib").sha256(b"1:172800").hexdigest()[:12]
    page = client.fetch_returns(f"rd1:{fingerprint}:86401:0", scope)

    assert queries[0]["page_size"] == 20
    assert (queries[0]["create_time_from"], queries[0]["create_time_to"]) == (86401, 172800)
    assert page["next_cursor"] == ""


def test_history_details_ignore_daily_pilot(monkeypatch):
    client = configured(monkeypatch)
    queries = []

    def request(path, query, **kwargs):
        queries.append(query)
        return {"response": {"return": [], "more": False}}

    monkeypatch.setattr(client, "_refund_request", request)
    scope = {
        "time_from": 1, "time_to": 15 * 86400, "page_size": 73,
        "_refund_daily_pilot": True, "_history_details": True,
    }
    client.fetch_returns("", scope)

    assert queries[0]["page_size"] == 73
    assert (queries[0]["create_time_from"], queries[0]["create_time_to"]) == (1, 15 * 86400)


def test_job_allowlist_is_closed_and_limited_to_shopee_refunds():
    config = SimpleNamespace(platform="shopee")
    refund_job = SimpleNamespace(pk=26, resource_type="refund_return")
    order_job = SimpleNamespace(pk=26, resource_type="sales_order")
    other_platform = SimpleNamespace(platform="tiktok")

    assert not _shopee_refund_pilot_enabled(config, refund_job, ())
    assert _shopee_refund_pilot_enabled(config, refund_job, (26,))
    assert not _shopee_refund_pilot_enabled(config, order_job, (26,))
    assert not _shopee_refund_pilot_enabled(other_platform, refund_job, (26,))


def test_frozen_budget_scope_round_trips_daily_pilot_selector():
    frozen = _freeze_adapter_scope({
        "time_from": 1, "time_to": 15 * 86400, "page_size": 100,
        "_refund_daily_pilot": True, "secret_like_runtime_field": "discard",
    })

    assert frozen == {
        "time_from": 1, "time_to": 15 * 86400, "page_size": 100,
        "_refund_daily_pilot": True,
    }


