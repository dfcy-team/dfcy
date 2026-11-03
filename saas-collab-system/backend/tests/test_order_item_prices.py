from decimal import Decimal

import pytest
from rest_framework.exceptions import ValidationError

from apps.integrations.models import SyncRawEnvelope
from apps.integrations.order_field_mapping import apply_order_observations
from apps.integrations.raw_services import payload_digest
from apps.sales_management.order_item_prices import enrich_item_prices
from apps.sales_management.serializers import SalesOrderLineSerializer
from tests.test_sales_management import create_scope, create_order

pytestmark = pytest.mark.django_db


def fixture(suffix):
    tenant, _, store, _ = create_scope(suffix)
    order = create_order(tenant, store, suffix)
    line = order.items.get()
    line.platform_variant_id = '456'
    line.save(update_fields=['platform_variant_id'])
    payload = {'records': [], 'responses': [{'endpoint': '/api/v2/payment/get_escrow_detail',
        'payload': {'response': {'order_sn': order.external_order_id, 'order_income': {'items': [
            {'item_id': line.platform_product_id, 'model_id': 456, 'model_sku': line.seller_sku,
             'quantity_purchased': 2, 'original_price': '200', 'discounted_price': '150'}]}}}}]}
    envelope = SyncRawEnvelope.objects.create(tenant=tenant, store=store, platform='shopee',
        sync_run=order.source_run, endpoint='/api/v2/payment/get_escrow_detail', sequence=1,
        payload=payload, payload_hash=payload_digest(payload))
    return order, line, envelope


def test_escrow_price_is_not_multiplied_twice_and_sales_facts_are_preserved():
    order, line, envelope = fixture('item-price')
    before = (order.order_total_amount, order.payload_hash, line.quantity, line.line_total_amount, line.updated_at)
    assert enrich_item_prices(envelope, save=False)['items_updated'] == 1
    line.refresh_from_db()
    assert line.source_details.get('api_price_source') is None
    assert enrich_item_prices(envelope)['items_updated'] == 1
    line.refresh_from_db(); order.refresh_from_db()
    assert line.original_unit_price == 100 and line.sale_unit_price == 75
    assert before == (order.order_total_amount, order.payload_hash, line.quantity, line.line_total_amount, line.updated_at)
    data = SalesOrderLineSerializer(line).data
    assert data['sale_unit_price'] == '75.0000' and data['line_total_amount'] == '150.0000'
    assert data['discount_amount'] is None and data['tax_amount'] is None
    assert enrich_item_prices(envelope)['items_updated'] == 0
    # A later order refresh must not replace the escrow-confirmed price with a zero placeholder.
    apply_order_observations(order, {'lines': [{'source_line_id': line.external_line_id,
        'sku': line.seller_sku, 'quantity': line.quantity, 'platform_variant_id': '456',
        'observed_fields': {'sale_unit_price': '0', 'tax_amount': '0'}}]})
    line.refresh_from_db()
    assert line.sale_unit_price == 75
    assert SalesOrderLineSerializer(line).data['tax_amount'] == '0.0000'


def test_unique_platform_identity_accepts_changed_seller_code_but_not_quantity_mismatch():
    order, line, envelope = fixture('item-price-identity')
    envelope.payload['responses'][0]['payload']['response']['order_income']['items'][0]['model_sku'] = 'OLD-PLATFORM-CODE'
    envelope.payload_hash = payload_digest(envelope.payload)
    assert enrich_item_prices(envelope)['items_updated'] == 1
    item = envelope.payload['responses'][0]['payload']['response']['order_income']['items'][0]
    item['quantity_purchased'] = 3
    envelope.payload_hash = payload_digest(envelope.payload)
    assert enrich_item_prices(envelope)['unmatched_items'] == 1
    line.refresh_from_db()
    assert line.quantity == 2 and line.sale_unit_price == 75


def test_missing_price_zero_and_corrupt_archive_remain_distinct():
    order, line, envelope = fixture('item-price-zero')
    line.line_total_amount = Decimal('0')
    line.source_details = {}
    line.save(update_fields=['line_total_amount', 'source_details'])
    assert SalesOrderLineSerializer(line).data['line_total_amount'] is None
    item = envelope.payload['responses'][0]['payload']['response']['order_income']['items'][0]
    item['discounted_price'] = 0
    envelope.payload_hash = payload_digest(envelope.payload)
    enrich_item_prices(envelope)
    line.refresh_from_db()
    assert SalesOrderLineSerializer(line).data['line_total_amount'] == '0.0000'
    envelope.payload_hash = '0' * 64
    with pytest.raises(ValidationError):
        enrich_item_prices(envelope)


