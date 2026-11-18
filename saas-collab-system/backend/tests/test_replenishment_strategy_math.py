from datetime import date
from decimal import Decimal
from fractions import Fraction
from types import SimpleNamespace

import pytest

from apps.supply_chain.replenishment import (
    replenishment_quantities,
    _replenishment_risk,
    _supply_action,
    target_stock_quantity,
    weighted_daily_sales,
    evaluate_replenishment_row,
    recognized_reference,
)


def test_weighted_daily_sales_uses_7_15_30_day_weights():
    daily = {7: Decimal('20'), 15: Decimal('16'), 30: Decimal('14')}
    assert weighted_daily_sales(daily, {'7': 50, '15': 30, '30': 20}) == Decimal('17.6')
    assert weighted_daily_sales(daily, {'7': 0, '15': 0, '30': 100}) == Decimal('14')


def test_target_stock_applies_activity_factor_only_on_overlapping_dates():
    target = target_stock_quantity(Decimal('20'), date(2026, 1, 1), 10,
        date(2026, 1, 3), date(2026, 1, 5), Decimal('1.5'))
    assert target == Decimal('230.0000')
    lowered = target_stock_quantity(Decimal('20'), date(2026, 1, 1), 10,
        date(2026, 1, 3), date(2026, 1, 5), Decimal('0.5'))
    assert lowered == Decimal('170.0000')


def test_replenishment_excludes_submitted_and_draft_reservations_and_clamps_zero():
    gap, quantity = replenishment_quantities(Decimal('100'), Decimal('20'), Decimal('10'), Decimal('15'), Decimal('5'))
    assert (gap, quantity) == (Decimal('70'), 50)
    assert replenishment_quantities(Decimal('20'), Decimal('30'), Decimal('0'), Decimal('0'), Decimal('0')) == (Decimal('0'), 0)
    assert replenishment_quantities(Decimal('100'), None, Decimal('0'), Decimal('0'), Decimal('0')) == (None, None)


def _exact_row(units):
    return {'sales_windows': [{'days': day, 'units': units.get(day, 0), 'coverage_complete': True}
                             for day in (7, 15, 30)],
            'inventory_complete': True, 'available_stock': 0,
            'pipeline': {'authorized': True, 'issues': [], 'eta_rows': [],
                         'submitted_operating_demand': 0, 'draft_reserved_demand': 0}}


@pytest.mark.parametrize('units,horizon,expected', [(2, 90, 6), (1, 90, 3), (7, 30, 7),
                                                    (10**18, 90, 3 * 10**18)])
def test_ordinary_window_ratio_does_not_round_integer_target_up(units, horizon, expected):
    row = _exact_row({30: units})
    strategy = SimpleNamespace(sales_model='ordinary', sales_weights={}, lead_days=horizon-1,
                               cycle_days=1, safety_days=0)
    result = evaluate_replenishment_row(row, strategy, sales_end=date(2026, 1, 1), today=date(2026, 1, 2))
    assert result['timeline']['target_stock'] == expected
    assert result['suggested_quantity'] == expected


def test_weighted_recurring_ratios_and_activity_keep_exact_order_quantity():
    row = _exact_row({7: 7, 15: 1, 30: 1})
    strategy = SimpleNamespace(sales_model='weighted', sales_weights={'7': 50, '15': 30, '30': 20},
                               lead_days=100, cycle_days=15, safety_days=35)
    result = evaluate_replenishment_row(row, strategy, sales_end=date(2026, 1, 1), today=date(2026, 1, 2))
    assert result['timeline']['target_stock'] == 79
    assert result['suggested_quantity'] == 79

    row = _exact_row({30: 2})
    strategy = SimpleNamespace(sales_model='ordinary', sales_weights={}, lead_days=45,
                               cycle_days=10, safety_days=35)
    result = evaluate_replenishment_row(row, strategy, sales_end=date(2026, 1, 1), today=date(2026, 1, 2),
        activity_start=date(2026, 1, 3), activity_end=date(2026, 2, 1), activity_factor=Decimal('1.5'))
    assert result['timeline']['target_stock'] == 7
    assert result['suggested_quantity'] == 7


def test_exact_ratio_ceiling_never_discards_a_small_real_fraction():
    # Display precision may round this to 1000; ordering must still ceil the exact requirement.
    ratio = Fraction(1000) + Fraction(1, 10**30)
    gap, quantity = replenishment_quantities(Decimal('1000'), 0, 0, 0, 0,
        target_ratio=(ratio.numerator, ratio.denominator))
    assert quantity == 1001


