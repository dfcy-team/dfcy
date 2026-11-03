import hashlib
import json
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

from apps.accounts.models import CustomUser
from apps.tenants.models import Tenant
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.finance.business_sync import import_snapshot
from apps.finance.models import PlatformFinanceTransaction
from apps.finance.business_sync_models import BusinessSyncSource, BusinessSyncBatch, BusinessSyncIdentity
from apps.commerce.models import SalesOrder, SalesOrderItem

pytestmark = pytest.mark.django_db


@pytest.fixture
def context():
    tenant = Tenant.objects.create(name='Import fixture', code='import-fixture')
    actor = CustomUser.objects.create_user(username='import-admin', tenant=tenant, is_superuser=True)
    platform = PlatformMaster.objects.create(tenant=tenant, code='shopee', name='Shopee', platform_type='shopee')
    store = StoreMaster.objects.create(tenant=tenant, platform=platform, code='store-a', name='Fixture store',
                                      country_code='PH', currency='PHP', timezone='Asia/Manila')
    source = BusinessSyncSource.objects.create(tenant=tenant, code='fixture-source', origin='https://source.example',
                                               client_binding_hash='a' * 64, created_by=actor, is_enabled=True)
    masters = {'platforms': [{'id': 800, 'platform_type': 'shopee'}],
               'stores': [{'id': 900, 'platform_id': 800, 'code': store.code, 'country_code': 'PH'}]}
    return source, actor, store, masters


def finance(pk=700):
    return dict(id=pk, store_id=900, platform='shopee', external_transaction_id='fixture-tx',
                external_order_id='fixture-order', external_order_item_id='', seller_sku='', platform_variant_id='',
                raw_fee_name='escrow_amount', fee_code='income', fee_category='income', raw_amount='10.1200',
                signed_amount='10.1200', currency='PHP', occurred_at_utc='2026-07-01T02:00:00Z',
                business_date='2026-07-01', sales_order_id=None, sales_order_item_id=None)


def snapshot(tmp_path, resource, rows):
    path = tmp_path / (resource + '.jsonl')
    content = ''.join(json.dumps(row) + '\n' for row in rows).encode()
    path.write_bytes(content)
    money = {'finance_transactions': 'signed_amount', 'sales_orders': 'order_total_amount',
             'sales_order_items': 'line_total_amount'}[resource]
    totals = {}
    for row in rows:
        sums = totals.setdefault(row['currency'], {money: Decimal(0)})
        sums[money] += Decimal(row[money])
    path.with_suffix('.manifest.json').write_text(json.dumps(dict(
        resource=resource, source='https://source.example', complete=True, sampled=False,
        full_pagination=True, identifiers='original_business_identifiers', rows=len(rows),
        sha256=hashlib.sha256(content).hexdigest(), window='2026-07-01_2026-07-01',
        totals={c: {k: str(v) for k, v in sums.items()} for c, sums in totals.items()})))
    return path


def run(context, path, apply=True):
    source, actor, _, masters = context
    return import_snapshot(source=source, actor=actor, path=path, masters=masters, apply=apply)


def test_dry_run_rolls_back_all_facts_and_provenance(context, tmp_path):
    result = run(context, snapshot(tmp_path, 'finance_transactions', [finance()]), apply=False)
    assert result['counts'] == {'created': 1}
    assert not PlatformFinanceTransaction.objects.exists()
    assert not BusinessSyncIdentity.objects.exists()
    assert not BusinessSyncBatch.objects.exists()


def test_create_without_platform_authorization_and_idempotent_rerun(context, tmp_path):
    path = snapshot(tmp_path, 'finance_transactions', [finance()])
    assert run(context, path)['counts'] == {'created': 1}
    assert run(context, path)['counts'] == {'unchanged': 1}
    obj = PlatformFinanceTransaction.objects.get()
    assert obj.pk != 700 and obj.authorization_id is None and obj.source_run_id is None
    assert obj.internal_sync_batch.source_id == context[0].pk
    assert obj.signed_amount == Decimal('10.1200')
    assert obj.match_status == 'unmatched'


