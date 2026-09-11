import io
import json
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from apps.commerce.models import SalesOrderItem, SalesOrder, RefundReturn, RefundReturnItem
from apps.integrations.models import IntegrationAuditLog
from apps.products.models import ProductSKU, ProductSPU
from apps.sales_management.views import _sku_rows
from tests.test_sales_management import NOW, create_scope, create_order, create_run, user_for, grant, client_for

pytestmark = pytest.mark.django_db


@pytest.fixture
def links():
    tenant, _, store, _ = create_scope("sales-links")
    order = create_order(tenant, store, "links")
    item = order.items.get()
    actor = user_for(tenant, "link-admin")
    grant(actor, "integrations.manage")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="TEST-SPU", product_name="Test")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="NEW", legacy_sku_code=item.seller_sku)

    def invoke(apply=False, expected=1):
        output = io.StringIO()
        call_command("link_sales_skus", tenant_id=tenant.id, actor_id=actor.id,
                     apply=apply, expected_matches=expected, stdout=output)
        return json.loads(output.getvalue())
    return item, sku, actor, invoke


def test_preview_apply_preserves_facts_and_is_idempotent(links):
    item, sku, _, invoke = links
    before = SalesOrderItem.objects.values().get(pk=item.pk)
    assert invoke()["matched"] == 1
    assert not IntegrationAuditLog.objects.filter(action="sales_sku_link").exists()
    invoke(True)
    after = SalesOrderItem.objects.values().get(pk=item.pk)
    assert after.pop("internal_sku_id") == sku.pk
    assert after.pop("internal_spu_id") == sku.spu_id
    before.pop("internal_sku_id")
    before.pop("internal_spu_id")
    assert before == after
    assert invoke(True, 0)["matched"] == 0
    assert IntegrationAuditLog.objects.filter(action="sales_sku_link").count() == 1


@pytest.mark.parametrize("kind", ["case", "duplicate", "foreign", "existing", "spu"])
def test_no_unsafe_or_existing_links(links, kind):
    item, sku, _, invoke = links
    if kind == "case":
        sku.legacy_sku_code = sku.legacy_sku_code.lower()
        sku.save()
    elif kind == "duplicate":
        ProductSKU.objects.create(tenant=sku.tenant, spu=sku.spu, sku_code="OTHER", legacy_sku_code=item.seller_sku)
    elif kind == "foreign":
        tenant, _, _, _ = create_scope("foreign-links")
        spu = ProductSPU.objects.create(tenant=tenant, spu_code="X", product_name="Test")
        sku.legacy_sku_code = ""
        sku.save()
        ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code=item.seller_sku)
    elif kind == "existing":
        item.internal_sku = sku
        item.save()
    else:
        item.internal_spu = ProductSPU.objects.create(tenant=sku.tenant, spu_code="OTHER", product_name="Test")
        item.save()
    assert invoke(True, 0)["matched"] == 0


def test_stale_preview_and_audit_failure_roll_back(links):
    item, _, _, invoke = links
    with pytest.raises(CommandError):
        invoke(True, 2)
    with patch.object(IntegrationAuditLog.objects, "create", side_effect=RuntimeError("test")):
        with pytest.raises(RuntimeError):
            invoke(True)
    item.refresh_from_db()
    assert item.internal_sku_id is None
    assert item.internal_spu_id is None


def test_boundary_whitespace_does_not_change_source_code(links):
    item, sku, _, invoke = links
    item.seller_sku += "\n"
    item.save()
    invoke(True)
    item.refresh_from_db()
    assert item.internal_sku_id == sku.id
    assert item.seller_sku.endswith("\n")


def test_missing_permission_cannot_apply(links):
    _, _, actor, invoke = links
    actor.is_active = False
    actor.save()
    with pytest.raises(CommandError):
        invoke(True)


def test_mapping_does_not_drop_variant_groups_or_double_count_orders(links):
    item, sku, _, invoke = links
    other = create_order(sku.tenant, item.sales_order.store, "other")
    second = other.items.get()
    second.seller_sku = item.seller_sku
    second.save()
    SalesOrderItem.objects.create(sales_order=item.sales_order, external_line_id="EXTRA",
        platform_product_id="ANOTHER-PRODUCT", seller_sku=item.seller_sku,
        quantity=3, currency="PHP", line_total_amount=30)
    invoke(True, 3)
    rows = _sku_rows(SalesOrder.objects.filter(tenant=sku.tenant), RefundReturn.objects.none(), True)
    assert len(rows) == 1
    assert rows[0]["units_sold"] == 7
    assert Decimal(rows[0]["gross_sales"]) == Decimal("230")
    assert rows[0]["order_count"] == 2
    assert rows[0]["platform_product_id"] == ""


def test_source_code_search_still_finds_linked_sales_sku(links):
    item, _, actor, invoke = links
    invoke(True)
    grant(actor, "sales_management.skus.view")
    data = client_for(actor).get("/api/internal/sales-management/skus/", {"sku": item.seller_sku}).json()["data"]
    assert data["count"] == 1
    assert data["results"][0]["internal_sku"] == "NEW"


def test_refund_reuses_linked_order_without_consuming_or_changing_facts(links):
    item, sku, _, invoke = links
    order = item.sales_order
    run = create_run(sku.tenant, "refund_return", "link-refund")
    refund = RefundReturn.objects.create(tenant=sku.tenant, platform=order.platform, store=order.store,
        sales_order=order, source_run=run, external_return_id="R", case_type="return_refund",
        raw_status="COMPLETED", normalized_status="completed", requested_at_utc=NOW,
        updated_at_utc=NOW, currency="PHP", refund_amount=20, payload_hash="a" * 64)
    row = RefundReturnItem.objects.create(refund_return=refund, sales_order_item=item,
        external_return_item_id="RI", quantity=1, currency="PHP", refund_amount=20)
    assert invoke()["refunds"] == 1
    invoke(True, 2)
    row.refresh_from_db()
    assert row.internal_sku_id == sku.id
    assert row.refund_amount == 20
