from datetime import date
from apps.integrations.gmv_max_overview import overview, shop_overview


def row(**values):
    return dict(store_code='TK1PH', advertiser_id='1', advertiser_name='Test',
        platform_store_id='2', currency='USD', timezone='Asia/Manila',
        date='2026-10-01', cost='0.10', gross_revenue='1.00', orders=2, **values)


def test_exact_sum_and_weighted_ratio():
    a = row()
    b = {**a, 'date': '2026-10-02', 'cost': '0.20', 'orders': 1}
    result = overview([a, b], date(2026, 10, 1), date(2026, 10, 2))[0]
    assert result['cost'] == '0.30'
    assert result['roi'] == '6.67'
    assert result['cost_per_order'] == '0.10'
    assert result['complete']


def test_missing_is_not_zero():
    result = overview([row()], date(2026, 10, 1), date(2026, 10, 2))[0]
    assert not result['complete'] and result['stored_days'] == 1
    assert overview(None, date(2026, 10, 1), date(2026, 10, 2)) is None
    assert overview([], date(2026, 10, 1), date(2026, 10, 2)) == []


def test_currency_identity_timezone_separated():
    a = row()
    rows = [a, {**a, 'currency': 'PHP'}, {**a, 'platform_store_id': '3'},
            {**a, 'timezone': 'Asia/Bangkok'}, {**a, 'advertiser_id': '4'}]
    assert len(overview(rows, date(2026, 10, 1), date(2026, 10, 1))) == 5


def test_duplicate_fails_closed_and_zero_denominator():
    a = row()
    result = overview([a, a], date(2026, 10, 1), date(2026, 10, 1))[0]
    assert result['conflict'] and result['cost'] is None and not result['complete']
    result = overview([{**a, 'cost': '0', 'orders': 0}], date(2026, 10, 1), date(2026, 10, 1))[0]
    assert result['roi'] is None and result['cost_per_order'] is None


def subject(advertiser='1', **kwargs):
    return dict(store_code='TK1PH', advertiser_id=advertiser, currency='USD',
                mapping_timezone='Asia/Manila', historical_binding_confirmed=True, **kwargs)


def test_shop_sums_accounts_and_recomputes_ratios():
    a = row()
    b = {**a, 'advertiser_id': '2', 'cost': '0.90', 'gross_revenue': '2', 'orders': 1}
    result = shop_overview([a, b], [subject(), subject('2')], date(2026, 10, 1), date(2026, 10, 1))[0]
    assert result['cost'] == '1.00' and result['roi'] == '3.00'
    assert result['cost_per_order'] == '0.33' and result['complete']
    assert result['advertiser_count'] == 2


def test_shop_missing_account_not_complete_and_unproven_binding_excluded():
    args = (date(2026, 10, 1), date(2026, 10, 1))
    result = shop_overview([row()], [subject(), subject('2')], *args)[0]
    assert not result['complete'] and result['expected_days'] == 2
    assert shop_overview([row()], [{**subject(), 'historical_binding_confirmed': False}], *args) == []
    assert shop_overview(None, [subject()], *args) is None


def test_shop_separates_dimensions_and_duplicate_conflict():
    a = row()
    data = [a, {**a, 'currency': 'PHP'}, {**a, 'timezone': 'Asia/Bangkok'}, {**a, 'platform_store_id': '3'}]
    args = (date(2026, 10, 1), date(2026, 10, 1))
    assert len(shop_overview(data, [subject()], *args)) == 4
    result = shop_overview([a, a], [subject()], *args)[0]
    assert result['conflict'] and result['cost'] is None and not result['complete']
