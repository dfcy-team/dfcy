from decimal import Decimal

from apps.sales_management.display_currency import aggregate_display_group, convert_currency_group


def test_currency_conversion_preserves_counts_and_inventory():
    source = {"currency": "PHP", "sales_amount": "800", "order_count": 3,
              "inventory": {"available_qty": 27, "in_transit_qty": 5}, "store_roi": "4"}
    rates = {"PHP": {"rate": Decimal(8)}, "CNY": {"rate": Decimal(1)}}
    result = convert_currency_group(source, "PHP", "CNY", rates)
    assert result["sales_amount"] == "100.000"
    assert result["order_count"] == 3
    assert result["inventory"] == source["inventory"]
    assert result["store_roi"] == "4"
    assert source["sales_amount"] == "800"


def test_cny_merge_retains_all_stores_and_orders_the_converted_values():
    rates = {"PHP": {"rate": Decimal(8)}, "MYR": {"rate": Decimal(2)}, "CNY": {"rate": Decimal(1)}}
    groups = [
        {"currency": "PHP", "sales_amount": "800", "order_count": 2, "units_sold": 9,
         "store_ranking": [{"store_id": 1, "sales_amount": "800", "order_count": 2, "units_sold": 9}]},
        {"currency": "MYR", "sales_amount": "300", "order_count": 3, "units_sold": 4,
         "store_ranking": [{"store_id": 2, "sales_amount": "300", "order_count": 3, "units_sold": 4}]},
    ]
    result = aggregate_display_group(groups, "CNY", rates)
    assert Decimal(result["sales_amount"]) == 250
    assert result["order_count"] == 5
    assert [row["store_id"] for row in result["store_ranking"]] == [2, 1]
    assert result["currency"] == "CNY"
    assert result["units_sold"] == 13
    assert [row["store_id"] for row in result["store_rankings"]["units_sold"]] == [1, 2]


def test_missing_exchange_rate_keeps_money_unknown_and_counts_visible():
    groups = [{"currency": "PHP", "sales_amount": "80", "order_count": 2,
               "store_ranking": [{"store_id": 1, "sales_amount": "80", "order_count": 2}]}]
    result = aggregate_display_group(groups, "CNY", {"CNY": {"rate": Decimal(1)}})
    assert result["sales_amount"] is None
    assert result["order_count"] == 2
    assert result["store_ranking"][0]["sales_amount"] is None
    assert result["missing_rate_currencies"] == ["PHP"]