def test_lazada_paid_amount_is_preserved_without_guessing_multi_quantity_unit_price():
    order, line, envelope = fixture('item-price-lazada')
    envelope.store.platform.platform_type = 'lazada'
    envelope.store.platform.save(update_fields=['platform_type'])
    line.source_details = {}
    line.save(update_fields=['source_details'])
    envelope.platform = 'lazada'
    envelope.payload = {'records': [{'order_id': order.external_order_id, 'order_items': [
        {'order_item_id': line.external_line_id, 'product_id': line.platform_product_id, 'sku_id': '456',
         'sku': line.seller_sku, 'quantity': 2, 'item_price': '100', 'paid_price': '80', 'tax_amount': '0'}]}]}
    envelope.payload_hash = payload_digest(envelope.payload)
    enrich_item_prices(envelope)
    line.refresh_from_db()
    data = SalesOrderLineSerializer(line).data
    assert data['reported_paid_price'] == '80' and data['line_total_amount'] == '80.0000'
    assert data['sale_unit_price'] is None and data['tax_amount'] == '0.0000'


def test_sync_hook_enriches_order_and_settlement_pages():
    from types import SimpleNamespace
    from unittest.mock import Mock, patch
    from apps.integrations.adapters import ProductionReadonlyAdapter
    adapter = ProductionReadonlyAdapter(SimpleNamespace(platform='shopee', platform_config={}))
    envelope = object()
    run = Mock()
    run.raw_envelopes.order_by.return_value.first.return_value = envelope
    adapter._require_run = lambda: run
    with patch('apps.sales_management.order_item_prices.enrich_item_prices') as enrich:
        adapter.after_page_persist(SimpleNamespace(resource_type='sales_order'), {}, [])
        adapter.after_page_persist(SimpleNamespace(resource_type='settlement_bill'), {}, [])
        assert enrich.call_count == 2
        enrich.assert_called_with(envelope)


def test_price_only_order_trace_hides_unverified_zero_until_escrow_confirms_it():
    order, line, envelope = fixture('item-price-placeholder')
    finance = envelope.payload['responses'][0]
    envelope.payload = {'records': [], 'responses': [{'endpoint': '/api/v2/order/get_order_detail',
        'payload': {'response': {'order_list': [{'order_sn': order.external_order_id, 'currency': 'PHP',
            'item_list': [{'item_id': line.platform_product_id, 'model_id': 456,
                'model_sku': line.seller_sku, 'model_quantity_purchased': 2,
                'model_original_price': 100, 'model_discounted_price': 0}]}]}}}]}
    envelope.payload_hash = payload_digest(envelope.payload)
    enrich_item_prices(envelope)
    line.refresh_from_db()
    data = SalesOrderLineSerializer(line).data
    assert data['original_unit_price'] == '100.0000'
    assert data['sale_unit_price'] is None and data['line_total_amount'] is None
    envelope.payload['responses'].append(finance)
    envelope.payload_hash = payload_digest(envelope.payload)
    enrich_item_prices(envelope)
    line.refresh_from_db()
    assert SalesOrderLineSerializer(line).data['sale_unit_price'] == '75.0000'


def test_existing_single_item_paid_amount_is_displayed_without_changing_stored_sales():
    _, line, _ = fixture('item-price-existing-paid')
    line.quantity = 1
    line.source_details = {'reported_paid_price': '18', 'sale_unit_price': '18'}
    line.sale_unit_price = Decimal('18')
    original_total = line.line_total_amount
    assert SalesOrderLineSerializer(line).data['line_total_amount'] == '18.0000'
    assert line.line_total_amount == original_total
    line.quantity = 2
    assert SalesOrderLineSerializer(line).data['line_total_amount'] == '100.0000'


def test_duplicate_same_sku_rows_require_equal_quantities_and_identical_api_prices():
    from copy import copy, deepcopy
    _, line, envelope = fixture('item-price-identical-rows')
    duplicate = copy(line)
    duplicate.pk = None
    duplicate.external_line_id += '-second'
    duplicate.save()
    items = envelope.payload['responses'][0]['payload']['response']['order_income']['items']
    items.append(deepcopy(items[0]))
    envelope.payload_hash = payload_digest(envelope.payload)
    assert enrich_item_prices(envelope)['items_updated'] == 2
    line.refresh_from_db(); duplicate.refresh_from_db()
    assert line.sale_unit_price == duplicate.sale_unit_price == 75
    items[1]['discounted_price'] = '130'
    envelope.payload_hash = payload_digest(envelope.payload)
    assert enrich_item_prices(envelope)['unmatched_items'] == 2
    line.refresh_from_db(); duplicate.refresh_from_db()
    assert line.sale_unit_price == duplicate.sale_unit_price == 75


def test_missing_escrow_amount_cannot_confirm_an_unverified_zero():
    _, line, envelope = fixture('item-price-missing-escrow')
    line.sale_unit_price = Decimal('0')
    line.source_details = {'sale_unit_price': '0', 'api_price_unverified_zero': True}
    line.save(update_fields=['sale_unit_price', 'source_details'])
    envelope.payload['responses'][0]['payload']['response']['order_income']['items'][0]['discounted_price'] = None
    envelope.payload_hash = payload_digest(envelope.payload)
    assert enrich_item_prices(envelope)['items_updated'] == 0
    line.refresh_from_db()
    assert SalesOrderLineSerializer(line).data['sale_unit_price'] is None
