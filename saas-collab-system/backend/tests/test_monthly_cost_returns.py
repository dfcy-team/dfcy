from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import patch

from django.test import SimpleTestCase
import pytest

from apps.products.monthly_cost_returns import add_return_inputs


@pytest.mark.django_db
def test_cross_month_uses_real_outbound_and_finalized_cost_casefolded_and_quantized():
    from apps.commerce.models import SalesOrder
    from apps.integrations.models import PlatformIntegrationConfig, SyncJob, SyncRun
    from apps.masterdata.models import PlatformMaster, StoreMaster, WarehouseMaster
    from apps.products.models import ProductSKU, ProductSPU
    from apps.products.monthly_cost_models import MonthlyProductCost
    from apps.sales_management.aftersales_models import AftersalesCase, ReturnAllocation, WarehouseReturnLine, WarehouseReturnReceipt
    from apps.sales_management.warehouse_order_models import OrderWarehouseLookup, WarehouseOutboundLine
    from apps.tenants.models import Tenant

    tenant = Tenant.objects.create(name="ReturnCost", code="return-cost")
    platform = PlatformMaster.objects.create(tenant=tenant, code="return-platform", name="P", platform_type="shopee")
    store = StoreMaster.objects.create(tenant=tenant, platform=platform, code="return-store", name="S", country_code="MY", currency="MYR", timezone="Asia/Kuala_Lumpur")
    warehouse = WarehouseMaster.objects.create(tenant=tenant, code="return-wh", name="W", country_code="MY", warehouse_type="owned")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="RETURN-SPU", product_name="P")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="RETURN-SKU", product_name="P")
    user = __import__("apps.accounts.models", fromlist=["CustomUser"]).CustomUser.objects.create_user(username="return-cost", tenant=tenant, user_type="internal")
    auth = PlatformIntegrationConfig.objects.create(tenant=tenant, platform="shopee", account_alias="ret-cost", created_by=user)
    job = SyncJob.objects.create(tenant=tenant, integration_config=auth, resource_type="sales_order")
    run = SyncRun.objects.create(tenant=tenant, sync_job=job, run_id="ret-cost-run", idempotency_key="ret-cost-key")
    order = SalesOrder.objects.create(tenant=tenant, platform=platform, store=store, authorization=auth, source_run=run,
        external_order_id="RET-ORDER", raw_status="COMPLETED", normalized_status="completed", status_mapping_version="1",
        created_at_utc=datetime(2026, 4, 7, tzinfo=timezone.utc), updated_at_utc=datetime(2026, 4, 7, tzinfo=timezone.utc),
        business_date=date(2026, 4, 7), currency="MYR", payload_hash="a" * 64)
    MonthlyProductCost.objects.create(tenant=tenant, sku=sku, warehouse=warehouse, month=date(2026, 4, 1),
        status="finalized", unit_cost=Decimal("1.234567"))
    lookup = OrderWarehouseLookup.objects.create(order=order)
    WarehouseOutboundLine.objects.create(lookup=lookup, tenant=tenant, warehouse=warehouse, site_code="X", document="D",
        document_key="d" * 64, identity_key="i" * 64, shipped_at=datetime(2026, 4, 7, tzinfo=timezone.utc), warehouse_sku="return-sku", quantity=4)
    receipt = WarehouseReturnReceipt.objects.create(tenant=tenant, warehouse=warehouse, return_no="RET-1", received_at=datetime(2026, 5, 7, tzinfo=timezone.utc))
    line = WarehouseReturnLine.objects.create(receipt=receipt, sku="RETURN-SKU", received_quantity=2)
    case = AftersalesCase.objects.create(tenant=tenant, store=store, source_key="ret-case", order=order, requires_return=True)
    ReturnAllocation.objects.create(line=line, case=case, case_sku="RETURN-SKU", quantity=2)
    rows = {(sku.pk, warehouse.pk): dict(outbound_quantity=Decimal(0), other_in_quantity=Decimal(0), other_in_amount=Decimal(0), is_complete=True, missing_reasons=[], source_keys=[])}
    assert add_return_inputs(tenant.pk, date(2026, 5, 1), date(2026, 6, 1), rows, {"return-sku": {sku.pk}}) == set()
    assert rows[(sku.pk, warehouse.pk)]["other_in_quantity"] == Decimal(2)
    assert rows[(sku.pk, warehouse.pk)]["other_in_amount"] == Decimal("2.4691")


