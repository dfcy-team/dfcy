from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections, connection
from rest_framework.exceptions import ValidationError

from apps.sales_management.aftersales import allocate_line, ingest_receipt
from apps.sales_management.aftersales_models import ReturnAllocation
from tests.test_order_aftersales import case_data, receipt


pytestmark = pytest.mark.django_db(transaction=True)


def simultaneous(operation):
    barrier = Barrier(2)

    def invoke(index):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            operation(index)
            return 'allocated'
        except ValidationError:
            return 'conflict'
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(invoke, range(2)))


def test_same_receipt_version_can_only_allocate_once(case_data):
    if connection.vendor != 'mysql':
        pytest.skip('Requires actual MySQL row locks.')
    user, warehouse, order, case = case_data
    row, _ = ingest_receipt(user, warehouse, receipt(order, warehouse, quantity=2), auto_match=False)
    line = row.lines.get()
    result = simultaneous(lambda _: allocate_line(user, line.pk, case, 'SKU-aftersales', 2,
        reason='并发核对实收', expected_version=row.version))
    assert sorted(result) == ['allocated', 'conflict']
    assert ReturnAllocation.objects.get(case=case).quantity == 2


def test_two_receipts_cannot_overallocate_the_same_order(case_data):
    if connection.vendor != 'mysql':
        pytest.skip('Requires actual MySQL row locks.')
    user, warehouse, order, case = case_data
    receipts = [ingest_receipt(user, warehouse, receipt(order, warehouse, quantity=2, number=f'R-{index}'),
                               auto_match=False)[0] for index in range(2)]
    lines = [row.lines.get() for row in receipts]
    result = simultaneous(lambda index: allocate_line(user, lines[index].pk, case, 'SKU-aftersales', 2,
        reason='两单并发核对实收', expected_version=receipts[index].version))
    assert sorted(result) == ['allocated', 'conflict']
    assert ReturnAllocation.objects.get(case=case).quantity == 2
