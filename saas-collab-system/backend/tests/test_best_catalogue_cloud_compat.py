"""Offline preservation checks for the deployed catalogue reader."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.test import override_settings
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.integrations.best_glink import BestGlinkClient


def make_client():
    return BestGlinkClient(SimpleNamespace(platform_config={"customer_code": "TEST-C"}),
                           SimpleNamespace(), http_client=Mock(), custody=Mock())


def rows(codes, customer="TEST-C"):
    return [{"sku": code, "customerCode": customer} for code in codes]


def test_catalogue_two_bounded_pages_and_complete_coverage():
    client = make_client()
    codes = ["SKU-" + str(i) for i in range(150)]
    client.query = Mock(side_effect=[{"itemList": rows(codes[:100]), "total": 100},
                                     {"itemList": rows(codes[100:]), "total": 50}])
    first, cursor = client.fetch_catalogue_page(0, codes)
    second, end = client.fetch_catalogue_page(cursor, codes)
    assert len(first) == 100 and len(second) == 50 and end is None
    assert all(c.args[0] == "GLINK_QUERY_ITEM_NOTIFY" for c in client.query.call_args_list)
    assert all(len(c.args[1]["skus"]) <= 100 for c in client.query.call_args_list)


@pytest.mark.parametrize("result", [
    {"itemList": rows(["SKU-A"]), "total": 2},
    {"itemList": rows(["SKU-A"]), "total": 1},
    {"itemList": rows(["SKU-A", "SKU-A"]), "total": 2},
    {"itemList": rows(["SKU-A", "SKU-B"], "OTHER"), "total": 2},
])
def test_missing_duplicate_or_wrong_customer_rows_refused(result):
    client = make_client()
    client.query = Mock(return_value=result)
    with pytest.raises(ValidationError):
        client.fetch_catalogue_page(0, ["SKU-A", "SKU-B"])


def test_casefold_duplicate_scope_refused_before_provider():
    client = make_client()
    client.query = Mock()
    with pytest.raises(ValidationError):
        client.fetch_catalogue_page(0, ["sku-a", "SKU-A"])
    client.query.assert_not_called()


def test_debug_never_uses_network_even_with_catalogue_method():
    client = make_client()
    with override_settings(DEBUG=True), pytest.raises(PermissionDenied):
        client.fetch_catalogue_page(0, ["SKU-A"])
    client.http.request.assert_not_called()
