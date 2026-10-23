from datetime import date
from decimal import Decimal
from fractions import Fraction
from types import SimpleNamespace

import pytest

from apps.supply_chain.replenishment import (
    replenishment_quantities,
    target_stock_quantity,
    weighted_daily_sales,
    evaluate_replenishment_row,
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
