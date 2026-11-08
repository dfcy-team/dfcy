from copy import deepcopy

import pytest

from apps.commerce.inventory_operations import operating_assessment


def facts(**overrides):
    row = dict(available_stock='30', inventory_complete=True, daily_sales='5',
               sales_windows=[dict(days=30, units=150, coverage_complete=True)],
               issues=[], blocking_issues=[], pipeline={'effective_incoming': '1000'})
    return {**row, **overrides}


def test_incoming_does_not_hide_low_current_coverage():
    result = operating_assessment(facts())
    assert result['inventory_status'] == 'low'
    assert result['observed_coverage_days'] == '6.00'
    assert result['sales_status'] == 'observed_sales'
    assert result['availability_history_complete'] is False
    assert result['arrival_prediction_status'] == 'unavailable'


@pytest.mark.parametrize('issue', ['collection_coverage_unproven', 'unmapped_sales_lines', 'bundle_composition_unverified'])
def test_unproven_sales_never_classified_as_sufficient_or_slow(issue):
    result = operating_assessment(facts(issues=[issue]))
    assert result['sales_status'] == result['inventory_status'] == 'unknown'


def test_zero_sales_is_not_slow_moving_and_coverage_not_zero():
    result = operating_assessment(facts(daily_sales='0', sales_windows=[dict(days=30, units=0, coverage_complete=True)]))
    assert result['sales_status'] == 'no_sales'
    assert result['inventory_status'] == 'unknown'
    assert 'observed_coverage_days' not in result


@pytest.mark.parametrize('value', [None, 'NaN', 'Infinity', 'bad'])
def test_invalid_stock_remains_unknown(value):
    assert operating_assessment(facts(available_stock=value))['inventory_status'] == 'unknown'


def test_stale_stock_and_observed_sales_are_independent():
    result = operating_assessment(facts(inventory_complete=False))
    assert result['inventory_status'] == 'unknown'
    assert result['sales_status'] == 'observed_sales'


def test_zero_stock_known_even_when_sales_unknown():
    result = operating_assessment(facts(available_stock='0', issues=['collection_coverage_unproven']))
    assert result['inventory_status'] == 'out'
    assert result['sales_status'] == 'unknown'


@pytest.mark.parametrize(('stock', 'expected'), [('35', 'sufficient'), ('300', 'sufficient'), ('301', 'over')])
def test_threshold_boundaries(stock, expected):
    row = facts(available_stock=stock)
    original = deepcopy(row)
    assert operating_assessment(row)['inventory_status'] == expected
    assert row == original


@pytest.mark.parametrize(('days', 'stock', 'rounded'), [(30, '2', '0.0333'), (7, '1', '0.1429')])
def test_rounded_daily_sales_do_not_change_boundary(days, stock, rounded):
    row = facts(available_stock=stock, daily_sales=rounded,
                sales_windows=[dict(days=days, units=1, coverage_complete=True)])
    assert operating_assessment(row, window_days=days)['inventory_status'] == 'sufficient'


def test_mapped_observations_survive_other_unmapped_records():
    row = facts(mapped_only=True, mapped_sales_units=60, mapped_sales_complete=False,
                unmapped_inventory_excluded=True, unmapped_sales_excluded=True,
                unknown_bundle_demand_excluded=True, issues=['collection_coverage_unproven'])
    result = operating_assessment(row)
    assert result['sales_status'] == 'observed_sales'
    assert result['inventory_status'] == 'observed'
    assert result['observed_coverage_days'] == '15.00'


def test_mapped_zero_is_not_proof_of_no_demand():
    result = operating_assessment(facts(mapped_only=True, mapped_sales_units=0, mapped_sales_complete=False))
    assert result['sales_status'] == 'unknown'
    assert result['inventory_status'] == 'observed'
    assert 'observed_coverage_days' not in result
