from types import SimpleNamespace

import pytest
from rest_framework.exceptions import ValidationError

from apps.integrations.readonly_clients import ShopeeReadonlyClient


def client_with(request):
    client = ShopeeReadonlyClient(SimpleNamespace(platform="shopee", platform_config={}), custody=object())
    client._request = request
    return client


def payout(identifier="batch-1", amount="90", timestamp=10):
    return {"encrypted_payout_id": identifier, "from_amount": amount, "from_currency": "PHP",
            "payout_amount": "1.50", "payout_currency": "USD", "exchange_rate": "0.01667",
            "payout_time": timestamp, "payee_id": "PRIVATE-ACCOUNT"}


def billing(amount, kind="ADJUSTMENT", level="SHOP", order=""):
    return {"amount": amount, "currency": "PHP", "order_sn": order, "level": level,
            "billing_transaction_type": kind, "billing_transaction_status": "RELEASED",
            "cost_header": "Marketing Fee", "scenario": "Paid Ads Service", "remark": ""}


def scope(end=20):
    return {"time_from": 1, "time_to": end, "page_size": 100}


def test_payout_collection_pages_billing_and_keeps_duplicate_charges_separate():
    calls = []

    def request(path, query, *, readonly_body=None):
        calls.append((path, query, readonly_body))
        if path.endswith("get_payout_info"):
            return {"response": {"payout_list": [payout()], "more": False, "next_cursor": ""}}
        if not readonly_body["cursor"]:
            return {"response": {"transactions": [billing("100", "ESCROW", "ORDER", "ORDER-1"), billing("-5")],
                                 "more": True, "next_cursor": "next"}}
        return {"response": {"transactions": [billing("-5")], "more": False, "next_cursor": ""}}

    result = client_with(request).fetch_payout_finance(scope())
    assert len(result["transactions"]) == 3
    assert len({row["source_key"] for row in result["transactions"]}) == 3
    assert result["summary"]["PHP"] == {
        "order_income": "100", "order_adjustment": "0", "shop_adjustment": "-10",
        "unclassified": "0", "billing_total": "90", "settlement_total": "90", "difference": "0",
    }
    assert result["payouts"][0]["payout_currency"] == "USD"
    assert "payee_id" not in result["payouts"][0]
    assert all("PRIVATE-ACCOUNT" not in str(row) for row in result["raw_responses"])
    assert calls[1][1] == {}
    assert calls[1][2] == {"billing_transaction_info_type": 2, "encrypted_payout_ids": ["batch-1"],
                           "cursor": "", "page_size": 100}
    assert not result.get("records")  # No payout or escrow duplicate is sent to the ordinary income ledger.
    assert all(row["date_basis"] == "payout_time" for row in result["transactions"])
    assert all("occurred_at" not in row for row in result["transactions"])
    assert result["reconciled"] is True
    assert "billing_total" not in result["raw_responses"][0]["payload"]["response"]["payout_list"][0]


def test_payout_list_follows_cursor_and_splits_at_fifteen_days():
    queries = []

    def request(path, query, **kwargs):
        if path.endswith("get_payout_info"):
            queries.append(query)
            more = len(queries) == 1
            return {"response": {"payout_list": [], "more": more, "next_cursor": "page2" if more else ""}}
        raise AssertionError("No billing query without a payout ID")

    client_with(request).fetch_payout_finance(scope(30 * 86400))
    assert len(queries) == 3
    assert queries[1]["cursor"] == "page2"
    assert queries[2]["cursor"] == ""
    assert queries[0]["payout_time_to"] + 1 == queries[2]["payout_time_from"]
    assert all(q["payout_time_to"] - q["payout_time_from"] + 1 <= 15 * 86400 for q in queries)


@pytest.mark.parametrize("response", [
    {"payout_list": [], "more": True, "next_cursor": ""},
    {"payout_list": [], "more": False, "next_cursor": "unexpected"},
    {"payout_list": [], "more": "false", "next_cursor": ""},
    {"more": False, "next_cursor": ""},
])
def test_invalid_or_incomplete_pagination_is_not_reported_as_complete(response):
    with pytest.raises(ValidationError):
        client_with(lambda *a, **kw: {"response": response}).fetch_payout_finance(scope())


def test_repeated_cursor_fails_instead_of_silently_truncating():
    def request(*args, **kwargs):
        return {"response": {"payout_list": [], "more": True, "next_cursor": "same"}}
    with pytest.raises(ValidationError, match="cursor"):
        client_with(request).fetch_payout_finance(scope())


@pytest.mark.parametrize("field,value", [("from_amount", None), ("from_amount", "NaN"),
                                         ("from_currency", ""), ("payout_time", 1000)])
def test_missing_money_currency_or_out_of_scope_payout_fails(field, value):
    row = {**payout(), field: value}
    with pytest.raises(ValidationError):
        client_with(lambda *a, **kw: {"response": {"payout_list": [row], "more": False, "next_cursor": ""}}).fetch_payout_finance(scope())


def test_empty_payouts_do_not_prove_zero_income():
    result = client_with(lambda *a, **kw: {"response": {"payout_list": [], "more": False, "next_cursor": ""}}).fetch_payout_finance(scope())
    assert result["summary"] == {}
    assert result["payouts"] == []
    assert result["reconciled"] is False


