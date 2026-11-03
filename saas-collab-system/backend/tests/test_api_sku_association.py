from datetime import timedelta

import pytest

from apps.products.models import ProductSKU, ProductSPU, ProductSKUAlias
from apps.products.sku_aliases import code_key
from apps.sales_management.services import upsert_normalized_order, upsert_normalized_refund
from tests.test_sales_management import NOW, create_run, create_scope


def catalogue(tenant, code='INTERNAL-NEW', old='SOURCE-OLD'):
    spu = ProductSPU.objects.create(tenant=tenant, spu_code=code, product_name='Synthetic')
    return ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code=code, legacy_sku_code=old)


def order_payload(store, code='SOURCE-OLD'):
    return {'store_id': store.id, 'external_order_id': 'API-ORDER',
            'created_at_utc': NOW.isoformat(), 'updated_at_utc': NOW.isoformat(),
            'currency': store.currency, 'order_total_amount': '20',
            'lines': [{'external_line_id': 'LINE', 'seller_sku': code,
                       'platform_product_id': 'PRODUCT', 'platform_variant_id': 'VARIANT',
                       'quantity': 2, 'sale_unit_price': '10', 'line_total_amount': '20'}]}


@pytest.mark.django_db
@pytest.mark.parametrize('platform', ['shopee', 'lazada', 'tiktok'])
@pytest.mark.parametrize('code', ['SOURCE-OLD', 'INTERNAL-NEW'])
def test_api_orders_link_unique_new_or_old_code_without_rewriting_source(platform, code):
    tenant, master, store, _ = create_scope('api-link-' + platform + code)
    master.platform_type = platform
    master.save(update_fields=['platform_type'])
    sku = catalogue(tenant)
    run = create_run(tenant, 'sales_order', 'api-' + platform + code, platform=platform)
    order = upsert_normalized_order(tenant=tenant, payload=order_payload(store, code), source_run=run)
    line = order.items.get()
    assert line.internal_sku_id == sku.id and line.internal_spu_id == sku.spu_id
    assert line.seller_sku == code and line.quantity == 2 and line.line_total_amount == 20


@pytest.mark.django_db
def test_ambiguous_case_mismatch_and_foreign_tenant_are_not_guessed():
    tenant, _, store, _ = create_scope('api-ambiguous')
    catalogue(tenant)
    catalogue(tenant, 'SOURCE-OLD', 'OTHER')
    foreign, _, _, _ = create_scope('api-foreign')
    catalogue(foreign, 'FOREIGN', 'FOREIGN-OLD')
    run = create_run(tenant, 'sales_order', 'api-ambiguous')
    for code in ['SOURCE-OLD', 'source-old', 'FOREIGN-OLD', 'UNKNOWN']:
        payload = order_payload(store, code)
        payload['external_order_id'] = code
        assert upsert_normalized_order(tenant=tenant, payload=payload, source_run=run).items.get().internal_sku_id is None


@pytest.mark.django_db
def test_dated_store_alias_uses_order_time_and_does_not_leak_to_another_store():
    tenant, _, store, _ = create_scope('api-alias')
    original = catalogue(tenant)
    replacement = catalogue(tenant, 'REPLACEMENT', 'OTHER-OLD')
    ProductSKUAlias.objects.create(tenant=tenant, sku=replacement, alias_code='SOURCE-OLD',
        code_key=code_key('SOURCE-OLD'),
        scope_type='store', store=store, effective_from=NOW-timedelta(days=1),
        effective_to=NOW+timedelta(days=1), reason='Synthetic approved alias', version_no=1)
    run = create_run(tenant, 'sales_order', 'api-alias')
    order = upsert_normalized_order(tenant=tenant, payload=order_payload(store), source_run=run)
    assert order.items.get().internal_sku_id == replacement.id
    payload = order_payload(store)
    payload.update(external_order_id='OUTSIDE-ALIAS', created_at_utc=(NOW-timedelta(days=2)).isoformat())
    assert upsert_normalized_order(tenant=tenant, payload=payload, source_run=run).items.get().internal_sku_id is None
    from apps.masterdata.models import StoreMaster
    other = StoreMaster.objects.create(tenant=tenant, platform=store.platform, code='OTHER', name='Other',
        country_code='PH', currency='PHP', timezone='Asia/Manila')
    assert upsert_normalized_order(tenant=tenant, payload=order_payload(other), source_run=run).items.get().internal_sku_id == original.id


