from types import SimpleNamespace

import pytest
from rest_framework.exceptions import ValidationError

from apps.integrations.adapters import MarketplaceFinanceTransactionAdapter, _lazada_finance_amount


@pytest.mark.parametrize("source,expected", [
    ("1,029.00", "1029.00"),
    ("-68,690.72", "-68690.72"),
    ("1,234,567.89", "1234567.89"),
    ("1029.00", "1029.00"),
    ("0.00", "0.00"),
])
def test_lazada_finance_grouped_amount_survives_normalization(source, expected):
    adapter = MarketplaceFinanceTransactionAdapter(SimpleNamespace(
        platform="lazada", platform_config={}, environment="production",
    ))
    adapter.authorization = SimpleNamespace(store=SimpleNamespace(currency="PHP", timezone="Asia/Manila"))
    record = adapter.normalize_record({
        "transaction_id": "format-test", "order_no": "order-test",
        "transaction_date": "15 Sep 2026", "fee_name": "Item Price Credit", "amount": source,
    })
    assert record["raw_amount"] == expected


@pytest.mark.parametrize("source", ["1,23.00", "1,234,56", "1,000oops"])
def test_lazada_finance_bad_grouping_is_not_silently_zero(source):
    with pytest.raises(ValidationError):
        _lazada_finance_amount(source)
