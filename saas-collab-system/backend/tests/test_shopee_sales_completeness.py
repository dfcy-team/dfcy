from types import SimpleNamespace

import pytest
from rest_framework.exceptions import ValidationError

from apps.integrations.adapters import MarketplaceRefundAdapter
from tests.test_order_field_enrichment import adapter_for, shopee_record
from tests.test_shopee_readonly_runtime import configured


def test_order_requests_operational_facts_without_sensitive_buyer_fields(monkeypatch):
    client, _ = configured(monkeypatch, {})
    queries = []

    def request(path, query):
        queries.append(query)
        return {'response': {'order_list': [{'order_sn': 'SYNTHETIC-ORDER'}]}}

    monkeypatch.setattr(client, '_request', request)
    client.fetch_orders('', {'time_from': 1, 'time_to': 2, 'page_size': 20})
    fields = set(queries[1]['response_optional_fields'].split(','))
    assert {'pay_time', 'pickup_done_time', 'actual_shipping_fee', 'estimated_shipping_fee',
            'actual_shipping_fee_confirmed', 'fulfillment_flag', 'cancel_reason', 'package_list'} <= fields
    assert not fields & {'buyer_username', 'buyer_user_id', 'recipient_address', 'invoice_data'}


@pytest.mark.parametrize('returned', [[], [{'order_sn': 'DIFFERENT-ORDER'}]])
def test_missing_order_details_do_not_advance_as_success(monkeypatch, returned):
    client, _ = configured(monkeypatch, {})
    monkeypatch.setattr(client, '_request', lambda path, query: {'response': {'order_list':
        [{'order_sn': 'SYNTHETIC-ORDER'}] if path == client.ORDER_LIST_PATH else returned}})
    with pytest.raises(ValidationError, match='incomplete'):
        client.fetch_orders('', {'time_from': 1, 'time_to': 2, 'page_size': 20})


def test_platform_pickup_deadline_booking_and_package_items_are_distinct():
    raw = shopee_record()
    raw.update(pickup_done_time=1788174000, ship_by_date=1788260400, booking_sn='AAS-SYNTHETIC',
               actual_shipping_fee=12, estimated_shipping_fee=10, actual_shipping_fee_confirmed=False,
               fulfillment_flag='fulfilled_by_cb_seller')
    raw['package_list'][0]['item_list'] = [{'item_id': 123, 'model_id': 456, 'model_quantity': 2,
                                          'order_item_id': 123, 'private_field': 'DO-NOT-COPY'}]
    raw['item_list'][0].update(item_sku='ORIGINAL-PARENT', order_item_id=123)
    payload = adapter_for().normalize_record(raw)
    facts = payload['observed_fields']
    assert facts['platform_pickup_at_utc'] != facts['ship_by_at_utc']
    assert facts['booking_sn'] == 'AAS-SYNTHETIC'
    assert facts['actual_shipping_fee_confirmed'] is False
    assert facts['packages'][0]['items'][0] == {
        'item_id': '123', 'model_id': '456', 'order_item_id': '123', 'quantity': 2}
    assert 'shipped_at_utc' not in payload
    assert payload['lines'][0]['observed_fields']['platform_item_sku'] == 'ORIGINAL-PARENT'
    assert 'DO-NOT-COPY' not in str(payload)


@pytest.mark.parametrize('solution,expected', [(0, True), (1, False), (None, None), (99, None), (True, None)])
def test_return_solution_not_negotiation_or_capability_determines_required_return(solution, expected):
    adapter = MarketplaceRefundAdapter(SimpleNamespace(platform='shopee', platform_config={}))
    adapter.authorization = SimpleNamespace(store=SimpleNamespace(id=1, currency='PHP'), region='PH')
    payload = adapter.normalize_record({
        'return_sn': 'SYNTHETIC-RETURN', 'order_sn': 'SYNTHETIC-ORDER',
        'create_time': 1788170400, 'update_time': 1788174000,
        'status': 'ACCEPTED', 'return_solution': solution,
        'needs_logistics': True, 'latest_solution': 'RETURN_REFUND', 'refund_amount': 10,
    })
    assert payload['requires_physical_return'] is expected
    assert payload['completed_at_utc'] is None


@pytest.mark.django_db
def test_operational_observations_persist_idempotently_without_shipment_or_inventory():
    from apps.commerce.models import ShipmentRecord, InventorySnapshot
    from apps.sales_management.serializers import SalesOrderDetailSerializer
    from apps.sales_management.services import upsert_normalized_order
    from tests.test_sales_management import create_scope, create_run

    tenant, _, store, _ = create_scope('sp-operational')
    run = create_run(tenant, 'sales_order', 'sp-operational')
    raw = shopee_record()
    raw.update(pickup_done_time=1788174000, ship_by_date=1788260400, booking_sn='AAS-SYNTHETIC')
    payload = adapter_for(store_id=store.id).normalize_record(raw)
    order = upsert_normalized_order(tenant=tenant, payload=payload, source_run=run)
    upsert_normalized_order(tenant=tenant, payload=payload, source_run=run)
    order.refresh_from_db()
    assert order.items.count() == 1
    facts = SalesOrderDetailSerializer(order).data['order_observations']
    assert facts['booking_sn'] == 'AAS-SYNTHETIC'
    assert facts['platform_pickup_at_utc'].endswith('+00:00')
    assert ShipmentRecord.objects.count() == 0
    assert InventorySnapshot.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize('mismatch', ['', 'sku', 'ambiguous'])
def test_refund_item_links_only_to_unique_original_shopee_order_item(mismatch):
    from apps.products.models import ProductSPU, ProductSKU
    from apps.sales_management.services import upsert_normalized_refund
    from tests.test_sales_management import NOW, create_scope, create_order, create_run

    tenant, _, store, _ = create_scope('sp-refund-' + mismatch)
    order = create_order(tenant, store, 'sp-refund-' + mismatch)
    line = order.items.get()
    spu = ProductSPU.objects.create(tenant=tenant, spu_code='SYNTHETIC-SPU', product_name='Synthetic')
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code='SYNTHETIC-INTERNAL',
                                   product_name='Synthetic', color_code='BLUE', specification='A')
    line.platform_product_id, line.platform_variant_id, line.internal_sku = '123', '456', sku
    line.save()
    original_id = line.id
    if mismatch == 'ambiguous':
        line.pk = None
        line.external_line_id = 'SECOND-SYNTHETIC-LINE'
        line.save()
    run = create_run(tenant, 'refund_return', 'sp-refund-' + mismatch)
    refund = upsert_normalized_refund(tenant=tenant, source_run=run, payload={
        'store_id': store.id, 'external_order_id': order.external_order_id,
        'external_return_id': 'SYNTHETIC-RETURN', 'updated_at_utc': NOW.isoformat(),
        'requested_at_utc': NOW.isoformat(), 'currency': 'PHP',
        'items': [{'external_return_item_id': 'SYNTHETIC-R-LINE', 'platform_product_id': '123',
                   'platform_variant_id': '456', 'seller_sku': 'DIFFERENT' if mismatch == 'sku' else line.seller_sku,
                   'quantity': 1}]})
    item = refund.items.get()
    if mismatch:
        assert item.sales_order_item_id is None and item.internal_sku_id is None
    else:
        assert item.sales_order_item_id == original_id and item.internal_sku_id == sku.id