@pytest.mark.django_db
@pytest.mark.parametrize('platform', ['shopee', 'lazada', 'tiktok'])
def test_api_refund_with_no_seller_sku_inherits_unique_original_item(platform):
    tenant, master, store, _ = create_scope('api-refund-inherit-' + platform)
    master.platform_type = platform
    master.save(update_fields=['platform_type'])
    order_run = create_run(tenant, 'sales_order', 'api-refund-order', platform=platform)
    order = upsert_normalized_order(tenant=tenant, payload=order_payload(store), source_run=order_run)
    sku = catalogue(tenant)  # Catalogue became available after the order was collected.
    refund_run = create_run(tenant, 'refund_return', 'api-refund', platform=platform)
    refund = upsert_normalized_refund(tenant=tenant, source_run=refund_run, payload={
        'store_id': store.id, 'external_order_id': order.external_order_id,
        'external_return_id': 'RETURN', 'requested_at_utc': NOW.isoformat(),
        'updated_at_utc': NOW.isoformat(), 'currency': 'PHP', 'normalized_status': 'accepted',
        'items': [{'external_return_item_id': 'RETURN-LINE', 'platform_product_id': 'PRODUCT',
                   'platform_variant_id': 'VARIANT', 'seller_sku': '', 'quantity': 1}]})
    assert refund.items.get().sales_order_item_id == order.items.get().id
    assert refund.items.get().internal_sku_id == order.items.get().internal_sku_id == sku.id
    assert refund.items.get().seller_sku == ''


@pytest.mark.django_db
def test_identical_api_batch_can_fill_a_previously_missing_link_without_replacing_existing():
    from apps.integrations.adapters import MarketplaceOrderAdapter
    tenant, _, store, _ = create_scope('api-repeat')
    run = create_run(tenant, 'sales_order', 'api-repeat')
    payload = order_payload(store)
    payload['source_order_id'] = payload['external_order_id']
    payload['payload_hash'] = 'a' * 64
    order = upsert_normalized_order(tenant=tenant, payload=payload, source_run=run)
    sku = catalogue(tenant)
    adapter = MarketplaceOrderAdapter(run.sync_job.integration_config)
    adapter.bind_run(run)
    result = adapter.persist_records(run.sync_job, [payload])
    assert order.items.get().internal_sku_id == sku.id
    assert result[0]['action'] == 'updated'
    replacement = catalogue(tenant, 'REPLACEMENT', 'SOURCE-OLD')
    adapter.persist_records(run.sync_job, [payload])
    assert order.items.get().internal_sku_id == sku.id != replacement.id


@pytest.mark.django_db
@pytest.mark.parametrize('platform', ['shopee', 'lazada', 'tiktok'])
def test_refund_batch_replay_links_exact_code_without_needing_an_order(platform):
    from apps.integrations.adapters import MarketplaceRefundAdapter
    from apps.integrations.models import IntegrationAuditLog
    tenant, master, store, _ = create_scope('api-return-replay-' + platform)
    master.platform_type = platform
    master.save(update_fields=['platform_type'])
    run = create_run(tenant, 'refund_return', 'return-replay-' + platform, platform=platform)
    payload = {'store_id': store.id, 'external_return_id': 'RETURN',
        'requested_at_utc': NOW.isoformat(), 'updated_at_utc': NOW.isoformat(),
        'currency': 'PHP', 'normalized_status': 'accepted', 'payload_hash': 'b' * 64,
        'items': [{'external_return_item_id': 'LINE', 'seller_sku': 'SOURCE-OLD', 'quantity': 1}]}
    refund = upsert_normalized_refund(tenant=tenant, payload=payload, source_run=run)
    sku = catalogue(tenant)
    adapter = MarketplaceRefundAdapter(run.sync_job.integration_config)
    adapter.bind_run(run)
    assert adapter.persist_records(run.sync_job, [payload])[0]['action'] == 'updated'
    assert refund.items.get().internal_sku_id == sku.id
    assert adapter.persist_records(run.sync_job, [payload])[0]['action'] == 'skipped'
    assert IntegrationAuditLog.objects.filter(action='api_sales_sku_link').count() == 1