def test_changed_source_amount_is_pending_and_preserves_existing_fact(context, tmp_path):
    run(context, snapshot(tmp_path, 'finance_transactions', [finance()]))
    changed = {**finance(), 'signed_amount': '9.1200'}
    result = run(context, snapshot(tmp_path, 'finance_transactions', [changed]))
    assert result['pending_reasons'] == {'source_or_local_fact_changed': 1}
    assert PlatformFinanceTransaction.objects.get().signed_amount == Decimal('10.1200')
    assert BusinessSyncIdentity.objects.get().pending_payload['signed_amount'] == '9.1200'


def test_duplicate_source_business_key_is_not_double_counted(context, tmp_path):
    result = run(context, snapshot(tmp_path, 'finance_transactions', [finance(700), finance(701)]))
    assert result['counts'] == {'pending': 2}
    assert not PlatformFinanceTransaction.objects.exists()


def test_missing_store_stays_pending(context, tmp_path):
    result = run(context, snapshot(tmp_path, 'finance_transactions', [{**finance(), 'store_id': 999}]))
    assert result['pending_reasons'] == {'store_unmapped': 1}
    assert StoreMaster.objects.count() == 1 and not PlatformFinanceTransaction.objects.exists()


def test_cross_tenant_actor_rejected(context, tmp_path):
    context[1].tenant = Tenant.objects.create(name='Other', code='other')
    with pytest.raises(PermissionDenied):
        run(context, snapshot(tmp_path, 'finance_transactions', [finance()]))
    assert not BusinessSyncBatch.objects.exists()


def test_hash_or_credential_rejection_leaves_database_unchanged(context, tmp_path):
    path = snapshot(tmp_path, 'finance_transactions', [finance()])
    path.write_text('changed')
    with pytest.raises((ValidationError, json.JSONDecodeError)):
        run(context, path)
    path = snapshot(tmp_path, 'finance_transactions', [{**finance(), 'client_secret': 'SYNTHETIC_ONLY'}])
    with pytest.raises(ValidationError):
        run(context, path)
    assert not BusinessSyncBatch.objects.exists()


def test_invalid_second_row_rolls_back_first_insert(context, tmp_path):
    bad = {**finance(701), 'external_transaction_id': 'other', 'fee_category': 'invalid'}
    with pytest.raises(ValidationError):
        run(context, snapshot(tmp_path, 'finance_transactions', [finance(), bad]))
    assert not PlatformFinanceTransaction.objects.exists() and not BusinessSyncBatch.objects.exists()


def test_existing_identical_fact_adopted_without_overwrite(context, tmp_path):
    path = snapshot(tmp_path, 'finance_transactions', [finance()])
    run(context, path)
    original = PlatformFinanceTransaction.objects.get()
    source, actor, store, masters = context
    other = BusinessSyncSource.objects.create(tenant=source.tenant, code='other-source', origin=source.origin,
                                              client_binding_hash='b' * 64, created_by=actor, is_enabled=True)
    assert run((other, actor, store, masters), path)['counts'] == {'adopted': 1}
    original.refresh_from_db()
    assert original.internal_sync_batch.source_id == source.pk
    assert PlatformFinanceTransaction.objects.count() == 1


def test_database_requires_exactly_one_origin(context, tmp_path):
    run(context, snapshot(tmp_path, 'finance_transactions', [finance()]))
    with pytest.raises(IntegrityError), transaction.atomic():
        PlatformFinanceTransaction.objects.update(internal_sync_batch=None)


