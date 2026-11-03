from types import SimpleNamespace

import pytest

from apps.integrations.adapters import MarketplaceOrderAdapter, LazadaOrderAdapter
from apps.integrations.order_field_mapping import apply_order_observations
from apps.sales_management.serializers import SalesOrderDetailSerializer
from tests.test_sales_management import create_scope, create_order


def adapter_for(platform='shopee', store_id=1):
    adapter = (LazadaOrderAdapter if platform == 'lazada' else MarketplaceOrderAdapter)(
        SimpleNamespace(platform=platform, platform_config={}))
    adapter.authorization = SimpleNamespace(store=SimpleNamespace(id=store_id, currency='PHP'), region='PH')
    return adapter


def shopee_record():
    return {'order_sn': 'SYNTHETIC-ORDER', 'order_status': 'COMPLETED',
        'create_time': 1788170400, 'update_time': 1788174000, 'total_amount': 160,
        'payment_method': 'Synthetic payment', 'shipping_carrier': 'Synthetic carrier',
        'package_list': [{'package_number': 'SYNTHETIC-PACKAGE', 'tracking_number': 'SYNTHETIC-TRACK',
                          'recipient_phone': 'never-copy-this-private-field'}],
        'recipient_address': {'name': 'Synthetic Customer', 'phone': '1234567890', 'city': 'Test city',
                              'full_address': 'DO-NOT-COPY-PRIVATE-STREET'},
        'item_list': [{'item_id': 123, 'model_id': 456, 'model_sku': 'SYNTHETIC-SKU',
            'model_quantity_purchased': 2, 'model_original_price': 100,
            'model_discounted_price': 80, 'model_name': 'Synthetic variation'}]}


def test_explicit_fields_survive_normalization_without_inventing_missing_charges():
    result = adapter_for().normalize_record(shopee_record())
    assert result['observed_fields']['raw_status'] == 'COMPLETED'
    assert result['observed_fields']['payment_method'] == 'Synthetic payment'
    assert 'tax_amount' not in result['observed_fields']
    assert 'seller_discount_amount' not in result['observed_fields']
    assert 'paid_at_utc' not in result['observed_fields']
    assert result['lines'][0]['observed_fields']['original_unit_price'] == '100'
    assert result['lines'][0]['observed_fields']['sale_unit_price'] == '80'
    assert 'discount_amount' not in result['lines'][0]['observed_fields']
    assert 'DO-NOT-COPY' not in str(result)
    assert '1234567890' not in str(result)
    assert 'never-copy' not in str(result)


def test_zero_is_known_only_when_explicitly_reported_and_times_are_not_guessed():
    raw = shopee_record()
    raw.update(pay_time=0, complete_time=1788174000, estimated_shipping_fee=0)
    result = adapter_for().normalize_record(raw)['observed_fields']
    assert result['shipping_amount'] == '0'
    assert result['shipping_amount_basis'] == 'estimated'
    assert 'paid_at_utc' not in result
    assert result['completed_at_utc'].endswith('+00:00')


def test_added_money_fields_convert_to_cny_without_turning_missing_tax_into_zero():
    from decimal import Decimal
    from unittest.mock import patch
    from apps.sales_management.currency_conversion import convert_sales_payload
    request = SimpleNamespace(query_params={'currency_basis': 'CNY'}, user=SimpleNamespace(tenant=None))
    with patch('apps.sales_management.currency_conversion.tenant_cny_rates',
               return_value={'PHP': {'rate': Decimal('10'), 'date': None}}):
        data = convert_sales_payload(request, {'currency': 'PHP', 'shipping_amount': '100', 'tax_amount': None,
            'items': [{'currency': 'PHP', 'reported_paid_price': '40'}]})
    assert data['shipping_amount'] == '10' and data['tax_amount'] is None
    assert data['items'][0]['reported_paid_price'] == '4'
    assert data['source_amounts']['shipping_amount'] == '100'


def test_lazada_paid_price_is_not_assumed_a_multi_quantity_unit_price():
    raw = {'order_id': 'SYNTHETIC-LZ', 'statuses': ['shipped'], 'created_at': '2026-09-01T00:00:00Z',
        'updated_at': '2026-09-01T01:00:00Z', 'price': '80', 'voucher_seller': '0',
        'voucher_platform': '5', 'order_items': [{'order_item_id': 'LINE-1', 'sku': 'SKU-1',
            'item_price': '100', 'paid_price': '80', 'quantity': 2, 'variation': 'Test variation', 'tax_amount': '0'}]}
    result = adapter_for('lazada').normalize_record(raw)
    assert result['observed_fields']['seller_discount_amount'] == '0'
    assert result['observed_fields']['platform_discount_amount'] == '5'
    assert result['lines'][0]['observed_fields']['tax_amount'] == '0'
    assert 'sale_unit_price' not in result['lines'][0]['observed_fields']
    assert result['lines'][0]['observed_fields']['reported_paid_price'] == '80'


