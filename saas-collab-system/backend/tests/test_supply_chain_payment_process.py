from decimal import Decimal
from apps.supply_chain.payment_process import annotate_process


def test_process_orders_by_registration_and_reverses_cash_without_erasing_history():
    entries = [
        {'id': 2, 'entry_type': 'payment', 'amount': '30', 'date': '2020-01-01', 'recorded_at': '2026-10-02', 'is_reversal': True},
        {'id': 1, 'entry_type': 'payment', 'amount': '30', 'date': '2026-10-01', 'recorded_at': '2026-10-01', 'reversed': True},
        {'id': 'opening', 'entry_type': 'opening', 'amount': '10'},
        {'id': 3, 'entry_type': 'application', 'amount': '20', 'recorded_at': '2026-10-03'},
    ]
    rows = annotate_process(entries, Decimal('100'), 'shipment')
    assert [r['remaining_after'] for r in rows] == ['90.0000','60.0000','90.0000','70.0000']
    assert rows[-1]['paid_after'] == '10.0000'
    assert rows[-1]['applied_after'] == '20.0000'
    assert rows[2]['cash_change'] == '-30.0000'


def test_deposit_usage_changes_available_not_purchase_cash_or_unpaid():
    rows = annotate_process([
        {'id': 1, 'entry_type': 'payment', 'amount': '50', 'recorded_at': '1'},
        {'id': 2, 'entry_type': 'application', 'amount': '30', 'recorded_at': '2'},
        {'id': 3, 'entry_type': 'application', 'amount': '30', 'recorded_at': '3', 'is_reversal': True},
    ], Decimal('100'), 'purchase')
    assert [r['remaining_after'] for r in rows] == ['50.0000'] * 3
    assert [r['available_after'] for r in rows] == ['50.0000','20.0000','50.0000']


def test_unknown_payable_does_not_invent_balance():
    row = annotate_process([{'id': 1,'entry_type':'payment','amount':'2'}], None, 'shipment')[0]
    assert row['remaining_after'] is None
    assert row['paid_after'] == '2.0000'