def test_billing_currency_mismatch_cannot_be_added_to_settlement_currency():
    def request(path, query, **kwargs):
        if path.endswith("get_payout_info"):
            return {"response": {"payout_list": [payout()], "more": False, "next_cursor": ""}}
        return {"response": {"transactions": [{**billing("90"), "currency": "USD"}], "more": False, "next_cursor": ""}}
    with pytest.raises(ValidationError, match="currency"):
        client_with(request).fetch_payout_finance(scope())


def test_repeated_collection_is_stable_and_unknown_types_are_visible():
    def request(path, query, **kwargs):
        if path.endswith("get_payout_info"):
            return {"response": {"payout_list": [payout()], "more": False, "next_cursor": ""}}
        return {"response": {"transactions": [billing("90", "NEW_TYPE")], "more": False, "next_cursor": ""}}
    client = client_with(request)
    assert client.fetch_payout_finance(scope()) == client.fetch_payout_finance(scope())
    assert client.fetch_payout_finance(scope())["unclassified_count"] == 1


def test_billing_is_an_explicit_readonly_post_endpoint():
    assert "/api/v2/payment/get_billing_transaction_info" in ShopeeReadonlyClient.READONLY_POST_PATHS
    assert "/api/v2/payment/set_shop_installment_status" not in ShopeeReadonlyClient.READONLY_POST_PATHS


def test_per_batch_differences_cannot_cancel_into_a_false_pass():
    def request(path, query, *, readonly_body=None):
        if path.endswith("get_payout_info"):
            return {"response": {"payout_list": [payout("one"), payout("two")], "more": False, "next_cursor": ""}}
        amount = "100" if readonly_body["encrypted_payout_ids"] == ["one"] else "80"
        return {"response": {"transactions": [billing(amount)], "more": False, "next_cursor": ""}}
    result = client_with(request).fetch_payout_finance(scope())
    assert result["summary"]["PHP"]["difference"] == "0"
    assert result["reconciled"] is False


def test_duplicate_payout_id_is_not_billed_twice_but_conflicting_version_fails():
    billing_calls = []

    def request(path, query, *, readonly_body=None):
        if path.endswith("get_payout_info"):
            return {"response": {"payout_list": [payout(), payout()], "more": False, "next_cursor": ""}}
        billing_calls.append(readonly_body)
        return {"response": {"transactions": [billing("90")], "more": False, "next_cursor": ""}}
    assert len(client_with(request).fetch_payout_finance(scope())["payouts"]) == 1
    assert len(billing_calls) == 1
    bad = {"response": {"payout_list": [payout(), payout(amount="91")], "more": False, "next_cursor": ""}}
    with pytest.raises(ValidationError, match="conflicting"):
        client_with(lambda *a, **kw: bad).fetch_payout_finance(scope())


def test_billing_repeated_cursor_and_unreleased_rows_fail():
    def request(path, query, **kwargs):
        if path.endswith("get_payout_info"):
            return {"response": {"payout_list": [payout()], "more": False, "next_cursor": ""}}
        return {"response": {"transactions": [], "more": True, "next_cursor": "same"}}
    with pytest.raises(ValidationError, match="cursor"):
        client_with(request).fetch_payout_finance(scope())

    def unreleased(path, query, **kwargs):
        if path.endswith("get_payout_info"):
            return request(path, query)
        return {"response": {"transactions": [{**billing("90"), "billing_transaction_status": "TO_RELEASE"}],
                             "more": False, "next_cursor": ""}}
    with pytest.raises(ValidationError, match="unreleased"):
        client_with(unreleased).fetch_payout_finance(scope())


def test_readonly_post_transport_honors_preflight_and_never_allows_mutation(monkeypatch):
    from tests.test_shopee_readonly_runtime import configured

    client, http = configured(monkeypatch, {"contract_approved": True, "api_host": "https://approved.example.test"})
    client.resource_type = "settlement_bill"
    body = {"billing_transaction_info_type": 2, "encrypted_payout_ids": ["batch-1"], "cursor": "", "page_size": 100}
    client._request("/api/v2/payment/get_billing_transaction_info", {}, readonly_body=body)
    assert http.request.call_args.args[0] == "POST"
    assert http.request.call_args.kwargs["json_body"] == body
    http.reset_mock()
    with pytest.raises(ValidationError, match="not allowed"):
        client._request("/api/v2/payment/set_shop_installment_status", {}, readonly_body={})
    http.request.assert_not_called()
    client.authorization.expires_at = client.now()
    with pytest.raises(ValidationError, match="TOKEN_REFRESH_REQUIRED"):
        client._request("/api/v2/payment/get_billing_transaction_info", {}, readonly_body=body)
    http.request.assert_not_called()


@pytest.mark.parametrize("month", ["2026/09", "2026-13", "0000-09"])
def test_command_rejects_invalid_month_before_accessing_credentials(month, tmp_path):
    from django.core.management.base import CommandError
    from apps.integrations.management.commands.collect_shopee_payout_finance import Command

    with pytest.raises(CommandError, match="[Mm]onth"):
        Command().handle(tenant_id=1, store_code="STORE", authorization_id=1,
                         month=month, output=str(tmp_path / "new.json"))


def test_command_refuses_to_overwrite_existing_output(tmp_path):
    from django.core.management.base import CommandError
    from apps.integrations.management.commands.collect_shopee_payout_finance import Command

    # An existing directory is also an unsafe output target; no file needs changing.
    with pytest.raises(CommandError, match="new file"):
        Command().handle(tenant_id=1, store_code="STORE", authorization_id=1,
                         month="2026-09", output=str(tmp_path))
