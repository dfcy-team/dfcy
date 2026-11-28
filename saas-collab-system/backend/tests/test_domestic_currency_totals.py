from decimal import Decimal as D
from apps.supply_chain.domestic_currency_totals import aggregate_money, serialise_money


def test_independent_units_never_become_a_numeric_combined_total():
    result = aggregate_money([{'currency': 'CNY', 'due': D('10')}, {'currency': 'PHP', 'due': D('10')}], ['due'])
    assert result['due'] is None
    assert result['currency'] is None and result['mixed_currency'] is True
    assert serialise_money(result)['totals_by_currency'] == {'CNY': {'due': '10'}, 'PHP': {'due': '10'}}


def test_known_unit_sums_exact_decimal_values_and_zero_is_not_unknown():
    result = aggregate_money([{'currency': 'PHP', 'due': D('0.1')}, {'currency': 'PHP', 'due': D('0.2')}], ['due'])
    assert result['due'] == D('0.3') and result['currency'] == 'PHP'
    assert aggregate_money([], ['due'])['due'] == D('0')


def test_missing_or_invalid_nonzero_units_fail_closed_even_with_known_currency():
    for unit in (None, 'php', 'BAD1'):
        result = aggregate_money([{'currency': 'PHP', 'due': D('10')}, {'currency': unit, 'due': D('3')}], ['due'])
        assert result['due'] is None and result['currency'] is None
        assert result['unknown_currency_documents'] == 1
        assert result['totals_by_currency']['UNKNOWN']['due'] is None


def test_all_unknown_draft_due_remains_unknown_while_known_paid_zero_is_zero():
    result = aggregate_money([{'currency': 'PHP', 'due': None, 'paid': D('0')}], ['due', 'paid'])
    assert result['due'] is None and result['paid'] == D('0')


def test_mixed_unit_totals_do_not_depend_on_input_order():
    rows = [{'currency': 'CNY', 'due': D('5')}, {'currency': 'PHP', 'due': D('2')}]
    assert aggregate_money(rows, ['due']) == aggregate_money(list(reversed(rows)), ['due'])


def test_unresolved_nonzero_unit_survives_party_rollup_then_global_rollup():
    unknown_party = aggregate_money([{'currency': None, 'due': D('10')}], ['due'])
    global_total = aggregate_money([unknown_party, {'currency': 'PHP', 'due': D('5')}], ['due'])
    assert unknown_party['due'] is None and unknown_party['unresolved_currency_nonzero'] is True
    assert global_total['due'] is None and global_total['currency'] is None


def test_nested_unknown_currency_counts_documents_not_party_buckets():
    party = aggregate_money([{'currency': None, 'due': D('1')}, {'currency': None, 'due': D('2')}], ['due'])
    card = aggregate_money([party], ['due'])
    assert party['unknown_currency_documents'] == card['unknown_currency_documents'] == 2
