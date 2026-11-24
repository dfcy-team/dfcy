from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from rest_framework.exceptions import ValidationError

from apps.supply_chain import payment_batches


def check(lines, batch_rate=None, batch_cny=None, currency='CNY'):
    batch = SimpleNamespace(currency=currency, exchange_rate=None if batch_rate is None else Decimal(batch_rate), cny_amount=None if batch_cny is None else Decimal(batch_cny))
    with patch.object(payment_batches.costs, '_payment_owner', return_value=object()), \
         patch.object(payment_batches.costs, 'validate_payment_currency'), \
         patch.object(payment_batches, '_source_batch_currency', return_value=currency):
        return payment_batches._batch_auth_currency(object(), batch, lines)


def line(amount, rate=None, cny=None, currency='CNY'):
    return SimpleNamespace(kind='shipment', source_id=1, amount=Decimal(amount), currency=currency,
                           exchange_rate=None if rate is None else Decimal(rate),
                           cny_amount=None if cny is None else Decimal(cny))


def test_legacy_all_null_cny_batch_authorizes():
    assert check([line('10'), line('20')]) == 'CNY'


def test_mixed_implicit_and_explicit_cny_pairs_authorize():
    assert check([line('10'), line('20', '1', '20')], '1', '30') == 'CNY'


@pytest.mark.parametrize('br,bc,lines', [
    (None, '10', [line('10')]),
    ('1', None, [line('10')]),
])
def test_partial_batch_snapshot_rejected(br, bc, lines):
    with pytest.raises(ValidationError):
        check(lines, None if br is None else Decimal(br), None if bc is None else Decimal(bc))


def test_partial_line_snapshot_rejected():
    with pytest.raises(ValidationError):
        check([line('10', '1', None)])


def test_explicit_foreign_snapshot_unchanged():
    assert check([line('2', '7', '14', 'USD')], '7', '14', 'USD') == 'USD'


def test_mismatched_line_cny_rejected():
    with pytest.raises(ValidationError):
        check([line('10', '1', '11')], '1', '10')


def test_authorization_does_not_mutate_snapshot_fields():
    row = line('10')
    before = (row.exchange_rate, row.cny_amount)
    check([row])
    assert (row.exchange_rate, row.cny_amount) == before
