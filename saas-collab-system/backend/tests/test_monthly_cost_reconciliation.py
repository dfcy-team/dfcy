from datetime import date,datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
import pytest
from django.core.exceptions import ValidationError
from apps.products.monthly_cost_reconciliation import register_inventory_evidence,seed_opening_balances,reconcile_month
from apps.products.monthly_cost_services import finalize_month
from tests.test_monthly_product_costs import monthly_record
pytestmark=pytest.mark.django_db

def evidence(row,boundary,quantity):
 return register_inventory_evidence(tenant=row.tenant,warehouse=row.warehouse,boundary=boundary,
  source_key=f"stock:{boundary}",snapshot_at=datetime(boundary.year,boundary.month,1,tzinfo=ZoneInfo("Asia/Shanghai")),
  quantities={str(row.sku_id):str(quantity)},metadata={"complete":True,"quantity_basis":"on_hand","as_of_boundary":True,"source_reference":"WMS-export"})

def test_full_opening_snapshot_and_valid_zero(monthly_record):
 source=evidence(monthly_record,monthly_record.month,10)
 result=seed_opening_balances(source,unit_costs={str(monthly_record.sku_id):"0"})
 monthly_record.refresh_from_db()
 assert result["missing"]==0 and monthly_record.opening_amount==0

def test_incomplete_snapshot_cannot_be_registered(monthly_record):
 with pytest.raises(ValidationError,match="complete physical"):
  register_inventory_evidence(tenant=monthly_record.tenant,warehouse=monthly_record.warehouse,boundary=monthly_record.month,
   source_key="partial",snapshot_at=datetime(2025,4,1,tzinfo=ZoneInfo("Asia/Shanghai")),quantities={},metadata={"complete":False})

def test_snapshot_balance_allows_automatic_finalization(monthly_record):
 source=evidence(monthly_record,monthly_record.month,10)
 seed_opening_balances(source,unit_costs={str(monthly_record.sku_id):"2"})
 monthly_record.refresh_from_db();monthly_record.watermark["source_complete"]=True;monthly_record.save()
 evidence(monthly_record,date(2025,5,1),15)
 row=reconcile_month(monthly_record)
 assert row.watermark["inventory_reconciled"] is True
 assert finalize_month(row,row.watermark).status=="finalized"

def test_stock_difference_prevents_finalization(monthly_record):
 source=evidence(monthly_record,monthly_record.month,10)
 seed_opening_balances(source,unit_costs={str(monthly_record.sku_id):"2"})
 monthly_record.refresh_from_db();monthly_record.watermark["source_complete"]=True;monthly_record.save()
 evidence(monthly_record,date(2025,5,1),14)
 row=reconcile_month(monthly_record)
 assert row.watermark["inventory_difference"]=="-1.0000"
 with pytest.raises(ValidationError):finalize_month(row,row.watermark)
