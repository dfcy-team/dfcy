from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rest_framework.exceptions import ValidationError

from tests.test_order_field_enrichment import adapter_for, shopee_record
from tests.test_shopee_readonly_runtime import configured


def test_split_packages_query_their_own_tracking_and_exclude_collection_secrets():
    from apps.integrations.shopee_logistics import collect_order_logistics
    queries = []

    def request(path, query):
        queries.append((path, query))
        if path.endswith('get_tracking_number'):
            return {'response': {'tracking_number': 'TRACK-' + query['package_number'], 'pickup_code': 'PRIVATE-PIN'}}
        return {'response': {**query, 'logistics_status': 'LOGISTICS_DELIVERY_DONE',
            'collection_pin_code': 'PRIVATE-PIN', 'tracking_info': [
                {'update_time': 1788174000, 'description': 'Synthetic event', 'return_code': 'PRIVATE-PIN'}]}}

    client = SimpleNamespace(_request=request, now=lambda: SimpleNamespace(isoformat=lambda: '2026-09-01T00:00:00Z'))
    facts, raw = collect_order_logistics(client, {'order_sn': 'ORDER', 'split_up': True,
        'package_list': [{'package_number': 'PKG-1'}, {'package_number': 'PKG-2'}]})
    assert len(queries) == 4
    assert [row['tracking_number'] for row in facts['packages']] == ['TRACK-PKG-1', 'TRACK-PKG-2']
    assert facts['packages'][0]['events'][0]['occurred_at_utc'].endswith('+00:00')
    assert 'PRIVATE-PIN' not in str((facts, raw))


def test_split_order_without_package_identity_is_not_queried_as_a_whole_order():
    from apps.integrations.shopee_logistics import collect_order_logistics
    client = SimpleNamespace(_request=Mock(), now=lambda: SimpleNamespace(isoformat=lambda: '2026-09-01T00:00:00Z'))
    facts, _ = collect_order_logistics(client, {'order_sn': 'ORDER', 'split_up': True})
    assert facts['status'] == 'missing_package_identity'
    client._request.assert_not_called()


def test_logistics_is_opt_in_and_stays_in_the_existing_order_page(monkeypatch):
    client, _ = configured(monkeypatch, {})
    raw = shopee_record()
    paths = []

    def request(path, query):
        paths.append(path)
        if path in {client.ORDER_LIST_PATH, client.ORDER_DETAIL_PATH}:
            return {'response': {'order_list': [raw]}}
        return {'response': {'order_sn': raw['order_sn'], 'package_number': 'SYNTHETIC-PACKAGE',
            'tracking_number': 'SYNTHETIC-TRACK', 'tracking_info': []}}

    monkeypatch.setattr(client, '_request', request)
    scope = {'time_from': 1, 'time_to': 2, 'page_size': 100}
    client.fetch_orders('', scope)
    assert len(paths) == 2
    page = client.fetch_orders('', {**scope, 'include_logistics': True})
    assert page['records'][0]['_platform_logistics']['status'] == 'ok'
    normalized = adapter_for().normalize_record(page['records'][0])
    assert normalized['observed_fields']['platform_logistics']['packages'][0]['tracking_number'] == 'SYNTHETIC-TRACK'


def test_reverse_logistics_keeps_buyer_and_post_return_segments_separate():
    from apps.integrations.shopee_logistics import collect_return_logistics
    client = SimpleNamespace(_request=Mock(return_value={'response': {
        'return_sn': 'RETURN', 'validation_type': 'warehouse_validation',
        'reverse_logistics_status': 'LOGISTICS_DELIVERY_DONE', 'tracking_number': 'BUYER-TRACK',
        'tracking_info': [{'update_time': 1788174000, 'tracking_description': 'Buyer parcel arrived'}],
        'rts_tracking_number': 'SELLER-TRACK', 'post_return_logistics_status': 'IN_TRANSIT',
        'post_return_logistics_tracking_info': [], 'collection_pin_code': 'PRIVATE-PIN'}}),
        now=lambda: SimpleNamespace(isoformat=lambda: '2026-09-01T00:00:00Z'))
    facts, raw = collect_return_logistics(client, 'RETURN')
    assert facts['buyer_return']['tracking_number'] == 'BUYER-TRACK'
    assert facts['post_return']['tracking_number'] == 'SELLER-TRACK'
    assert 'PRIVATE-PIN' not in str((facts, raw))
    assert 'received_quantity' not in str(facts)