def test_disabled_source_and_non_admin_cannot_import(context, tmp_path):
    path = snapshot(tmp_path, 'finance_transactions', [finance()])
    source = context[0]
    source.is_enabled = False
    source.save(update_fields=['is_enabled'])
    with pytest.raises(PermissionDenied):
        run(context, path)
    source.is_enabled = True
    source.save(update_fields=['is_enabled'])
    context[1].is_superuser = False
    with pytest.raises(PermissionDenied):
        run(context, path)


def test_readonly_projection_preserves_internal_facts_and_tenant_boundary(context, tmp_path):
    run(context, snapshot(tmp_path, 'finance_transactions', [finance()]))
    from apps.integrations.readonly_finance import query
    assert query('finance_transactions', context[0].tenant_id).count() == 1
    other = Tenant.objects.create(name='Other', code='other')
    assert not query('finance_transactions', other.pk).exists()


def test_native_platform_ingestion_still_rejects_revoked_authorization(context):
    from rest_framework.exceptions import ValidationError as PlatformValidationError
    from apps.integrations.models import MarketplaceStoreAuthorization
    from apps.finance.ingestion import upsert_finance_transaction
    source, _, store, _ = context
    authorization = MarketplaceStoreAuthorization(tenant=source.tenant, store=store,
                                                 platform='shopee', status='revoked')
    with pytest.raises(PlatformValidationError, match='active'):
        upsert_finance_transaction(tenant=source.tenant, store=store, authorization=authorization,
                                   source_run=None, payload={})


def test_incomplete_manifest_is_never_importable(context, tmp_path):
    path = snapshot(tmp_path, 'finance_transactions', [finance()])
    manifest = path.with_suffix('.manifest.json')
    meta = json.loads(manifest.read_text())
    meta['complete'] = False
    manifest.write_text(json.dumps(meta))
    with pytest.raises(ValidationError):
        run(context, path)
    assert not PlatformFinanceTransaction.objects.exists()


def test_native_wide_rebuild_does_not_fabricate_provenance_for_internal_rows(context, tmp_path):
    from apps.finance.wide_service import rebuild_lazada_finance_wide
    run(context, snapshot(tmp_path, 'finance_transactions', [finance()]))
    assert rebuild_lazada_finance_wide(tenant=context[0].tenant, store=context[2]) == 0
    from apps.finance.ingestion import rematch_unmatched_transactions
    assert rematch_unmatched_transactions(tenant=context[0].tenant, store=context[2]) == 0


def test_verified_native_event_adopts_identical_replica_instead_of_double_counting(tmp_path):
    from tests.test_shopee_tiktok_finance_ingestion import _finance_scope
    from apps.finance.ingestion import upsert_finance_transaction
    tenant, store, _, authorization, _, native_run = _finance_scope('shopee')
    actor = CustomUser.objects.create_user(username='replica-admin', tenant=tenant, is_superuser=True)
    source = BusinessSyncSource.objects.create(tenant=tenant, code='replica', origin='https://source.example',
                                               client_binding_hash='a' * 64, created_by=actor, is_enabled=True)
    masters = {'platforms': [{'id': 800, 'platform_type': 'shopee'}],
               'stores': [{'id': 900, 'platform_id': 800, 'code': store.code, 'country_code': 'PH'}]}
    row = finance()
    import_snapshot(source=source, actor=actor, path=snapshot(tmp_path, 'finance_transactions', [row]),
                    masters=masters, apply=True)
    original = PlatformFinanceTransaction.objects.get()
    result = upsert_finance_transaction(tenant=tenant, store=store, authorization=authorization, source_run=native_run,
        payload={'contract_version':'finance_transaction.v1', 'source_key':'native-event-key',
                 **{key:row[key] for key in ('external_transaction_id','external_order_id','external_order_item_id',
                                            'raw_fee_name','raw_amount','currency','occurred_at_utc')}})
    assert result.action == 'updated' and result.instance.pk == original.pk
    assert PlatformFinanceTransaction.objects.count() == 1
    result.instance.refresh_from_db()
    assert result.instance.internal_sync_batch_id is None
    assert result.instance.authorization_id == authorization.pk


