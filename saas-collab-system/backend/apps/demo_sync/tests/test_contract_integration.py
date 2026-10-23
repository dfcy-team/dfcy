"""Use the real published V278 field/parameter contract, not an enlarged fixture."""
import json

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from apps.commerce.models import SalesOrder, SalesOrderItem, InventorySnapshot
from apps.demo_sync.importer import import_snapshot, SnapshotImportError
from apps.demo_sync.pipeline import RESOURCES, build_snapshot
from apps.demo_sync.tests.test_importer import FixtureClient
from apps.integrations.internal_readonly_api import READY
from apps.integrations.readonly_domains import CONTRACTS, filter_fields
from apps.tenants.models import Tenant


class PublishedContractClient(FixtureClient):
    def fetch(self, resource, params):
        allowed_params = {"limit", "cursor"}
        if resource in CONTRACTS:
            allowed_params |= set(filter_fields(resource)) | {"date_from", "date_to"}
        assert set(params) <= allowed_params
        response = super().fetch(resource, params)
        fields = READY[resource][1]
        response["items"] = [{key: value for key, value in row.items() if key in fields} for row in response["items"]]
        return response


@pytest.mark.django_db
@override_settings(DEMO_DATA_SYNC_IMPORT_ENABLED=True, DEMO_DATA_SYNC_TEST_OVERRIDE=True,
                   LIVE_PLATFORM_SECURITY_APPROVED=False, LIVE_READONLY_SYNC_ENABLED=False)
def test_published_fields_only_import_orders_skus_and_inventory(tmp_path):
    tenant = Tenant.objects.create(code="CONTRACT-DEMO", name="Synthetic contract Demo")
    user = get_user_model().objects.create_user(username="contract-demo", tenant=tenant, user_type="internal")
    folder = tmp_path / "bundle"
    manifest = build_snapshot(client=PublishedContractClient(), resources=RESOURCES, store_ids=[10], warehouse_ids=[20],
                              date_from="2026-01-01", date_to="2026-01-31", output_dir=folder, scope_key="source-tenant:scope-a")
    result = import_snapshot(folder, tenant_id=tenant.pk, actor_id=user.pk, dry_run=False)
    order = SalesOrder.objects.get(tenant=tenant)
    item = SalesOrderItem.objects.get(sales_order=order)
    inventory = InventorySnapshot.objects.get(tenant=tenant)
    assert str(order.order_total_amount) == "20.0000"
    assert str(item.line_total_amount) == "18.0000"
    assert inventory.available_qty == 8
    assert inventory.source_run.sync_job.integration_config.platform == "jifeng_wms"
    assert item.internal_sku_id == inventory.internal_sku_id
    assert result["created"] > 0
    # A different source scope cannot overwrite initialized test work.
    manifest["scope_key"] = "other-source:scope-b"
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(SnapshotImportError):
        import_snapshot(folder, tenant_id=tenant.pk, actor_id=user.pk, dry_run=False)


@pytest.mark.django_db
@override_settings(DEMO_DATA_SYNC_IMPORT_ENABLED=True, DEMO_DATA_SYNC_TEST_OVERRIDE=True,
                   LIVE_PLATFORM_SECURITY_APPROVED=False, LIVE_READONLY_SYNC_ENABLED=False)
def test_inventory_only_without_source_warehouse_platform(tmp_path):
    tenant = Tenant.objects.create(code="STOCK-DEMO", name="Synthetic stock Demo")
    user = get_user_model().objects.create_user(username="stock-demo", tenant=tenant, user_type="internal")
    folder = tmp_path / "stock"
    build_snapshot(client=PublishedContractClient(), resources=["inventory_snapshots"], store_ids=[], warehouse_ids=[20],
                   date_from="2026-01-01", date_to="2026-01-31", output_dir=folder, scope_key="stock-scope")
    import_snapshot(folder, tenant_id=tenant.pk, actor_id=user.pk, dry_run=False)
    inventory = InventorySnapshot.objects.get(tenant=tenant)
    assert inventory.available_qty == 8
    assert inventory.source_run.sync_job.integration_config.platform == "jifeng_wms"
    assert not SalesOrder.objects.filter(tenant=tenant).exists()
