"""Business-payload tests only; these do not simulate verified HTTP callbacks."""
from copy import deepcopy

import pytest
from rest_framework.exceptions import ValidationError

from apps.integrations.best_business import putaway_receipt, return_receipt
from tests.test_best_warehouse_business import authorization, returned
from tests.test_order_aftersales import case_data


def payload():
    return {'customerCode': 'TEST-CUSTOMER', 'warehouseCode': 'BEST-PH', 'orderCode': 'RMA-1',
        'feedBackStage': 'putaway', 'rmaStatus': 'FULFILLED',
        'receiveTime': '2026-09-03T12:00:00+08:00',
        'wmsUpdateTime': '2026-09-04T01:00:00+08:00',
        'products': {'product': {'itemSkuCode': 'SKU-A', 'normalQuantity': '2', 'defectiveQuantity': '1'}}}


def test_putaway_uses_completion_not_receipt_time():
    result = putaway_receipt(payload(), authorization())
    assert result['received_at'] == '2026-09-03T17:00:00+00:00'
    assert result['lines'] == [{'sku': 'SKU-A', 'received_quantity': 3}]
    assert result['platform_order_no'] == result['erp_no'] == result['tracking_no'] == ''


@pytest.mark.parametrize('field,value', [
    ('customerCode', 'OTHER'), ('warehouseCode', 'OTHER'), ('orderCode', ''),
    ('feedBackStage', 'receive'), ('rmaStatus', 'CANCELED'), ('rmaStatus', 'WMS_ACCEPT'),
    ('wmsUpdateTime', None), ('wmsUpdateTime', ''), ('wmsUpdateTime', 'invalid'),
    ('wmsUpdateTime', '2026-09-04 01:00:00'), ('products', {}),
])
def test_incomplete_or_conflicting_putaway_cannot_date_costs(field, value):
    data = payload()
    data[field] = value
    with pytest.raises(ValidationError):
        putaway_receipt(data, authorization())


@pytest.mark.parametrize('quantity', [None, '', '-1', '0.5', 'NaN', True])
def test_putaway_does_not_invent_or_truncate_quantity(quantity):
    data = payload()
    data['products']['product']['normalQuantity'] = quantity
    with pytest.raises(ValidationError):
        putaway_receipt(data, authorization())


@pytest.mark.django_db
def test_putaway_business_payload_repeat_and_later_query_keep_completion(case_data):
    from apps.sales_management.aftersales import ingest_receipt
    from apps.sales_management.aftersales_models import WarehouseReturnReceipt, ReturnAllocation
    user, warehouse, _, case = case_data
    case.warehouse, case.warehouse_return_no, case.expectation_reviewed = warehouse, 'RMA-1', True
    case.save()
    data = payload()
    data['products']['product'].update(itemSkuCode='SKU-aftersales', normalQuantity='2', defectiveQuantity='0')
    normalized = putaway_receipt(data, authorization())
    receipt, created = ingest_receipt(user, warehouse, normalized, source='api')
    version = receipt.version
    for _ in range(2):
        receipt, created = ingest_receipt(user, warehouse, deepcopy(normalized), source='api')
        assert not created
        assert receipt.version == version
    query = returned()
    query['rma']['products']['product'].update(skuCode='SKU-aftersales', normalQuantity='2', defectiveQuantity='0')
    receipt, _ = ingest_receipt(user, warehouse, return_receipt(query, 'RMA-1'), source='api')
    assert receipt.received_at.isoformat() == normalized['received_at']
    assert WarehouseReturnReceipt.objects.count() == 1
    assert ReturnAllocation.objects.get(case=case).quantity == 2
