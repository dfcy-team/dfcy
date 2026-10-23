from datetime import date, timedelta
from decimal import Decimal

from apps.supply_chain.replenishment_math import forecast_timeline


TODAY = date(2026, 10, 23)


def forecast(**kwargs):
    return forecast_timeline(daily=Decimal(20), today=TODAY, lead_days=30,
        cycle_days=7, safety_days=15, stock=100, eta_rows=[], **kwargs)


def test_activity_only_changes_covered_dates():
    out = forecast(activity_start=TODAY + timedelta(days=20),
        activity_end=TODAY + timedelta(days=29), activity_factor=Decimal('1.5'))
    assert out['target_stock'] == 1140
    assert out['reminder_stock'] == 1000
    assert out['on_hand_days'] == Decimal('5.00')


def test_timely_arrival_prevents_false_shortage_despite_short_on_hand_coverage():
    out = forecast_timeline(daily=20, today=TODAY, lead_days=30, cycle_days=7,
        safety_days=15, stock=100, eta_rows=[{'expected_date': '2026-10-25', 'quantity': 1000}])
    assert out['first_shortage_date'] is None
    assert out['arrival_gap'] is False
    assert out['needs_replenishment'] is False


def test_late_arrival_does_not_hide_intermediate_stockout():
    out = forecast_timeline(daily=20, today=TODAY, lead_days=30, cycle_days=7,
        safety_days=15, stock=100, eta_rows=[{'expected_date': '2026-11-10', 'quantity': 1000}])
    assert out['first_shortage_date'] == '2026-10-29'
    assert out['arrival_gap'] is True
    assert out['needs_replenishment'] is False


def test_zero_sales_and_unknown_stock_have_no_invented_coverage():
    zero = forecast_timeline(daily=0, today=TODAY, lead_days=30, cycle_days=7,
        safety_days=15, stock=32, eta_rows=[])
    assert zero['on_hand_days'] is None
    assert zero['target_stock'] == 0
    assert zero['first_shortage_date'] is None
    unknown = forecast_timeline(daily=20, today=TODAY, lead_days=30, cycle_days=7,
        safety_days=15, stock=None, eta_rows=[])
    assert unknown['on_hand_days'] is None
    assert unknown['needs_replenishment'] is None


def test_activity_changes_actual_on_hand_coverage():
    out = forecast(activity_start=TODAY + timedelta(days=1),
        activity_end=TODAY + timedelta(days=10), activity_factor=Decimal('0.5'))
    assert out['on_hand_days'] == Decimal('10.00')


def test_unknown_and_outside_horizon_arrivals_do_not_add_timely_supply():
    out = forecast_timeline(daily=20, today=TODAY, lead_days=30, cycle_days=7,
        safety_days=15, stock=100, eta_rows=[{'expected_date': None, 'quantity': 1000},
            {'expected_date': '2027-01-01', 'quantity': 1000},
            {'expected_date': '2026-10-01', 'quantity': 1000}])
    assert out['target_incoming'] == 0
    assert out['first_shortage_date'] == '2026-10-29'


def test_target_top_up_and_reorder_trigger_are_different():
    out = forecast_timeline(daily=1, today=TODAY, lead_days=45, cycle_days=10,
        safety_days=35, stock=85, eta_rows=[])
    assert out['target_stock'] == 90
    assert out['reminder_stock'] == 80
    assert out['needs_replenishment'] is False
    assert out['arrival_gap'] is False
