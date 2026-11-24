from decimal import Decimal

from apps.supply_chain.payment_fx import effective_snapshot, snapshot


def test_original_positive_fx_snapshot_validation():
    assert snapshot('CNY', '12.34565') == (Decimal('1'), Decimal('12.3457'))
    assert snapshot('USD', '2.5', '7.12345678') == (
        Decimal('7.12345678'), Decimal('17.8086'))


def test_implicit_cny_legacy_derivation_rounds_half_up():
    assert effective_snapshot('CNY', '1.23445', None, None) == (
        Decimal('1'), Decimal('1.2345'))
    assert effective_snapshot('CNY', '-1.23445', None, None) == (
        Decimal('1'), Decimal('-1.2345'))
    assert effective_snapshot('CNY', '0', None, None) == (
        Decimal('1'), Decimal('0.0000'))


def test_implicit_cny_large_precision_uses_local_context():
    amount = '123456789012345678901234567890.12345'
    assert effective_snapshot('CNY', amount, None, None) == (
        Decimal('1'), Decimal('123456789012345678901234567890.1235'))


def test_explicit_pair_is_returned_unchanged():
    stored_rate = Decimal('7.1')
    stored_amount = Decimal('10.25')
    assert effective_snapshot('USD', '999', stored_rate, stored_amount) == (
        stored_rate, stored_amount)


def test_partial_pair_is_preserved_without_healing():
    assert effective_snapshot('CNY', '3', Decimal('1'), None) == (Decimal('1'), None)
    assert effective_snapshot('USD', '3', None, Decimal('21')) == (None, Decimal('21'))


def test_unknown_currency_and_invalid_legacy_amount_stay_empty():
    assert effective_snapshot('EUR', '3', None, None) == (None, None)
    assert effective_snapshot('', '3', None, None) == (None, None)
    assert effective_snapshot('CNY', 'NaN', None, None) == (None, None)


def test_legacy_helper_does_not_mutate_inputs():
    values = ['CNY', '1.23445', None, None]
    original = list(values)
    effective_snapshot(*values)
    assert values == original