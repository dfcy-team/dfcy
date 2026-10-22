import json

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from apps.demo_sync.importer import SnapshotImportError, import_snapshot
from apps.demo_sync.models import ImportedSnapshotReceipt, SnapshotIdentity
from apps.demo_sync.pipeline import RESOURCES, build_snapshot
from apps.tenants.models import Tenant
from apps.masterdata.models import StoreMaster, WarehouseMaster
from apps.products.models import ProductCategory, ProductSKU
from apps.commerce.models import InventorySnapshot, SalesOrder, SalesOrderItem
from apps.integrations.models import PlatformIntegrationConfig, SyncJob


class FixtureClient:
    masking_key = b"synthetic-test-secret-key-material-at-least-32-bytes"

    def fetch(self, resource, params):
        records = {
            "platforms": [{"id": 1, "code": "market", "name": "Marketplace", "platform_type": "bigseller", "status": "active"}],
            "country_sites": [{"id": 2, "code": "gb", "name": "United Kingdom", "country_code": "GB", "platform_id": 1, "currency": "GBP", "timezone": "UTC"}],
            "stores": [{"id": 10, "code": "store", "name": "Store Name", "external_store_id": "store-ext", "platform_id": "1", "country_site_id": 2, "country_code": "GB", "currency": "GBP", "timezone": "UTC"}],
            "warehouses": [{"id": 20, "code": "warehouse", "name": "Warehouse Name", "country_code": "GB", "warehouse_type": "owned"}],
            "product_categories": [
                {"id": 50, "parent_id": 51, "level": 2, "code": "01", "name": "Child Category"},
                {"id": 51, "level": 1, "code": "1", "name": "Parent Category"},
            ],
            "products": [{"id": 100, "spu_code": "SPU-100", "product_name": "A Real Product", "product_type": "standard", "category_node_id": 50}],
            "product_details": [{"id": 101, "spu_id": 100, "sku_code": "SKU-101", "product_name": "Variant Name", "specification": "Blue / Large", "purchase_price": "12.3456", "is_active": True}],
            "sales_orders": [{"id": 200, "platform_id": 1, "store_id": 10, "external_order_id": "ORDER-SECRET", "region": "GB", "raw_status": "paid", "normalized_status": "pending", "status_mapping_version": "fixture", "created_at_utc": "2026-01-02T03:04:05Z", "updated_at_utc": "2026-01-02T03:04:05Z", "business_date": "2026-01-02", "currency": "GBP", "subtotal_amount": "18.0000", "seller_discount_amount": "0.0000", "platform_discount_amount": "0.0000", "shipping_amount": "2.0000", "tax_amount": "0.0000", "order_total_amount": "20.0000"}],
            "sales_order_items": [{"id": 201, "sales_order_id": "200", "internal_spu_id": 100, "internal_sku_id": 101, "external_line_id": "LINE-SECRET", "platform_product_id": "PRODUCT-SECRET", "platform_variant_id": "VARIANT-SECRET", "seller_sku": "SELLER-SKU", "item_name_snapshot": "Line Product", "variation_snapshot": "blue", "quantity": 1, "original_unit_price": "18.0000", "sale_unit_price": "18.0000", "discount_amount": "0.0000", "tax_amount": "0.0000", "line_total_amount": "18.0000", "currency": "GBP"}],
            "inventory_snapshots": [{"id": 300, "site_code": "GB", "warehouse_id": 20, "internal_sku_id": 101, "source_sku": "SKU-101", "on_hand_qty": 9, "available_qty": 8, "reserved_qty": 1, "snapshot_at_utc": "2026-01-02T03:04:05Z", "provided_quantity_fields": ["on_hand_qty", "available_qty", "reserved_qty"]}],
        }
        return {"items": records[resource], "has_more": False, "next_cursor": None}


@pytest.mark.django_db(transaction=True)
@override_settings(DEMO_DATA_SYNC_IMPORT_ENABLED=True, DEMO_DATA_SYNC_TEST_OVERRIDE=True,
                   LIVE_PLATFORM_SECURITY_APPROVED=False, LIVE_READONLY_SYNC_ENABLED=False)
