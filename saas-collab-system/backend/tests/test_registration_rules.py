import pytest
from rest_framework.exceptions import ValidationError

from apps.sales_management.registration_rules import adjusted_lines, promotion_cost


def test_changes_preserve_other_skus_and_use_current_lines():
    before = [{"sku_id": 1, "quantity": 3}, {"sku_id": 2, "quantity": 4}]
    first = adjusted_lines(before, [{"action": "replace", "old_sku_id": 1, "reduce_quantity": 2, "new_sku_id": 3, "add_quantity": 1}])
    assert first == [{"sku_id": 1, "quantity": 1}, {"sku_id": 2, "quantity": 4}, {"sku_id": 3, "quantity": 1}]
    assert adjusted_lines(first, [{"action": "add", "new_sku_id": 3, "add_quantity": 2}])[-1]["quantity"] == 3
    assert before[0]["quantity"] == 3


@pytest.mark.parametrize("changes", [
    [{"action": "reduce", "old_sku_id": 1, "reduce_quantity": 4}],
    [{"action": "reduce", "old_sku_id": 1, "reduce_quantity": 3}],
    [{"action": "add", "new_sku_id": 2, "add_quantity": True}],
    [{"action": "reduce", "old_sku_id": 1, "reduce_quantity": 2}, {"action": "reduce", "old_sku_id": 1, "reduce_quantity": 2}],
])
def test_invalid_changes_fail(changes):
    with pytest.raises(ValidationError):
        adjusted_lines([{"sku_id": 1, "quantity": 3}], changes)


def test_promotion_formula_and_direction():
    data = {"order_amount": "100", "fee_amount": "10", "fee_currency": "CNY", "exchange_rate": "8.5", "rate_date": "2026-10-13", "rate_source": "人工记录"}
    result = promotion_cost(data, "PHP")
    assert result["cost"] == "185.00"
    assert data.get("cost") is None
    data.update(fee_currency="PHP", exchange_rate="1")
    assert promotion_cost(data, "PHP")["cost"] == "110.00"


@pytest.mark.parametrize("field,value", [("order_amount", "NaN"), ("order_amount", "1.001"), ("fee_amount", "-1"), ("exchange_rate", "0"), ("exchange_rate", 1.2)])
def test_invalid_promotion_amounts(field, value):
    data = {"order_amount": "100", "fee_amount": "10", "fee_currency": "CNY", "exchange_rate": "8", "rate_date": "2026-10-13", "rate_source": "人工"}
    data[field] = value
    with pytest.raises(ValidationError):
        promotion_cost(data, "PHP")
