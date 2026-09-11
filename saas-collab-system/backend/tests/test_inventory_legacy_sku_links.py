import io
import json
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.commerce.models import InventorySnapshot
from apps.integrations.models import IntegrationAuditLog
from apps.permissions.models import DataScope
from apps.products.models import ProductSKU, ProductSPU
from tests.test_sales_management import NOW, create_scope, create_run, user_for, grant

pytestmark = pytest.mark.django_db


@pytest.fixture
def links():
    tenant, _, _, warehouse = create_scope("legacy-links")
    run = create_run(tenant, "inventory_snapshot", "legacy-links", platform="jifeng_wms")
    actor = user_for(tenant, "legacy-link-admin")
    grant(actor, "integrations.manage")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="FAKE-SPU", product_name="Test")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="NEW-SKU", legacy_sku_code="OLD-SKU")
    row = InventorySnapshot.objects.create(
        tenant=tenant, warehouse=warehouse, source_run=run, site_code="PH", source_sku="OLD-SKU",
        snapshot_at_utc=NOW, on_hand_qty=10, available_qty=8, reserved_qty=2, payload_hash="a" * 64,
    )

    def invoke(apply=False, expected=1):
        output = io.StringIO()
        call_command("link_inventory_legacy_skus", tenant_id=tenant.id, warehouse_id=warehouse.id,
                     actor_id=actor.id, apply=apply, expected_matches=expected, stdout=output)
        return json.loads(output.getvalue())
    return row, sku, actor, invoke


def test_preview_then_apply_preserves_facts_and_is_idempotent(links):
    row, sku, actor, invoke = links
    before = InventorySnapshot.objects.values().get(pk=row.id)
    assert invoke()["matched"] == 1
    row.refresh_from_db()
    assert row.internal_sku_id is None
    assert not IntegrationAuditLog.objects.filter(action="inventory_legacy_sku_link").exists()
    assert invoke(True)["matched"] == 1
    after = InventorySnapshot.objects.values().get(pk=row.id)
    assert after.pop("internal_sku_id") == sku.id
    before.pop("internal_sku_id")
    assert before == after
    audit = IntegrationAuditLog.objects.get(action="inventory_legacy_sku_link")
    assert audit.actor_id == actor.id
    assert audit.masked_detail["changes"] == [{"snapshot_id": row.id, "before_internal_sku_id": None,
                                              "after_internal_sku_id": sku.id}]
    assert invoke(True, 0)["matched"] == 0
    assert IntegrationAuditLog.objects.filter(action="inventory_legacy_sku_link").count() == 1


@pytest.mark.parametrize("conflict", ["duplicate", "current_code", "seller", "case", "foreign_tenant"])
def test_ambiguous_or_nonexact_or_foreign_matches_are_not_linked(links, conflict):
    row, sku, _, invoke = links
    if conflict in {"duplicate", "current_code"}:
        ProductSKU.objects.create(tenant=sku.tenant, spu=sku.spu,
            sku_code="ANOTHER" if conflict == "duplicate" else "OLD-SKU",
            legacy_sku_code="OLD-SKU" if conflict == "duplicate" else "")
    elif conflict == "seller":
        row.seller_sku = "DIFFERENT"
        row.save()
    elif conflict == "case":
        sku.legacy_sku_code = "old-sku"
        sku.save()
    else:
        other, _, _, _ = create_scope("other-legacy")
        other_spu = ProductSPU.objects.create(tenant=other, spu_code="OTHER", product_name="Test")
        sku.legacy_sku_code = ""
        sku.save()
        ProductSKU.objects.create(tenant=other, spu=other_spu, sku_code="OTHER", legacy_sku_code="OLD-SKU")
    assert invoke(True, 0)["matched"] == 0
    row.refresh_from_db()
    assert row.internal_sku_id is None


def test_does_not_replace_existing_link(links):
    row, sku, _, invoke = links
    previous = ProductSKU.objects.create(tenant=sku.tenant, spu=sku.spu, sku_code="PREVIOUS")
    row.internal_sku = previous
    row.save()
    assert invoke(True, 0)["matched"] == 0
    row.refresh_from_db()
    assert row.internal_sku_id == previous.id


def test_stale_preview_and_missing_permission_fail_closed(links):
    row, _, actor, invoke = links
    with pytest.raises(CommandError):
        invoke(True, 2)
    actor.is_active = False
    actor.save()
    with pytest.raises(CommandError):
        invoke(True)
    row.refresh_from_db()
    assert row.internal_sku_id is None


def test_audit_failure_rolls_back_links(links):
    row, _, _, invoke = links
    with patch.object(IntegrationAuditLog, "save", side_effect=RuntimeError("Synthetic audit failure")):
        with pytest.raises(RuntimeError):
            invoke(True)
    row.refresh_from_db()
    assert row.internal_sku_id is None


def test_scoped_roles_cannot_run_tenant_wide_maintenance(links):
    row, _, actor, invoke = links
    DataScope.objects.filter(tenant=actor.tenant).update(scope_type=DataScope.ScopeType.CUSTOM)
    with pytest.raises(CommandError):
        invoke(True)
    row.refresh_from_db()
    assert row.internal_sku_id is None


def test_only_selected_warehouse_is_changed(links):
    row, sku, actor, invoke = links
    from apps.masterdata.models import WarehouseMaster
    warehouse = WarehouseMaster.objects.create(tenant=actor.tenant, code="UNSELECTED", name="Other",
                                               country_code="PH", warehouse_type="third_party")
    other = InventorySnapshot.objects.create(
        tenant=actor.tenant, warehouse=warehouse, source_run=row.source_run, site_code="PH",
        source_sku=row.source_sku, snapshot_at_utc=NOW, on_hand_qty=4, payload_hash="b" * 64,
    )
    invoke(True)
    other.refresh_from_db()
    assert other.internal_sku_id is None
