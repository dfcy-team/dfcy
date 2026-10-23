from datetime import date
from decimal import Decimal

from apps.supply_chain.replenishment import (
    replenishment_quantities,
    target_stock_quantity,
    weighted_daily_sales,
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