def test_unknown_warehouse_demand_does_not_become_a_known_zero():
    row = _exact_row({30: 30})
    row['pipeline'].update(submitted_operating_demand=None, draft_reserved_demand=None,
        issues=['warehouse_supply_scope_incomplete'])
    strategy = SimpleNamespace(sales_model='ordinary', sales_weights={}, lead_days=45,
                               cycle_days=10, safety_days=35)
    result = evaluate_replenishment_row(row, strategy, sales_end=date(2026, 1, 1), today=date(2026, 1, 2))
    assert result['submitted'] is None
    assert result['draft_reserved'] is None
    assert result['suggested_quantity'] is None


def test_forecast_shortage_is_risk_even_when_no_purchase_quantity_is_suggested():
    row = _exact_row({30: 30})
    row['available_stock'] = 3
    row['pipeline']['eta_rows'] = [{'expected_date': '2026-11-22', 'quantity': 10}]
    strategy = SimpleNamespace(sales_model='ordinary', sales_weights={},
                               lead_days=2, safety_days=3, cycle_days=2)
    result = evaluate_replenishment_row(row, strategy,
        sales_end=date(2026, 11, 16), today=date(2026, 11, 17))
    timeline = result['timeline']
    assert timeline['first_shortage_date'] == '2026-11-21'
    assert timeline['arrival_gap'] is False
    assert result['suggested_quantity'] == 0
    assert _replenishment_risk(unknown=False, forecast=Decimal('1'), stock=Decimal('3'),
        timeline=timeline) == 'arrival_gap'
    assert _supply_action(timeline, 0) == 'expedite_or_transfer'


def test_purchase_action_requires_positive_quantity_and_no_shortage_stays_normal():
    shortage = {'arrival_gap': False, 'first_shortage_date': '2026-11-21',
                'needs_replenishment': False}
    assert _supply_action(shortage, 4) == 'purchase_and_expedite'
    no_shortage = {'arrival_gap': False, 'first_shortage_date': None,
                   'needs_replenishment': False}
    assert _replenishment_risk(unknown=False, forecast=Decimal('1'), stock=Decimal('30'),
        timeline=no_shortage) == 'normal'
    assert _supply_action(no_shortage, 0) is None


def test_ordinary_calculation_only_requires_the_weighted_window():
    row = _exact_row({30: 30})
    row['sales_windows'][0].update(units=None, coverage_complete=False)
    strategy = SimpleNamespace(sales_model='ordinary', lead_days=10, cycle_days=5, safety_days=5)
    result = evaluate_replenishment_row(row, strategy, sales_end=date(2026, 1, 1), today=date(2026, 1, 2))
    assert result['suggested_quantity'] == 20


def test_scope_gap_keeps_verified_observations_separate_from_order_quantity():
    row = _exact_row({30: 30})
    row['sales_windows'][2].update(recognized_units=30, coverage_complete=False)
    row.update(inventory_complete=False, available_stock=None,
        warehouses=[{'available_qty': '4'}, {'available_qty': None, 'last_synced_qty': '99'}],
        blocking_issues=['collection_coverage_unproven', 'unmapped_inventory', 'stale_inventory_snapshot'])
    strategy = SimpleNamespace(sales_model='ordinary', lead_days=10, cycle_days=5, safety_days=5)
    today = date(2026, 1, 2)
    result = evaluate_replenishment_row(row, strategy, sales_end=date(2026, 1, 1), today=today)
    reference = recognized_reference(row, strategy, calculated=result, today=today)
    assert result['suggested_quantity'] is None
    assert reference['has_observed_basis'] is True
    assert reference['observed_available_stock'] == '4'
    assert reference['scope_issues'] == ['collection_coverage_unproven', 'unmapped_inventory']
    assert reference['item_issues'] == ['stale_inventory_snapshot']
    assert reference['quantity_reference'] == 16
    assert reference['can_create_order'] is False

    row['sales_windows'][2]['recognized_units'] = 0
    result = evaluate_replenishment_row(row, strategy, sales_end=date(2026, 1, 1), today=today)
    reference = recognized_reference(row, strategy, calculated=result, today=today)
    assert reference['quantity_reference'] is None
    assert reference['has_observed_basis'] is False
