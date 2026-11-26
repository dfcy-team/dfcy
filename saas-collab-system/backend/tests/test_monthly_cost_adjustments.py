from datetime import date
from decimal import Decimal
import pytest
from django.core.exceptions import ValidationError
from apps.products.monthly_cost_models import MonthlyCostAdjustment, MonthlyProductCost, MonthlyCostMovement
from apps.products.monthly_cost_services import recalculate_month,finalize_month
from apps.products.monthly_cost_adjustments import register_adjustment,allocate_adjustment,origin_remaining
from tests.test_monthly_product_costs import monthly_record
pytestmark=pytest.mark.django_db
W={"source_complete":True,"inventory_reconciled":True,"opening_verified":True}

def adjustment(row,delta="10",key="late:1"):
    return register_adjustment(tenant_id=row.tenant_id,sku_id=row.sku_id,warehouse_id=row.warehouse_id,
        receipt_line_id=1,original_month=date(2025,4,1),effective_month=date(2025,5,1),
        source_key=key,delta_amount=delta,evidence={"source_reference":"invoice"})

def test_proportional_remainder_conserves_amount_and_leaves_history(monthly_record):
    original=finalize_month(monthly_record,W)
    old=original.versions.order_by("-version_no").first().snapshot
    item=allocate_adjustment(adjustment(original),original_quantity=10)
    assert item.inventory_amount==Decimal("7.5000")
    assert item.sold_amount==Decimal("2.5000")
    original.refresh_from_db();assert original.versions.order_by("-version_no").first().snapshot==old

def test_repeat_source_is_idempotent(monthly_record):
    first=adjustment(monthly_record)
    assert adjustment(monthly_record).pk==first.pk
    assert MonthlyCostAdjustment.objects.count()==1

def test_reused_source_different_delta_rejected(monthly_record):
    adjustment(monthly_record)
    with pytest.raises(ValidationError,match="reused"):
        adjustment(monthly_record,"11")

def test_all_sold_delta_not_spread_to_new_stock(monthly_record):
    monthly_record.outbound_quantity=20;monthly_record.save();finalize_month(monthly_record,W)
    item=allocate_adjustment(adjustment(monthly_record),original_quantity=10)
    assert item.inventory_amount==0 and item.sold_amount==10

def test_missing_provenance_stays_pending(monthly_record):
    item=adjustment(monthly_record)
    with pytest.raises(ValidationError,match="Missing finalized"):
        allocate_adjustment(item,original_quantity=10)
    item.refresh_from_db();assert item.status=="pending"

def test_reviewed_override_requires_evidence(monthly_record):
    with pytest.raises(ValidationError,match="Reviewed"):
        allocate_adjustment(adjustment(monthly_record),original_quantity=10,remaining_quantity=4)
    item=allocate_adjustment(adjustment(monthly_record),original_quantity=10,remaining_quantity=4,
        evidence={"reviewed":True,"source_reference":"third-party-origin"})
    assert item.inventory_amount==4 and item.sold_amount==6

def test_negative_delta_conserves_and_final_allocation_immutable(monthly_record):
    finalize_month(monthly_record,W)
    item=allocate_adjustment(adjustment(monthly_record,"-10"),original_quantity=10)
    assert item.inventory_amount+item.sold_amount==-10
    with pytest.raises(ValidationError,match="immutable"):
        item.save()

def test_transfer_origin_requires_reviewed_evidence(monthly_record):
    MonthlyCostMovement.objects.create(tenant=monthly_record.tenant,sku=monthly_record.sku,warehouse=monthly_record.warehouse,
        month=monthly_record.month,source_key="transfer:1",kind="transfer_out",quantity=1,evidence={"document":"T1"})
    finalize_month(monthly_record,W)
    with pytest.raises(ValidationError,match="Transferred"):
        allocate_adjustment(adjustment(monthly_record),original_quantity=10)
