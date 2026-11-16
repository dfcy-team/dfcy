from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rest_framework.exceptions import ValidationError


def test_trace_contract_maps_packages_and_actual_event_time_without_private_fields():
    from apps.integrations.lazada_logistics import collect_order_logistics
    response = {'result': {'success': True, 'module': [{'package_detail_info_list': [{
        'ofc_package_id': 'PKG', 'tracking_number': 'TRACK', 'logistic_detail_info_list': [{
            'title': 'Delivered', 'description': 'Delivered parcel', 'status_code': 'DELIVERED',
            'event_time': 1788174000000, 'receive_time': 1788175000000, 'proof_images': ['PRIVATE']}]}]}]}}
    client = SimpleNamespace(_request=Mock(return_value=response), now=lambda: datetime(2026,9,1,tzinfo=UTC))
    facts, traces = collect_order_logistics(client, {'order_id': '123'})
    client._request.assert_called_once_with('/rest/logistic/order/trace', {'order_id': '123'})
    assert facts['packages'][0]['package_number'] == 'PKG'
    assert facts['packages'][0]['events'][0]['occurred_at_utc'] == datetime.fromtimestamp(1788174000, UTC).isoformat()
    assert 'PRIVATE' not in str((facts,traces))
    assert 'completed_at_utc' not in facts


@pytest.mark.parametrize('result', [{'success': False}, {}, {'success': True, 'module': {}},
    {'success': True, 'module': [{'package_detail_info_list': [{'tracking_number': 'T'}]}]}])
def test_bad_trace_is_not_silently_an_empty_success(result):
    from apps.integrations.lazada_logistics import collect_order_logistics
    client = SimpleNamespace(_request=Mock(return_value={'result':result}), now=lambda: datetime(2026,9,1,tzinfo=UTC))
    with pytest.raises(ValidationError): collect_order_logistics(client, {'order_id':'123'})


@pytest.mark.parametrize('event', [{}, {'event_time': 1788174000000},
    {'event_time': True, 'description': 'Delivered', 'status_code': 'DELIVERED'},
    {'event_time': 1788174000000, 'description': {}, 'status_code': 'DELIVERED'},
    {'event_time': 1788174000000, 'description': 'Delivered', 'status_code': None}])
def test_invalid_lazada_event_does_not_advance_order_page(event):
    from apps.integrations.readonly_clients import LazadaReadonlyClient
    c = LazadaReadonlyClient(SimpleNamespace(platform='lazada', platform_config={}), SimpleNamespace(), custody=object())
    c._runtime_path = lambda key, fallback: fallback
    c._request = Mock(side_effect=[{'data': {'countTotal': 2, 'orders': [{'order_id': '123'}]}},
        {'data': [{'order_id': '123', 'order_item_id': '1'}]},
        {'result': {'success': True, 'module': [{'package_detail_info_list': [{
            'ofc_package_id': 'PKG', 'logistic_detail_info_list': [event]}]}]}}])
    with pytest.raises(ValidationError):
        c.fetch_orders('', {'time_from': 1788170000, 'time_to': 1788171000,
                           'page_size': 1, 'include_logistics': True})


def test_lazada_item_packages_and_trace_survive_normalization():
    from tests.test_order_field_enrichment import adapter_for
    raw={'order_id':'123','statuses':['shipped'],'created_at':'2026-09-01T00:00:00Z',
         'updated_at':'2026-09-01T01:00:00Z','price':'80','order_items':[
         {'order_id':123,'order_item_id':'1','sku':'SKU','item_price':'80','paid_price':'80',
          'package_id':'PKG','tracking_code':'TRACK','shipment_provider':'Carrier','status':'shipped'}],
         '_platform_logistics':{'status':'ok','packages':[{'package_number':'PKG','tracking_number':'TRACK','events':[]}]}}
    data=adapter_for('lazada').normalize_record(raw)['observed_fields']
    assert data['packages'][0]['package_id']=='PKG'
    assert data['packages'][0]['tracking_number']=='TRACK'
    assert data['shipping_carrier']=='Carrier'
    assert data['packages'][0]['items'][0]['order_item_id']=='1'
    assert data['platform_logistics']['packages'][0]['tracking_number']=='TRACK'
    assert 'completed_at_utc' not in data


@pytest.mark.parametrize('wrong_identity', [False, True])
def test_order_sync_opt_in_trace_and_cross_order_rejection(wrong_identity):
    from apps.integrations.readonly_clients import LazadaReadonlyClient
    client = LazadaReadonlyClient(SimpleNamespace(platform='lazada', platform_config={}),
        SimpleNamespace(), custody=object())
    client._runtime_path = lambda key, fallback: fallback
    client._request = Mock(side_effect=[
        {'data': {'countTotal': 1, 'orders': [{'order_id': '123'}]}},
        {'data': [{'order_id': 'other' if wrong_identity else 123, 'order_item_id': 'L1'}]},
        {'result': {'success': True}},
    ])
    scope = {'time_from': 1788170000, 'time_to': 1788171000,
             'page_size': 1, 'include_logistics': True}
    if wrong_identity:
        with pytest.raises(ValidationError):
            client.fetch_orders('', scope)
        assert client._request.call_count == 2
    else:
        page = client.fetch_orders('', scope)
        assert page['records'][0]['_platform_logistics']['packages'] == []
        assert page['raw_responses'][-1]['endpoint'] == '/rest/logistic/order/trace'
