"""TK-only fail-closed boundaries, with synthetic provider payloads."""

from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError

from apps.integrations.adapters import MarketplaceFinanceTransactionAdapter
from apps.integrations.readonly_clients import TikTokReadonlyClient
from apps.integrations.tiktok_ads_pilot import _parse_campaign_page
from apps.integrations.tiktok_finance_fields import amount


def client_for(statement_data=None, details=None):
    client = TikTokReadonlyClient(SimpleNamespace(platform="tiktok", platform_config={}),
        authorization=SimpleNamespace(shop_cipher="synthetic"), custody=object())
    client._runtime_path = lambda _key, fallback: fallback
    client._request = Mock(side_effect=[{"data": {"statements": [{"id": "S"}]} if statement_data is None else statement_data},
        *(details if details is not None else [{"data": {"transactions": [transaction()]}}])])
    return client


def transaction(**changes):
    return {"id": "T", "settlement_amount": "7.0001", "currency": "PHP", "create_time": 12, **changes}


def fetch(client):
    return client.fetch_finance_transactions("", {"time_from": 1, "time_to": 20, "page_size": 100})


@pytest.mark.parametrize("value", [None, "", True, False, 0.1, "NaN", "Infinity", "-Infinity", "x",
    "10000000000000000", "-10000000000000000", "1.00001", {}, {"amount": None},
    {"amount": "1", "currency": "USD"}])
def test_finance_invalid_amount_never_defaults_to_zero(value):
    with pytest.raises(ValidationError):
        amount(value, "PHP")


@pytest.mark.parametrize("value, expected", [("0", "0"), (0, "0"), ("-2.1234", "-2.1234"),
    ("9999999999999999.9999", "9999999999999999.9999"),
    ({"amount": "1.20", "currency": "PHP"}, "1.20")])
def test_finance_exact_signed_money_and_explicit_zero(value, expected):
    assert amount(value, "PHP") == expected


@pytest.mark.parametrize("data", [{}, {"statements": None}, {"statements": {}},
    {"statements": [None]}, {"statements": [{}]}, {"statements": [{"id": "S"}, {"id": "S"}]},
    {"statements": [], "next_page_token": "next"}])
def test_invalid_statement_structure_is_not_successful_empty_page(data):
    with pytest.raises(ValidationError):
        fetch(client_for(statement_data=data))


@pytest.mark.parametrize("data", [{}, {"transactions": None}, {"transactions": {}},
    {"transactions": [None]}, {"transactions": [{}]},
    {"transactions": [transaction(), transaction()]},
    {"transactions": [], "next_page_token": "next"},
    {"transactions": [transaction()], "next_page_token": False}])
def test_invalid_transactions_are_not_silently_skipped(data):
    with pytest.raises(ValidationError):
        fetch(client_for(details=[{"data": data}]))


def test_missing_amount_blocks_entire_page_and_nested_money_is_exact():
    with pytest.raises(ValidationError):
        fetch(client_for(details=[{"data": {"transactions": [transaction(settlement_amount=None)]}}]))
    rows = fetch(client_for(details=[{"data": {"transactions": [transaction(
        settlement_amount={"amount": "-3.2400", "currency": "PHP"})]}}]))["records"]
    assert rows[0]["amount"] == "-3.2400"
    assert rows[0]["fee_name"] == "UNKNOWN"


def test_explicit_empty_statements_and_transactions_remain_valid():
    assert fetch(client_for(statement_data={"statements": []}))["records"] == []
    assert fetch(client_for(details=[{"data": {"transactions": []}}]))["records"] == []


def test_statement_response_currency_is_preserved_not_assumed_from_store():
    item = transaction()
    item.pop("currency")
    row = fetch(client_for(details=[{"data": {"transactions": [item], "currency": "PHP", "total_count": 1}}]))["records"][0]
    assert row["currency"] == "PHP" and row["amount"] == "7.0001"
    with pytest.raises(ValidationError, match="CURRENCY_MISMATCH"):
        fetch(client_for(statement_data={"statements": [{"id": "S", "currency": "USD"}]},
            details=[{"data": {"transactions": [item], "currency": "PHP"}}]))


@pytest.mark.parametrize("total", [True, "1", -1, 0, 2, 10001])
def test_statement_total_count_cannot_hide_missing_or_extra_transactions(total):
    with pytest.raises(ValidationError):
        fetch(client_for(details=[{"data": {"transactions": [transaction()], "total_count": total}}]))


def test_changed_total_count_blocks_statement():
    with pytest.raises(ValidationError, match="TOTAL_COUNT"):
        fetch(client_for(details=[
            {"data": {"transactions": [transaction()], "total_count": 2, "next_page_token": "next"}},
            {"data": {"transactions": [transaction(id="T2")], "total_count": 3}}]))


def test_duplicate_transaction_across_pages_and_cursor_cycle_are_rejected():
    first = {"data": {"transactions": [transaction()], "next_page_token": "next"}}
    for second in ({"data": {"transactions": [transaction()]}},
                   {"data": {"transactions": [transaction(id="T2")], "next_page_token": "next"}}):
        with pytest.raises(ValidationError):
            fetch(client_for(details=[deepcopy(first), second]))