@pytest.mark.django_db
def test_alias_overlap_is_not_resolved_arbitrarily():
    tenant, _, store, _ = create_scope('api-overlap')
    for index in range(2):
        sku = catalogue(tenant, 'NEW-' + str(index), 'OLD-' + str(index))
        ProductSKUAlias.objects.create(tenant=tenant, sku=sku, alias_code='API-CODE',
            code_key=code_key('API-CODE'), scope_type='tenant', effective_from=NOW-timedelta(days=1),
            reason='Synthetic', version_no=1)
    run = create_run(tenant, 'sales_order', 'api-overlap')
    order = upsert_normalized_order(tenant=tenant, payload=order_payload(store, 'API-CODE'), source_run=run)
    assert order.items.get().internal_sku_id is None


@pytest.mark.django_db
def test_audit_failure_rolls_back_automatic_link_and_new_order(monkeypatch):
    from apps.commerce.models import SalesOrder
    from apps.integrations.models import IntegrationAuditLog
    tenant, _, store, _ = create_scope('api-audit-failure')
    catalogue(tenant)
    run = create_run(tenant, 'sales_order', 'api-audit-failure')
    def fail(**kwargs):
        raise RuntimeError('Synthetic audit failure')
    monkeypatch.setattr(IntegrationAuditLog.objects, 'create', fail)
    with pytest.raises(RuntimeError, match='audit failure'):
        upsert_normalized_order(tenant=tenant, payload=order_payload(store), source_run=run)
    assert not SalesOrder.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db
def test_new_bundle_order_keeps_the_effective_component_snapshot():
    from apps.commerce.models import SalesOrderBundleSnapshot
    from apps.products.models import ProductBundleVersion, ProductBundleVersionComponent
    tenant, _, store, _ = create_scope('api-bundle')
    bundle = catalogue(tenant)
    component = catalogue(tenant, 'COMPONENT', 'COMPONENT-OLD')
    run = create_run(tenant, 'sales_order', 'api-bundle')
    version = ProductBundleVersion.objects.create(tenant=tenant, bundle_sku=bundle, version=1,
        effective_at=NOW-timedelta(days=1), created_by=run.sync_job.integration_config.created_by)
    ProductBundleVersionComponent.objects.create(version=version, component_sku=component,
        component_sku_code=component.sku_code, quantity=2)
    order = upsert_normalized_order(tenant=tenant, payload=order_payload(store), source_run=run)
    snapshot = SalesOrderBundleSnapshot.objects.get(order_item=order.items.get())
    assert snapshot.bundle_version_id == version.id
    assert snapshot.components_payload[0]['component_sku_id'] == component.id


@pytest.mark.django_db
def test_automatic_link_does_not_overwrite_an_existing_order_identity():
    from apps.integrations.models import IntegrationAuditLog
    tenant, _, store, _ = create_scope('api-preserve')
    original = catalogue(tenant)
    run = create_run(tenant, 'sales_order', 'api-preserve')
    payload = order_payload(store)
    order = upsert_normalized_order(tenant=tenant, payload=payload, source_run=run)
    replacement = catalogue(tenant, 'REPLACEMENT', 'REPLACEMENT-OLD')
    payload['lines'][0]['seller_sku'] = replacement.legacy_sku_code
    upsert_normalized_order(tenant=tenant, payload=payload, source_run=run)
    assert order.items.get().internal_sku_id == original.id
    assert IntegrationAuditLog.objects.filter(action='api_sales_sku_conflict', result='blocked').exists()
