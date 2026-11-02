from datetime import date
from decimal import Decimal

from apps.sales_management.dashboard_cny import cny_summary


def test_cny_summary_converts_before_weighted_growth_and_sums_quantity():
    summary = cny_summary([
        {"currency": "PHP", "previous": {"amount": "100", "quantity": 2},
         "daily": [{"date": "2026-10-01", "amount": "300", "quantity": 3}]},
        {"currency": "THB", "previous": {"amount": "100", "quantity": 4},
         "daily": [{"date": "2026-10-01", "amount": "100", "quantity": 5}]},
        {"currency": "CNY", "previous": {"amount": "10", "quantity": 6},
         "daily": [{"date": "2026-10-01", "amount": "20", "quantity": 7}]},
    ], {"PHP": {"rate": Decimal("2"), "date": date(2026, 10, 1)},
        "THB": {"rate": Decimal("4"), "date": date(2026, 10, 1)},
        "CNY": {"rate": Decimal("1"), "date": None}}, [])
    assert Decimal(summary["previous"]["amount"]) == Decimal("85")
    assert summary["previous"]["quantity"] == 12
    assert Decimal(summary["daily"][0]["amount"]) == Decimal("195")
    assert summary["daily"][0]["quantity"] == 15


def test_cny_summary_missing_rate_fails_closed_but_keeps_native_currency():
    summary = cny_summary([
        {"currency": "CNY", "previous": {"amount": "10", "quantity": 1}, "daily": []},
        {"currency": "PHP", "previous": {"amount": "5", "quantity": 1}, "daily": []},
    ], {}, [])
    assert summary["conversion"]["status"] == "missing_rates"
    assert summary["conversion"]["missing_currencies"] == ["PHP"]
    assert summary["previous"]["amount"] is None


def test_cny_advertising_combines_comparable_totals_and_selected_store_coverage():
    summary = cny_summary([
        {"currency": "PHP", "previous": {"amount": "0", "quantity": 0}, "daily": [
            {"date": "2026-10-01", "amount": "0", "quantity": 0,
             "ad_comparison": {"current": "100", "previous": "0", "covered_stores": 1, "total_stores": 1}}]},
        {"currency": "THB", "previous": {"amount": "0", "quantity": 0}, "daily": [
            {"date": "2026-10-01", "amount": "0", "quantity": 0, "ad_comparison": None}]},
    ], {"PHP": {"rate": Decimal("2"), "date": date(2026, 10, 1)},
        "THB": {"rate": Decimal("4"), "date": date(2026, 10, 1)}},
       [{"currency": "PHP"}, {"currency": "THB"}, {"currency": "THB"}])
    comparison = summary["daily"][0]["ad_comparison"]
    assert comparison == {"current": "50", "previous": "0", "covered_stores": 1, "total_stores": 3}


def test_cny_summary_preserves_zero_baseline_comparison_and_no_comparison_as_null():
    zero_comparison = cny_summary([
        {"currency": "CNY", "previous": {"amount": "0", "quantity": 0}, "daily": [
            {"date": "2026-10-01", "amount": "0", "quantity": 0,
             "ad_comparison": {"current": "0", "previous": "0", "covered_stores": 1, "total_stores": 1}}]},
    ], {}, [{"currency": "CNY"}])
    assert zero_comparison["daily"][0]["ad_comparison"] == {
        "current": "0", "previous": "0", "covered_stores": 1, "total_stores": 1,
    }
    no_comparison = cny_summary([
        {"currency": "CNY", "previous": {"amount": "5", "quantity": 1}, "daily": [
            {"date": "2026-10-01", "amount": "5", "quantity": 1, "ad_comparison": None}]},
    ], {}, [{"currency": "CNY"}])
    assert no_comparison["daily"][0]["ad_comparison"] is None


def test_mixed_sales_ad_only_and_quantity_only_are_not_dropped():
    groups = [
        {"currency": "CNY", "previous": {"amount": "10", "quantity": 1}, "daily": [{"date": "2026-10-01", "amount": "20", "quantity": 2}]},
        {"currency": "PHP", "previous": {"amount": "0", "quantity": 0}, "daily": [{"date": "2026-10-01", "amount": "0", "quantity": 0, "ad_comparison": {"current": "40", "previous": "20", "covered_stores": 1, "total_stores": 1}}]},
        {"currency": "THB", "previous": {"amount": "0", "quantity": 3}, "daily": [{"date": "2026-10-01", "amount": "0", "quantity": 4}]},
    ]
    result = cny_summary(groups, {"PHP": {"rate": Decimal("2")}}, [{"currency": "CNY"}, {"currency": "PHP"}, {"currency": "THB"}])
    assert result["previous"]["quantity"] == 4
    assert result["daily"][0]["quantity"] == 6
    assert result["daily"][0]["ad_comparison"]["current"] == "20"
    for bad in ("0", "-1", "NaN", "Infinity", "bad"):
        assert cny_summary(groups, {"PHP": {"rate": bad}}, [])["conversion"]["status"] == "missing_rates"
