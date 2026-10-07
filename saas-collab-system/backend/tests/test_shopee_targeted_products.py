from types import SimpleNamespace

import pytest
from rest_framework.exceptions import ValidationError

from apps.integrations.readonly_clients import ShopeeReadonlyClient


def _client():
    return ShopeeReadonlyClient(SimpleNamespace(platform="shopee", platform_config={}), custody=object())


def test_targeted_products_hydrate_real_models_and_report_omissions():
    client = _client()
    calls = []

    def request(path, query):
        calls.append((path, query))
        if path == client.PRODUCT_BASE_INFO_PATH:
            return {"response": {"item_list": [
                {"item_id": 11, "item_name": "Simple", "item_sku": "S-11", "item_status": "NORMAL", "category_id": 4, "has_model": False},
                {"item_id": 22, "item_name": "Modeled", "item_status": "NORMAL", "has_model": True},
            ]}}
        return {"response": {"model": [{"model_id": 221, "model_sku": "M-221", "model_status": "NORMAL", "tier_index": [0]}],
                            "tier_variation": [{"name": "Color", "option_list": [{"option": "Blue"}]}]}}

    client._request = request
    result = client.fetch_products_by_ids(["11", "22", "33"])
    assert len(calls) == 2 and calls[0][0] == client.PRODUCT_BASE_INFO_PATH
    assert result["next_cursor"] == ""
    assert result["unavailable_item_ids"] == ["33"]
    assert [(r["platform_product_id"], r["platform_variant_id"]) for r in result["records"]] == [("11", "11"), ("22", "221")]
    assert result["records"][0]["category_l1"] == "4"
    assert result["records"][1]["variant"] == "Color=Blue"


@pytest.mark.parametrize("payload", [
    {"response": {}},
    {"response": {"item_list": [{"item_id": 99}]}},
    {"response": {"item_list": [{"item_id": 11}, {"item_id": 11}]}},
    {"response": {"item_list": [None]}},
])
def test_targeted_products_fail_closed_on_malformed_or_foreign_base_rows(payload):
    client = _client()
    client._request = lambda _path, _query: payload
    with pytest.raises(ValidationError):
        client.fetch_products_by_ids(["11"])


def test_targeted_empty_model_list_is_unavailable_and_no_variant_is_invented():
    client = _client()
    client._request = lambda path, _query: (
        {"response": {"item_list": [{"item_id": 11, "has_model": True}]}}
        if path == client.PRODUCT_BASE_INFO_PATH else {"response": {"model": []}}
    )
    result = client.fetch_products_by_ids(["11"])
    assert result["records"] == []
    assert result["unavailable_item_ids"] == ["11"]


def test_targeted_model_request_errors_propagate():
    client = _client()
    calls = 0

    def request(path, _query):
        nonlocal calls
        calls += 1
        if path == client.PRODUCT_BASE_INFO_PATH:
            return {"response": {"item_list": [{"item_id": 11, "has_model": True}]}}
        raise RuntimeError("provider failure")

    client._request = request
    with pytest.raises(RuntimeError, match="provider failure"):
        client.fetch_products_by_ids(["11"])
    assert calls == 2


@pytest.mark.parametrize("ids", [[], ["1", "1"], [""], ["abc"], ["1"] * 51, [1], ["0"], ["１２"], ["1" * 21]])
def test_targeted_product_ids_are_strictly_validated(ids):
    with pytest.raises(ValidationError):
        _client().fetch_products_by_ids(ids)


@pytest.mark.parametrize("base", [{"item_id": 11}, {"item_id": 11, "has_model": "false"}])
def test_targeted_missing_or_untyped_has_model_never_invents_single_variant(base):
    client = _client()
    client._request = lambda _path, _query: {"response": {"item_list": [base]}}
    with pytest.raises(ValidationError):
        client.fetch_products_by_ids(["11"])


@pytest.mark.parametrize("models", [[{"model_id": "0"}], [{"model_id": "221"}, {"model_id": "221"}], [{"model_id": "foreign"}]])
def test_targeted_invalid_models_fail_closed(models):
    client = _client()
    client._request = lambda path, _query: (
        {"response": {"item_list": [{"item_id": 11, "has_model": True}]}}
        if path == client.PRODUCT_BASE_INFO_PATH else {"response": {"model": models}}
    )
    with pytest.raises(ValidationError):
        client.fetch_products_by_ids(["11"])
