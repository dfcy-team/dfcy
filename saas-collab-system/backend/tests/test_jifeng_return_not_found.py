from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rest_framework.exceptions import ValidationError

from apps.integrations.readonly_clients import JifengWmsReadonlyClient


@pytest.mark.parametrize('code', [40025, '40025'])
def test_saved_provider_not_found_code_is_not_a_receipt(code):
    client = JifengWmsReadonlyClient.__new__(JifengWmsReadonlyClient)
    client.authorization = SimpleNamespace(external_warehouse_code='TEST-PH')
    client._signed_post = Mock(return_value={'code': code, 'data': None})
    with pytest.raises(ValidationError) as caught:
        client.fetch_return_detail(tracking_no='TEST-TRACK')
    assert caught.value.get_codes() == ['return_not_found']


def test_other_provider_failure_is_not_classified_as_missing_return():
    client = JifengWmsReadonlyClient.__new__(JifengWmsReadonlyClient)
    client.authorization = SimpleNamespace(external_warehouse_code='TEST-PH')
    client._signed_post = Mock(return_value={'code': 401, 'data': None})
    with pytest.raises(ValidationError) as caught:
        client.fetch_return_detail(tracking_no='TEST-TRACK')
    assert caught.value.get_codes() != ['return_not_found']


@pytest.mark.parametrize('status,finish,expected', [
    (1, '2026-11-05 01:01:25', '2026-11-04T17:01:25+00:00'),
    (1, '2026-11-05T01:01:25+07:00', '2026-11-04T18:01:25+00:00'),
    (1, '', None), (4, '2026-11-05 01:01:25', None),
    (2, '2026-11-05 01:01:25', None),
])
def test_successful_inbound_time_only(status, finish, expected):
    client = JifengWmsReadonlyClient.__new__(JifengWmsReadonlyClient)
    client.authorization = SimpleNamespace(external_warehouse_code='TEST-PH')
    client._signed_post = Mock(return_value={'code': 0, 'data': {
        'returnId': 'RETURN-1', 'trackingNo': 'TRACK', 'warehouseCode': 'TEST-PH',
        'status': status, 'finishTime': finish, 'createTime': '2026-10-01 10:00:00',
        'skuList': [{'sku': 'SKU', 'receiveCount': 1}]}})
    assert client.fetch_return_detail(tracking_no='TRACK')['received_at'] == expected
