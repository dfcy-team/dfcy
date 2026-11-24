from decimal import Decimal
import pytest
from rest_framework.exceptions import ValidationError
from apps.supply_chain.receipt_difference_history import allocation_plan


def test_partial_history_preserves_unrelated_amount():
    reduction, remaining = allocation_plan({'receipt_difference_allocations': {'line:1': '2420', 'line:2': '500'}}, ['line:1'], '3000')
    assert reduction == Decimal('2420')
    assert remaining == {'line:2': '500'}
    assert Decimal('3000')-reduction == Decimal('580')


def test_unattributed_history_is_not_automatically_reversed():
    with pytest.raises(ValidationError):
        allocation_plan({}, ['line:1'], '2420')


def test_repeated_adjustment_cannot_reduce_history_again():
    with pytest.raises(ValidationError):
        allocation_plan({'receipt_difference_allocations': {}}, ['line:1'], '580')


def test_allocation_exceeding_history_rejected():
    with pytest.raises(ValidationError):
        allocation_plan({'receipt_difference_allocations': {'line:1':'100'}}, ['line:1'], '50')