def test_order_and_item_use_internal_provenance_and_never_source_pks(context, tmp_path):
    row = dict(id=500, platform_id=800, store_id=900, external_order_id='fixture-order', region='PH',
               raw_status='COMPLETED', normalized_status='completed', created_at_utc='2026-07-01T01:00:00Z',
               updated_at_utc='2026-07-01T02:00:00Z', paid_at_utc=None, delivered_at_utc=None,
               cancelled_at_utc=None, completed_at_utc=None, business_date='2026-07-01', currency='PHP',
               subtotal_amount='10.12', seller_discount_amount='0', platform_discount_amount='0',
               shipping_amount='0', tax_amount='0', order_total_amount='10.12')
    assert run(context, snapshot(tmp_path, 'sales_orders', [row]))['counts'] == {'created': 1}
    order = SalesOrder.objects.get()
    assert order.pk != 500 and order.source_run_id is None and order.authorization_id is None
    item = dict(id=600, sales_order_id=500, internal_sku_id=12345, internal_spu_id=67890,
                external_line_id='line-1', platform_product_id='product-1', platform_variant_id='', seller_sku='',
                item_name_snapshot='', variation_snapshot='', quantity=1, original_unit_price='10.12',
                sale_unit_price='10.12', discount_amount='0', tax_amount='0', line_total_amount='10.12',
                currency='PHP', raw_line_status='')
    assert run(context, snapshot(tmp_path, 'sales_order_items', [item]))['counts'] == {'created': 1}
    local_item = SalesOrderItem.objects.get()
    assert local_item.sales_order_id == order.pk and local_item.internal_sku_id is None
    assert run(context, snapshot(tmp_path, 'sales_order_items', [item]))['counts'] == {'unchanged': 1}
    from apps.products.models import ProductSPU, ProductSKU
    spu = ProductSPU.objects.create(tenant=context[0].tenant, spu_code='fixture-spu', product_name='Fixture')
    sku = ProductSKU.objects.create(tenant=context[0].tenant, spu=spu, sku_code='exact-sku')
    context[3]['product_details'] = [{'id': 12345, 'sku_code': 'exact-sku', 'legacy_sku_code': ''}]
    linked = run(context, snapshot(tmp_path, 'sales_order_items', [item]))
    assert linked['quality']['sku_links_added'] == 1
    local_item.refresh_from_db()
    assert local_item.internal_sku_id == sku.pk and local_item.internal_sku_id != 12345
    assert run(context, snapshot(tmp_path, 'sales_order_items', [item]))['quality'] == {}


def test_source_sku_matching_rejects_ambiguous_legacy_codes(context):
    from apps.products.models import ProductSPU, ProductSKU
    from apps.finance.business_sync import _sku_mapping
    spu = ProductSPU.objects.create(tenant=context[0].tenant, spu_code='fixture-spu', product_name='Fixture')
    ProductSKU.objects.create(tenant=context[0].tenant, spu=spu, sku_code='SKU-1', legacy_sku_code='shared')
    ProductSKU.objects.create(tenant=context[0].tenant, spu=spu, sku_code='SKU-2', legacy_sku_code='shared')
    masters = {'product_details': [{'id': 12345, 'sku_code': 'shared', 'legacy_sku_code': ''}]}
    assert _sku_mapping(context[0], masters)['source_ids'] == {}
    from apps.finance.business_sync import _match_sku
    mapping = _sku_mapping(context[0], masters)
    assert _match_sku({'internal_sku_id': None, 'seller_sku': 'shared'}, mapping) is None
    assert _match_sku({'internal_sku_id': None, 'seller_sku': 'SKU-1'}, mapping).sku_code == 'SKU-1'
    assert _match_sku({'internal_sku_id': None, 'seller_sku': 'sku-1'}, mapping) is None