def test_finance_detail_page_budget_is_bounded():
    pages = [{"data": {"transactions": [transaction(id=str(i))], "next_page_token": str(i)}} for i in range(100)]
    client = client_for(details=pages)
    with pytest.raises(ValidationError, match="LIMIT_EXCEEDED"):
        fetch(client)
    assert client._request.call_count == 101


@pytest.mark.parametrize("record", [{}, {"amount": None}, {"amount": "bad"},
    {"amount": "NaN"}, {"amount": "1.00001"}, {"amount": 0.1}, {"amount": {"value": "5"}}])
def test_tk_adapter_cannot_bypass_exact_amount_checks(record):
    adapter = MarketplaceFinanceTransactionAdapter(SimpleNamespace(platform="tiktok", platform_config={}))
    adapter.authorization = SimpleNamespace(store=SimpleNamespace(currency="PHP", timezone="Asia/Manila"))
    with pytest.raises(ValidationError):
        adapter.normalize_record({"source_key": "S:T", "fee_name": "UNKNOWN", "currency": "PHP", "occurred_at": 12, **record})


@pytest.mark.parametrize("value", [0.1, True, "-", "NaN", "100000000000000", "1.0000001", "\u0661"])
def test_ads_spend_requires_exact_bounded_ascii_decimal(value):
    data = {"page_info": {"total_page": 1}, "list": [{"dimensions": {"campaign_id": "123"}, "metrics": {"spend": value}}]}
    with pytest.raises(DjangoValidationError):
        _parse_campaign_page(data, 1, None)


@pytest.mark.parametrize("value", [True, 1.5, "1"])
def test_ads_pagination_cannot_truncate_non_integer(value):
    with pytest.raises(DjangoValidationError):
        _parse_campaign_page({"page_info": {"total_page": value}, "list": []}, 1, None)


def test_ads_exact_zero_and_six_decimal_precision():
    data = {"page_info": {"total_page": 1}, "list": [
        {"dimensions": {"campaign_id": "1"}, "metrics": {"spend": "0"}},
        {"dimensions": {"campaign_id": "2"}, "metrics": {"spend": "1.234567"}}]}
    assert _parse_campaign_page(data, 1, None)[1] == {"1": Decimal("0"), "2": Decimal("1.234567")}


def test_statement_token_cycle_is_rejected_before_details_or_writes():
    client = client_for()
    client._request = Mock(side_effect=[
        {"data": {"statements": [{"id": "S1"}], "next_page_token": "A"}},
        {"data": {"statements": [{"id": "S2"}], "next_page_token": "B"}},
        {"data": {"statements": [{"id": "S3"}], "next_page_token": "A"}}])
    with pytest.raises(ValidationError, match="NOT_ADVANCING"):
        fetch(client)
    assert client._request.call_count == 3


def test_duplicate_statement_across_pages_is_rejected():
    client = client_for()
    client._request = Mock(side_effect=[
        {"data": {"statements": [{"id": "S"}], "next_page_token": "A"}},
        {"data": {"statements": [{"id": "S"}], "next_page_token": "B"}}])
    with pytest.raises(ValidationError, match="STATEMENT_ID"):
        fetch(client)
    assert client._request.call_count == 2


def test_statement_page_budget_is_not_reset_by_distinct_tokens():
    client = client_for()
    client._request = Mock(side_effect=[{"data": {"statements": [{"id": str(i)}],
        "next_page_token": str(i)}} for i in range(100)])
    with pytest.raises(ValidationError, match="LIMIT_EXCEEDED"):
        fetch(client)
    assert client._request.call_count == 100


def test_complete_statement_window_returns_one_page_and_all_raw_responses():
    client = client_for()
    def request(path, **kwargs):
        if path.endswith("/statements"):
            if "page_token" not in kwargs["query"]:
                return {"data": {"statements": [{"id": "S1"}], "next_page_token": "A"}}
            assert kwargs["query"]["page_token"] == "A"
            return {"data": {"statements": [{"id": "S2"}]}}
        return {"data": {"transactions": [transaction()]}}
    client._request = Mock(side_effect=request)
    page = fetch(client)
    assert sorted(row["source_key"] for row in page["records"]) == ["S1:T", "S2:T"]
    assert page["next_cursor"] == "" and len(page["raw_responses"]) == 4


def test_provider_cursor_from_before_window_guard_fails_before_request():
    client = client_for()
    with pytest.raises(ValidationError, match="RESTART_REQUIRED"):
        client.fetch_finance_transactions("old-provider-cursor", {"time_from": 1, "time_to": 20, "page_size": 100})
    client._request.assert_not_called()


def test_durable_resume_advances_only_at_completed_time_window_boundary():
    scope = {"time_from": 1, "time_to": 32 * 86400, "page_size": 100}
    first = client_for()
    page = first.fetch_finance_transactions("", scope)
    assert page["next_cursor"] == "tw:2678401:"
    resumed = client_for()
    final = resumed.fetch_finance_transactions(page["next_cursor"], scope)
    assert resumed._request.call_args_list[0].kwargs["query"]["statement_time_ge"] == 2678401
    assert final["next_cursor"] == ""
