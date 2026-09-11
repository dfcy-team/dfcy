from datetime import timedelta
from unittest.mock import patch

import pytest

from apps.commerce.models import InventorySnapshot
from apps.commerce.services import upsert_inventory_snapshot
from apps.integrations.models import IntegrationAuditLog
from apps.masterdata.models import WarehouseMaster
from apps.products.models import ProductSKU, ProductSPU, ProductLegacyItem
from tests.test_sales_management import NOW, create_scope, create_run

pytestmark = pytest.mark.django_db


@pytest.fixture
def inventory_link():
    tenant, _, _, warehouse = create_scope('auto-inventory')
    run = create_run(tenant, 'inventory_snapshot', 'auto-inventory', platform='jifeng_wms')
    spu = ProductSPU.objects.create(tenant=tenant, spu_code='SPU', product_name='Synthetic')
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code='NEW-SKU', legacy_sku_code='OLD-SKU')

    def ingest(code='OLD-SKU', **values):
        payload = dict(warehouse_id=warehouse.pk, site_code='PH', source_sku=code, seller_sku=code,
                       snapshot_at_utc=NOW, on_hand_qty=10, available_qty=8, reserved_qty=2,
                       payload_hash='a' * 64)
        payload.update(values)
        return upsert_inventory_snapshot(tenant=tenant, payload=payload, source_run=run)

    def history(code, target=sku, at=NOW - timedelta(days=1), wh=warehouse):
        return InventorySnapshot.objects.create(tenant=tenant, warehouse=wh, source_run=run,
            site_code='PH', source_sku=code, internal_sku=target, snapshot_at_utc=at,
            payload_hash='b' * 64, on_hand_qty=4)
    return tenant, warehouse, run, sku, ingest, history


@pytest.mark.parametrize('code', ['NEW-SKU', 'OLD-SKU'])
def test_unique_exact_codes_link_and_same_snapshot_retry_is_idempotent(inventory_link, code):
    _, _, _, sku, ingest, _ = inventory_link
    row = ingest(code)
    assert row.internal_sku_id == sku.id
    assert (row.on_hand_qty, row.available_qty, row.reserved_qty, row.payload_hash) == (10, 8, 2, 'a' * 64)
    assert ingest(code).pk == row.pk
    assert InventorySnapshot.objects.count() == 1
    audit = IntegrationAuditLog.objects.get(action='inventory_auto_sku_link')
    assert audit.masked_detail['after_internal_sku_id'] == sku.id


def test_exact_legacy_import_alias_resolves_same_target(inventory_link):
    tenant, _, _, sku, ingest, _ = inventory_link
    ProductLegacyItem.objects.create(tenant=tenant, legacy_sku_code='IMPORT-OLD', product_name='Synthetic',
                                    generated_sku=sku, status='generated')
    assert ingest('IMPORT-OLD').internal_sku_id == sku.id


def test_user_confirmed_case_different_history_is_inherited(inventory_link):
    _, _, _, sku, ingest, history = inventory_link
    history('Old-Sku')
    assert ingest('Old-Sku').internal_sku_id == sku.id
    assert IntegrationAuditLog.objects.get(action='inventory_auto_sku_link').masked_detail['rule'] == 'warehouse_history'


@pytest.mark.parametrize('code', ['old-sku', 'UNKNOWN'])
def test_unknown_and_unconfirmed_case_differences_stay_unmapped(inventory_link, code):
    _, _, _, _, ingest, _ = inventory_link
    assert ingest(code).internal_sku_id is None


def test_history_requires_exact_source_code_and_same_warehouse(inventory_link):
    tenant, _, _, _, ingest, history = inventory_link
    history('old-sku')
    assert ingest('Old-Sku').internal_sku_id is None
    other = WarehouseMaster.objects.create(tenant=tenant, code='OTHER', name='Other', country_code='PH',
                                           warehouse_type='third_party')
    history('EXTERNAL', wh=other)
    assert ingest('EXTERNAL').internal_sku_id is None