class MonthlyCostReturnsTests(SimpleTestCase):
    def setUp(self):
        self.start, self.end = date(2026, 5, 1), date(2026, 6, 1)
        case = NS(order=NS(pk=19, business_date=date(2026, 5, 7)))
        allocation = NS(pk=9, quantity=2, case_sku="A", case=case)
        line = NS(pk=4, received_quantity=2, allocations=NS(all=lambda: [allocation]))
        self.receipt = NS(warehouse_id=3, lines=NS(all=lambda: [line]))
        self.rows = {(8, 3): dict(outbound_quantity=Decimal(10), other_in_quantity=Decimal(0),
            other_in_amount=Decimal(0), is_complete=True, missing_reasons=[], source_keys=[])}
        self.aliases = {"a": {8}}
        self.return_qs = NS(filter=lambda **kw: NS(select_related=lambda *a, **k: NS(
            prefetch_related=lambda *a: [self.receipt])))
        outbound_rows = [datetime(2026, 5, 7, tzinfo=timezone.utc)]
        self.outbound_qs = NS(filter=lambda **kw: NS(annotate=lambda **a: NS(
            filter=lambda *x, **k: NS(values_list=lambda *x, **y: outbound_rows))))

    def invoke(self, movements=(), finalized=()):
        mgr = NS(filter=lambda **kw: NS(values_list=lambda *a, **k: movements) if "kind" in kw
                 else NS(values_list=lambda *a, **k: finalized))
        with patch("apps.sales_management.aftersales_models.WarehouseReturnReceipt.objects", self.return_qs), \
             patch("apps.products.monthly_cost_models.MonthlyCostMovement.objects", mgr), \
             patch("apps.products.monthly_cost_models.MonthlyProductCost.objects", mgr), \
             patch("apps.sales_management.warehouse_order_models.WarehouseOutboundLine.objects", self.outbound_qs):
            return add_return_inputs(1, self.start, self.end, self.rows, self.aliases)

    def test_same_month_return_reduces_sales_outbound(self):
        self.assertEqual(self.invoke(), set())
        self.assertEqual(self.rows[(8, 3)]["outbound_quantity"], Decimal(8))

    def test_return_source_key_is_recorded(self):
        self.invoke()
        self.assertIn("return:4:9", self.rows[(8, 3)]["source_keys"])

    def test_existing_movement_is_not_counted_twice(self):
        self.invoke(movements=["return:4:9"])
        self.assertEqual(self.rows[(8, 3)]["outbound_quantity"], Decimal(10))

    def test_partial_allocation_marks_warehouse_gap(self):
        self.receipt.lines.all()[0].allocations.all()[0].quantity = 1
        gaps = self.invoke()
        self.assertEqual(gaps, {3})

    def test_ambiguous_sku_marks_warehouse_gap(self):
        self.aliases["a"] = {8, 9}
        self.assertEqual(self.invoke(), {3})

    def test_same_month_return_cannot_exceed_sales_quantity(self):
        self.rows[(8, 3)]["outbound_quantity"] = Decimal(1)
        self.assertEqual(self.invoke(), {3})
        self.assertFalse(self.rows[(8, 3)]["is_complete"])

    def test_unmatched_sale_marks_missing(self):
        self.receipt.lines.all()[0].allocations.all()[0].case.order = None
        self.assertEqual(self.invoke(), {3})
        self.assertFalse(self.rows[(8, 3)]["is_complete"])

