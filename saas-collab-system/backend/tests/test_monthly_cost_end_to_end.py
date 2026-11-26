from datetime import date,datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
from unittest.mock import patch
import pytest
from django.test import override_settings
from apps.products.monthly_cost_reconciliation import register_inventory_evidence,seed_opening_balances
from apps.products.monthly_cost_models import MonthlyProductCost
from apps.products.monthly_cost_services import finalize_month
from apps.products.monthly_cost_adjustments import register_adjustment,allocate_adjustment
from apps.products.monthly_cost_schedule import finalize_ready_months
from apps.products.tasks import aggregate_monthly_product_cost_sources
from tests.test_monthly_product_costs import monthly_record

pytestmark=pytest.mark.django_db

def stock(row,boundary,qty):
 return register_inventory_evidence(tenant=row.tenant,warehouse=row.warehouse,boundary=boundary,
  source_key=f"e2e:{boundary}",snapshot_at=datetime(boundary.year,boundary.month,1,tzinfo=ZoneInfo("Asia/Shanghai")),
  quantities={str(row.sku_id):str(qty)},metadata={"complete":True,"quantity_basis":"on_hand","as_of_boundary":True,"source_reference":"verified-WMS"})

@override_settings(MONTHLY_PRODUCT_COST_ENABLED=True)
def test_two_month_pipeline_late_fee_changes_current_only(monthly_record):
 row=monthly_record
 seed_opening_balances(stock(row,date(2025,4,1),10),unit_costs={str(row.sku_id):"2"})
 stock(row,date(2025,5,1),15)
 april=dict(sku_id=row.sku_id,warehouse_id=row.warehouse_id,receipt_quantity=Decimal(10),receipt_amount=Decimal(60),outbound_quantity=Decimal(5),is_complete=True,source_complete=True,missing_reasons=[],source_keys=["receipt:one","outbound:one"])
 response=dict(items=[april],source_complete=True,truncated=False,unmapped_outbounds=0,ambiguous_outbounds=0,pending_reason="")
 with patch("apps.products.monthly_cost_sources.aggregate_month",return_value=response):
  first=aggregate_monthly_product_cost_sources.run(row.tenant_id,"2025-04-01")
  assert first["errors"]==[]
  row.refresh_from_db();count=row.versions.count()
  aggregate_monthly_product_cost_sources.run(row.tenant_id,"2025-04-01")
  row.refresh_from_db();assert row.versions.count()==count
  closed=finalize_ready_months.run(row.tenant_id)
  assert closed["finalized"]==1
 row.refresh_from_db();old_snapshot=row.versions.order_by("-version_no").first().snapshot
 delta=register_adjustment(tenant_id=row.tenant_id,sku_id=row.sku_id,warehouse_id=row.warehouse_id,receipt_line_id=77,
  original_month=date(2025,4,1),effective_month=date(2025,5,1),source_key="late-invoice:one",delta_amount="10",evidence={"source_reference":"invoice"})
 delta=allocate_adjustment(delta,original_quantity=10)
 assert delta.inventory_amount==Decimal("7.5000") and delta.sold_amount==Decimal("2.5000")
 # Actual source collector now consumes persisted adjustments and rolls forward
 # the finalized opening even in a month with no new receipt or sale.
 result=aggregate_monthly_product_cost_sources.run(row.tenant_id,"2025-05-01")
 assert result["errors"]==[]
 may=MonthlyProductCost.objects.get(tenant_id=row.tenant_id,sku_id=row.sku_id,warehouse_id=row.warehouse_id,month=date(2025,5,1))
 assert may.opening_amount==Decimal("60")
 assert may.adjustment_amount==Decimal("7.5")
 assert may.historical_sold_adjustment==Decimal("2.5")
 assert may.unit_cost==Decimal("4.5")
 row.refresh_from_db();assert row.versions.order_by("-version_no").first().snapshot==old_snapshot