def test_native_import_preserves_precision_relations_and_replay_is_idempotent(tmp_path):
    tenant = Tenant.objects.create(name="Demo tenant", code="demo-import-test")
    user = get_user_model().objects.create_user(username="demo-importer", tenant=tenant,
                                                user_type="internal", password=None)
    bundle = tmp_path / "bundle"
    build_snapshot(client=FixtureClient(), resources=RESOURCES, store_ids=[10], warehouse_ids=[20],
                   date_from="2026-01-01", date_to="2026-01-31", output_dir=bundle,
                   scope_key="demo-scope")

    preview = import_snapshot(bundle, tenant_id=tenant.pk, actor_id=user.pk, dry_run=True)
    assert preview["created"] > 0
    assert not SnapshotIdentity.objects.filter(tenant=tenant).exists()

    first = import_snapshot(bundle, tenant_id=tenant.pk, actor_id=user.pk, dry_run=False)
    assert first["resources"]["sales_orders"]["created"] == 1
    order = SalesOrder.objects.get(tenant=tenant)
    item = SalesOrderItem.objects.get(sales_order=order)
    sku = ProductSKU.objects.get(tenant=tenant)
    child_category = ProductCategory.objects.get(tenant=tenant, code="01")
    parent_category = ProductCategory.objects.get(tenant=tenant, code="1")
    inventory = InventorySnapshot.objects.get(tenant=tenant)
    assert str(sku.purchase_price) == "12.3456"
    assert child_category.parent_id == parent_category.pk
    assert item.internal_sku_id == sku.pk and item.sales_order_id == order.pk
    assert inventory.internal_sku_id == sku.pk
    assert order.external_order_id != "ORDER-SECRET"
    assert StoreMaster.objects.get(tenant=tenant).platform_site_id is None
    assert WarehouseMaster.objects.get(tenant=tenant).service_platform_id is None
    assert first["site_mapping"].startswith("CountrySiteMaster imported")
    assert PlatformIntegrationConfig.objects.filter(tenant=tenant, status="disabled", network_enabled=False,
        sync_read_enabled=False, sync_write_enabled=False, credential_id="", token_id="").exists()
    assert SyncJob.objects.filter(tenant=tenant, is_enabled=False, status="disabled").count() == 2
    order.normalized_status = "completed"
    order.save()

    second = import_snapshot(bundle, tenant_id=tenant.pk, actor_id=user.pk, dry_run=False)
    assert second["created"] == 0
    assert second["updated"] == 0 and second["idempotent_replay"] is True
    assert SalesOrder.objects.filter(tenant=tenant).count() == 1
    assert SalesOrderItem.objects.filter(sales_order=order).count() == 1
    assert SalesOrder.objects.get(pk=order.pk).normalized_status == "completed"
    assert ImportedSnapshotReceipt.objects.filter(tenant=tenant).count() == 1


@pytest.mark.django_db
@override_settings(DEMO_DATA_SYNC_IMPORT_ENABLED=True, DEMO_DATA_SYNC_TEST_OVERRIDE=True,
                   LIVE_PLATFORM_SECURITY_APPROVED=False, LIVE_READONLY_SYNC_ENABLED=False)
def test_import_rejects_hash_tampering_and_live_gate(tmp_path):
    tenant = Tenant.objects.create(name="Gate tenant", code="demo-gate-test")
    user = get_user_model().objects.create_user(username="demo-gate-user", tenant=tenant,
                                                user_type="internal", password=None)
    bundle = tmp_path / "bundle"
    build_snapshot(client=FixtureClient(), resources=RESOURCES, store_ids=[10], warehouse_ids=[20],
                   date_from="2026-01-01", date_to="2026-01-31", output_dir=bundle,
                   scope_key="demo-scope")
    with (bundle / "sales_orders.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"id": "tampered"}) + "\n")
    with pytest.raises(SnapshotImportError, match="checksum"):
        import_snapshot(bundle, tenant_id=tenant.pk, actor_id=user.pk)

    with override_settings(LIVE_READONLY_SYNC_ENABLED=True):
        with pytest.raises(SnapshotImportError, match="live platform gates"):
            import_snapshot(bundle, tenant_id=tenant.pk, actor_id=user.pk)
