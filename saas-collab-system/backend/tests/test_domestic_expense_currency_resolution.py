"""A replacement may only use one explicitly recorded original currency."""
import pytest
from apps.supply_chain.domestic_expenses import replacement_currency

@pytest.mark.parametrize("codes,exchange,expected", [
    ({"PHP"}, {}, "PHP"),
    (set(), {"currency": "PHP"}, "PHP"),
    ({"PHP"}, {"currency": "CNY"}, None),
    ({"PHP", "CNY"}, {}, None),
    (set(), {}, None),
    ({"usd"}, {}, None),
    ({"US1"}, {}, None),
    ({"CNY"}, {"currency": "CNY"}, "CNY"),
])
def test_replacement_preserves_known_currency_and_refuses_missing_or_conflicting_units(codes, exchange, expected):
    assert replacement_currency(codes, exchange) == expected
