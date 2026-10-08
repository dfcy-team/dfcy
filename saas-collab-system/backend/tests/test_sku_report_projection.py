from decimal import Decimal

import pytest

from apps.commerce.models import RefundReturn, RefundReturnItem, SalesOrder, SalesOrderItem
from apps.products.models import ProductSKU, ProductSPU
from apps.sales_management.reporting import sku_report
from tests.test_sales_management import client_for, create_order, create_run, create_scope, grant, user_for

pytestmark = pytest.mark.django_db


def test_sku_projection_preserves_first_seen_order_and_sales_refund_metadata():
    tenant, platform, store, _ = create_scope("sku-projection")
    order = create_order(tenant, store, "sku-projection", "60")
    first = order.items.get()
    first.seller_sku = "FIRST"
    first.item_name_snapshot = "First product"
    first.variation_snapshot = "Blue / Large"
    first.line_total_amount = Decimal("30")
    first.save()
    second = SalesOrderItem.objects.create(
        sales_order=order,
        external_line_id="second-line",
        seller_sku="SECOND",
        platform_product_id="PRODUCT-2",
        platform_variant_id="VARIANT-2",
        item_name_snapshot="Second product",
        variation_snapshot="Red / Small",
        quantity=2,
        line_total_amount=30,
        currency="PHP",
    )
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SKU-PROJECTION-SPU", product_name="Mapped")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="INTERNAL-FIRST")
    first.internal_sku = sku
    first.save()

    refund = RefundReturn.objects.create(
        tenant=tenant,
        platform=platform,
        store=store,
        sales_order=order,
        source_run=create_run(tenant, "refund_return", "sku-projection"),
        external_return_id="sku-projection-return",
        case_type="return_refund",
        raw_status="COMPLETED",
        normalized_status="completed",
        requested_at_utc=order.created_at_utc,
        updated_at_utc=order.created_at_utc,
        currency="PHP",
        refund_amount=5,
        payload_hash="a" * 64,
    )
    RefundReturnItem.objects.create(
        refund_return=refund,
        external_return_item_id="sku-projection-return-line",
        seller_sku=second.seller_sku,
        platform_product_id=second.platform_product_id,
        platform_variant_id=second.platform_variant_id,
        item_name_snapshot="Second product refund",
        quantity=1,
        currency="PHP",
        refund_amount=5,
    )

    rows, _, _ = sku_report(SalesOrder.objects.filter(tenant=tenant), RefundReturn.objects.filter(tenant=tenant), "store")

    assert [row["sku"] for row in rows] == ["INTERNAL-FIRST", "SECOND"]
    assert rows[0]["mapping_status"] == "mapped"
    assert rows[0]["internal_sku"] == "INTERNAL-FIRST"
    assert rows[0]["seller_sku"] == "FIRST"
    assert rows[0]["product_name"] == "First product"
    assert rows[0]["variation"] == "Blue / Large"
    assert rows[1]["mapping_status"] == "unmapped"
    assert rows[1]["platform_product_id"] == "PRODUCT-2"
    assert rows[1]["platform_variant_id"] == "VARIANT-2"
    assert rows[1]["product_name"] == "Second product / Second product refund"
    assert rows[1]["variation"] == "Red / Small"
    assert rows[1]["refund_amount"] == Decimal("5")
    assert rows[0]["gross_sales"] == rows[1]["gross_sales"] == Decimal("30")
    viewer = user_for(tenant, "sku-projection-viewer")
    grant(viewer, "sales_management.skus.view")
    response = client_for(viewer).get("/api/internal/commerce/sales/skus/", {
        "report": "true", "ordering": "-gross_sales", "page_size": 1,
    })
    assert response.status_code == 200
    assert response.json()["data"]["results"][0]["sku"] == "INTERNAL-FIRST"