@pytest.mark.django_db
def test_enrichment_is_idempotent_preserves_totals_and_does_not_create_items():
    tenant, _, store, _ = create_scope('order-fields')
    order = create_order(tenant, store, 'order-fields')
    line = order.items.get()
    payload = {'observed_fields': {'raw_status': 'COMPLETED', 'payment_method': 'Synthetic payment'},
        'lines': [{'source_line_id': line.external_line_id, 'sku': line.seller_sku, 'quantity': line.quantity,
                   'observed_fields': {'original_unit_price': '90', 'sale_unit_price': '40', 'variation_snapshot': 'Test variation'}}]}
    before = (order.order_total_amount, order.updated_at_utc, line.quantity, line.line_total_amount, order.items.count())
    planned = apply_order_observations(order, payload, save=False)
    assert planned['order_fields'] > 0
    order.refresh_from_db()
    assert order.source_details.get('payment_method') is None
    apply_order_observations(order, payload)
    assert apply_order_observations(order, payload)['item_fields'] == 0
    order.refresh_from_db(); line.refresh_from_db()
    assert before == (order.order_total_amount, order.updated_at_utc, line.quantity, line.line_total_amount, order.items.count())
    assert line.original_unit_price == 90 and line.sale_unit_price == 40
    data = SalesOrderDetailSerializer(order).data
    assert data['order_observations']['payment_method'] == 'Synthetic payment'
    assert data['tax_amount'] is None
    assert data['items'][0]['discount_amount'] is None


@pytest.mark.django_db
def test_different_variant_or_quantity_is_not_backfilled():
    tenant, _, store, _ = create_scope('order-fields-mismatch')
    order = create_order(tenant, store, 'order-fields-mismatch')
    line = order.items.get()
    payload = {'observed_fields': {}, 'lines': [{'source_line_id': line.external_line_id, 'sku': line.seller_sku,
        'quantity': line.quantity + 1, 'observed_fields': {'original_unit_price': '999'}}]}
    result = apply_order_observations(order, payload)
    line.refresh_from_db()
    assert result['unmatched_items'] == 1 and line.original_unit_price != 999


def archived_order(suffix):
    from apps.integrations.models import SyncRawEnvelope
    from apps.integrations.raw_services import payload_digest
    from tests.test_sales_management import NOW, user_for
    tenant, _, store, _ = create_scope(suffix)
    actor = user_for(tenant, suffix + '-actor')
    actor.is_superuser = True; actor.save(update_fields=['is_superuser'])
    order = create_order(tenant, store, suffix)
    line = order.items.get()
    line.external_line_id = f'{order.external_order_id}:123:456:1'
    line.platform_product_id, line.platform_variant_id = '123', '456'
    line.save()
    raw = shopee_record()
    raw.update(order_sn=order.external_order_id, create_time=int(NOW.timestamp()), update_time=int(NOW.timestamp()))
    raw['item_list'][0]['model_sku'] = line.seller_sku
    payload = {'records': [raw], 'responses': []}
    envelope = SyncRawEnvelope.objects.create(tenant=tenant, sync_run=order.source_run, store=store,
        platform='shopee', endpoint='/api/v2/order/get_order_detail', sequence=1,
        payload=payload, payload_hash=payload_digest(payload))
    return actor, order, envelope


@pytest.mark.django_db
def test_offline_plan_is_read_only_and_apply_is_idempotent_without_platform_calls():
    from unittest.mock import patch
    from apps.commerce.models import SalesOrder, SalesOrderItem
    from apps.sales_management.order_field_backfill import build_plan, apply_plan
    actor, order, _ = archived_order('offline-fields')
    count = (SalesOrder.objects.count(), SalesOrderItem.objects.count())
    total = order.order_total_amount
    with patch('apps.integrations.readonly_clients.PlatformHttpClient.request') as network:
        plan, summary = build_plan(actor)
        assert summary['orders_to_update'] == 1
        order.refresh_from_db()
        assert 'payment_method' not in order.source_details
        apply_plan(actor, plan)
        again, _ = build_plan(actor)
        network.assert_not_called()
    assert again == []
    order.refresh_from_db()
    assert order.order_total_amount == total
    assert count == (SalesOrder.objects.count(), SalesOrderItem.objects.count())
    assert order.items.get().original_unit_price == 100


@pytest.mark.django_db
def test_offline_plan_refuses_changed_local_facts_and_rolls_back():
    from rest_framework.exceptions import ValidationError
    from apps.sales_management.order_field_backfill import build_plan, apply_plan
    actor, order, _ = archived_order('offline-conflict')
    plan, _ = build_plan(actor)
    order.order_total_amount += 1; order.save(update_fields=['order_total_amount'])
    with pytest.raises(ValidationError):
        apply_plan(actor, plan)
    order.refresh_from_db()
    assert 'payment_method' not in order.source_details


@pytest.mark.django_db
def test_offline_plan_ignores_different_snapshot_and_refuses_corrupt_archive():
    from rest_framework.exceptions import ValidationError
    from apps.sales_management.order_field_backfill import build_plan
    actor, order, envelope = archived_order('offline-snapshot')
    order.updated_at_utc = order.updated_at_utc.replace(second=1)
    order.save(update_fields=['updated_at_utc'])
    plan, summary = build_plan(actor)
    assert plan == [] and summary['different_snapshot'] == 1
    # Corruption is injected only into the test database using the base
    # manager; ordinary application writes cannot change an immutable RAW.
    from django.db.models import QuerySet
    QuerySet.update(envelope.__class__.objects.filter(pk=envelope.pk), payload_hash='0' * 64)
    with pytest.raises(ValidationError):
        build_plan(actor)
