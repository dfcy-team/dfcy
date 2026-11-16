from apps.integrations.order_field_mapping import enrich_order_fields, timestamp


def test_official_order_fields_keep_deadlines_and_completion_separate():
    raw = {'status': 'COMPLETED', 'paid_time': 1788170000,
           'collection_time': 1788171000, 'delivery_time': 1788172000,
           'rts_time': 1788170500, 'update_time': 1788173000,
           'complete_time': 1788173000, 'collection_due_time': 1788190000,
           'payment_method_name': 'COD', 'shipping_provider': 'Carrier',
           'is_buyer_request_cancel': False,
           'packages': [{'id': 'P1'}, {'id': 'P2'}],
           'line_items': [{'id': 'L1', 'package_id': 'P1', 'tracking_number': 'T1'},
                          {'id': 'L2', 'package_id': 'P2', 'tracking_number': 'T2'}]}
    observed = enrich_order_fields('tiktok', raw, {'lines': []})['observed_fields']
    assert observed['platform_pickup_at_utc'] == timestamp(raw['collection_time'])
    assert observed['platform_delivered_at_utc'] == timestamp(raw['delivery_time'])
    assert observed['paid_at_utc'] == timestamp(raw['paid_time'])
    assert 'completed_at_utc' not in observed
    assert observed['payment_method'] == 'COD'
    assert observed['shipping_carrier'] == 'Carrier'
    assert observed['is_buyer_request_cancel'] is False
    assert observed['packages'] == [
        {'package_id': 'P1', 'tracking_number': 'T1', 'items': [{'order_item_id': 'L1'}]},
        {'package_id': 'P2', 'tracking_number': 'T2', 'items': [{'order_item_id': 'L2'}]}]


def test_missing_times_and_cancel_request_do_not_become_cancel_event():
    observed = enrich_order_fields('tiktok', {'status': 'AWAITING_SHIPMENT',
        'is_buyer_request_cancel': True, 'collection_due_time': 1788190000}, {})['observed_fields']
    assert not any(key.endswith('_at_utc') for key in observed)


def test_tiktok_times_reach_detail_and_log_without_faking_completion():
    from types import SimpleNamespace
    from apps.sales_management.serializers import SalesOrderDetailSerializer
    from apps.sales_management.order_presentation import factual_events
    details = enrich_order_fields('tiktok', {'collection_time': 1788171000,
        'rts_time': 1788170000, 'delivery_time': 1788172000}, {})['observed_fields']
    order = SimpleNamespace(source_details=details, created_at_utc=None)
    assert SalesOrderDetailSerializer().get_order_observations(order)['platform_delivered_at_utc']
    assert {event['title'] for event in factual_events(order)} == {'平台揽收', '平台安排发货', '平台妥投'}