def test_conflicting_history_does_not_fall_back_to_catalogue(inventory_link):
    tenant, _, _, sku, ingest, history = inventory_link
    other = ProductSKU.objects.create(tenant=tenant, spu=sku.spu, sku_code='OTHER')
    history('OLD-SKU')
    history('OLD-SKU', target=other, at=NOW - timedelta(days=2))
    assert ingest().internal_sku_id is None
    assert IntegrationAuditLog.objects.get(action='inventory_auto_sku_link').masked_detail['rule'] == 'history_conflict'


@pytest.mark.parametrize('kind', ['duplicate_legacy', 'current_vs_legacy', 'seller'])
def test_conflicts_stay_unmapped(inventory_link, kind):
    tenant, _, _, sku, ingest, _ = inventory_link
    if kind == 'seller':
        row = ingest(seller_sku='DIFFERENT')
    else:
        ProductSKU.objects.create(tenant=tenant, spu=sku.spu,
            sku_code='OTHER' if kind == 'duplicate_legacy' else 'OLD-SKU',
            legacy_sku_code='OLD-SKU' if kind == 'duplicate_legacy' else '')
        row = ingest()
    assert row.internal_sku_id is None


def test_existing_mapping_wins_and_new_snapshot_inherits_it(inventory_link):
    tenant, _, _, sku, ingest, history = inventory_link
    manual = ProductSKU.objects.create(tenant=tenant, spu=sku.spu, sku_code='MANUAL')
    old = history('OLD-SKU', target=manual, at=NOW)
    assert ingest().internal_sku_id == manual.id
    assert ingest(snapshot_at_utc=NOW + timedelta(days=1)).internal_sku_id == manual.id
    old.refresh_from_db()
    assert old.internal_sku_id == manual.id


def test_other_tenant_candidates_are_not_used(inventory_link):
    _, _, _, _, ingest, _ = inventory_link
    other, _, _, _ = create_scope('foreign-auto')
    spu = ProductSPU.objects.create(tenant=other, spu_code='OTHER', product_name='Test')
    ProductSKU.objects.create(tenant=other, spu=spu, sku_code='FOREIGN', legacy_sku_code='EXT')
    assert ingest('EXT').internal_sku_id is None


def test_audit_failure_rolls_back_snapshot_and_link(inventory_link):
    _, _, _, _, ingest, _ = inventory_link
    with patch.object(IntegrationAuditLog, 'save', side_effect=RuntimeError('Synthetic audit failure')):
        with pytest.raises(RuntimeError):
            ingest()
    assert InventorySnapshot.objects.count() == 0


def test_retry_of_unmapped_snapshot_links_after_catalogue_is_completed(inventory_link):
    tenant, _, _, sku, ingest, _ = inventory_link
    row = ingest('LATER')
    assert row.internal_sku_id is None
    target = ProductSKU.objects.create(tenant=tenant, spu=sku.spu, sku_code='LATER')
    retried = ingest('LATER')
    assert retried.pk == row.pk
    assert retried.internal_sku_id == target.id


def test_legacy_import_alias_conflict_does_not_choose_first(inventory_link):
    tenant, _, _, sku, ingest, _ = inventory_link
    other = ProductSKU.objects.create(tenant=tenant, spu=sku.spu, sku_code='OTHER')
    ProductLegacyItem.objects.create(tenant=tenant, legacy_sku_code='OLD-SKU', product_name='Synthetic',
                                    generated_sku=other, status='generated')
    assert ingest().internal_sku_id is None


def test_adapter_reports_mapping_only_update_and_then_skips_replay(inventory_link):
    from apps.integrations.adapters import JifengInventoryAdapter
    _, warehouse, run, sku, _, history = inventory_link
    row = history('OLD-SKU', target=None, at=NOW)
    adapter = JifengInventoryAdapter(run.sync_job.integration_config)
    adapter.bind_run(run)
    payload = dict(warehouse_id=warehouse.pk, site_code='PH', source_sku='OLD-SKU',
                   snapshot_at_utc=NOW.isoformat(), on_hand_qty=4, payload_hash=row.payload_hash)
    assert adapter.persist_record(run.sync_job, payload)['action'] == 'updated'
    assert adapter.persist_record(run.sync_job, payload)['action'] == 'skipped'
    row.refresh_from_db()
    assert row.internal_sku_id == sku.id