def test_wrong_order_identity_fails_closed():
    from apps.integrations.shopee_logistics import collect_order_logistics
    client = SimpleNamespace(_request=Mock(return_value={'response': {'order_sn': 'WRONG', 'tracking_info': []}}),
        now=lambda: SimpleNamespace(isoformat=lambda: '2026-09-01T00:00:00Z'))
    with pytest.raises(ValidationError, match='identity'):
        collect_order_logistics(client, {'order_sn': 'ORDER'})


@pytest.mark.parametrize('value', ['true', 1, None])
def test_logistics_policy_requires_a_real_boolean(value):
    from apps.integrations.views import _validated_job_policy
    with pytest.raises(ValidationError):
        _validated_job_policy({'include_logistics': value})


@pytest.mark.django_db
def test_reverse_snapshot_is_scoped_to_its_order_and_does_not_receive_inventory():
    from apps.commerce.models import InventorySnapshot
    from apps.integrations.adapters import MarketplaceRefundAdapter
    from apps.sales_management.serializers import SalesReturnSerializer
    from apps.sales_management.services import upsert_normalized_refund
    from apps.sales_management.aftersales_models import AftersalesCase, ReturnAllocation
    from tests.test_sales_management import NOW, create_scope, create_order, create_run

    tenant, _, store, _ = create_scope('reverse-logistics')
    order = create_order(tenant, store, 'reverse-logistics')
    run = create_run(tenant, 'refund_return', 'reverse-logistics')
    adapter = MarketplaceRefundAdapter(SimpleNamespace(platform='shopee', platform_config={}))
    adapter.authorization = SimpleNamespace(store=store, region='PH')
    raw = {'return_sn': 'RETURN', 'order_sn': order.external_order_id, 'return_solution': 0,
           'create_time': int(NOW.timestamp()), 'update_time': int(NOW.timestamp()), 'status': 'ACCEPTED',
           '_platform_logistics': {'status': 'ok', 'return_sn': 'RETURN', 'collected_at_utc': NOW.isoformat(),
                                  'buyer_return': {'tracking_number': 'BUYER-TRACK', 'status': 'LOGISTICS_DELIVERY_DONE'},
                                  'collection_pin_code': 'PRIVATE-PIN'}}
    refund = upsert_normalized_refund(tenant=tenant, source_run=run, payload=adapter.normalize_record(raw))
    data = SalesReturnSerializer(refund).data
    assert data['platform_logistics']['buyer_return']['tracking_number'] == 'BUYER-TRACK'
    assert 'PRIVATE-PIN' not in str(data)
    case = AftersalesCase.objects.get(refund=refund)
    assert case.return_status != 'received'
    assert not ReturnAllocation.objects.exists() and not InventorySnapshot.objects.exists()
    # An unmatched return remains in RAW/canonical ingestion, never assigned to a different order.
    raw.update(return_sn='UNMATCHED', order_sn='MISSING-ORDER')
    raw['_platform_logistics']['return_sn'] = 'UNMATCHED'
    unmatched = upsert_normalized_refund(tenant=tenant, source_run=run, payload=adapter.normalize_record(raw))
    assert SalesReturnSerializer(unmatched).data['platform_logistics'] is None
    order.refresh_from_db()
    assert set(order.source_details['platform_return_logistics']) == {'RETURN'}


def test_scope_and_checkpoint_change_when_logistics_is_requested():
    from apps.integrations.readonly_clients import default_sync_scope, ShopeeReadonlyClient
    from apps.integrations.views import _set_job_scope
    config = SimpleNamespace(platform='shopee', platform_config={})
    scope = default_sync_scope(config, {'include_logistics': True}, 'sales_order')
    assert scope['include_logistics'] is True and scope['page_size'] == 4
    a = {'time_from': 1, 'time_to': 2}
    assert ShopeeReadonlyClient._detail_scope_fingerprint(a, 'returns', 4) != (
        ShopeeReadonlyClient._detail_scope_fingerprint({**a, 'include_logistics': True}, 'returns', 4))
    job = SimpleNamespace(integration_config=SimpleNamespace(platform='lazada'), resource_type='sales_order')
    with pytest.raises(ValidationError):
        _set_job_scope(job, {'include_logistics': True})


def test_provider_failure_is_explicit_and_never_replaced_with_fake_tracking():
    from apps.integrations.shopee_logistics import collect_order_logistics
    client = SimpleNamespace(_request=Mock(side_effect=ValidationError('Private provider error')),
        now=lambda: SimpleNamespace(isoformat=lambda: '2026-09-01T00:00:00Z'))
    facts, _ = collect_order_logistics(client, {'order_sn': 'ORDER'})
    assert facts['status'] == 'partial'
    assert facts['packages'][0]['number_query_status'] == 'unavailable'
    assert 'tracking_number' not in facts['packages'][0]
    assert 'Private provider error' not in str(facts)
