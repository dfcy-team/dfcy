"""Late receipt-price deltas allocated against monthly quantity provenance.

The auxiliary allocation is proportional to each month's available quantity.
It does not change the month-average inventory valuation method. Transfers or
unidentified returns require explicit source evidence instead of a guessed lot.
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from .monthly_cost_models import MonthlyCostAdjustment, MonthlyProductCost, MonthlyCostMovement

ZERO=Decimal(0)
UNIT=Decimal("0.0001")


def next_month(month):
    return date(month.year+(month.month==12),month.month%12+1,1)


def business_month(stamp):
    zone=ZoneInfo(getattr(settings,"MONTHLY_PRODUCT_COST_TIMEZONE","Asia/Shanghai"))
    return stamp.astimezone(zone).date().replace(day=1)


def origin_remaining(*,tenant_id,sku_id,warehouse_id,original_month,effective_month,quantity):
    """Return quantity at effective-month opening, with finalized lineage evidence."""
    remaining=Decimal(quantity)
    if remaining<=0:
        raise ValidationError("Original receipt quantity must be positive")
    month=original_month; lineage=[]
    while month<effective_month:
        record=MonthlyProductCost.objects.filter(tenant_id=tenant_id,sku_id=sku_id,
            warehouse_id=warehouse_id,month=month,status="finalized").first()
        if not record:
            raise ValidationError(f"Missing finalized provenance for {month:%Y-%m}")
        if MonthlyCostMovement.objects.filter(tenant_id=tenant_id,sku_id=sku_id,warehouse_id=warehouse_id,
            month=month,kind__in=("transfer_in","transfer_out","return","count_in")).exists():
            raise ValidationError("Transferred or returned origins require reviewed remaining-quantity evidence")
        available=record.opening_quantity+record.receipt_quantity+record.other_in_quantity
        if available<=0 or remaining>available or record.closing_quantity<0 or record.closing_quantity>available:
            raise ValidationError("Origin quantity is inconsistent with finalized inventory")
        remaining=remaining*record.closing_quantity/available
        lineage.append({"monthly_cost_id":record.pk,"version":record.version_no,
            "available":str(available),"closing":str(record.closing_quantity)})
        month=next_month(month)
    return remaining,lineage


@transaction.atomic
def allocate_adjustment(adjustment, *, original_quantity, remaining_quantity=None, evidence=None):
    adjustment=MonthlyCostAdjustment.objects.select_for_update().get(pk=adjustment.pk)
    if adjustment.status=="allocated":
        return adjustment
    if MonthlyProductCost.objects.filter(tenant_id=adjustment.tenant_id,sku_id=adjustment.sku_id,
        warehouse_id=adjustment.warehouse_id,month=adjustment.effective_month,status="finalized").exists():
        raise ValidationError("Adjustment cannot modify a finalized period")
    total=Decimal(original_quantity)
    if remaining_quantity is None:
        remaining,lineage=origin_remaining(tenant_id=adjustment.tenant_id,sku_id=adjustment.sku_id,
            warehouse_id=adjustment.warehouse_id,original_month=adjustment.original_month,
            effective_month=adjustment.effective_month,quantity=total)
        proof={"method":"monthly_proportional_quantity","lineage":lineage}
    else:
        remaining=Decimal(remaining_quantity)
        if not evidence or not evidence.get("reviewed") or not evidence.get("source_reference"):
            raise ValidationError("Reviewed origin evidence is required for an override")
        proof={"method":"reviewed_origin_quantity",**evidence}
    if not total.is_finite() or not remaining.is_finite() or total<=0 or not ZERO<=remaining<=total:
        raise ValidationError("Remaining origin quantity must be between zero and received quantity")
    inventory=(adjustment.delta_amount*remaining/total).quantize(UNIT,rounding=ROUND_HALF_UP)
    adjustment.inventory_amount=inventory
    adjustment.sold_amount=adjustment.delta_amount-inventory
    adjustment.status="allocated";adjustment.reason=""
    adjustment.evidence={**adjustment.evidence,**proof,"original_quantity":str(total),"remaining_quantity":str(remaining)}
    adjustment.save()
    return adjustment


@transaction.atomic
def register_adjustment(*,tenant_id,sku_id,warehouse_id,receipt_line_id,original_month,effective_month,
                        source_key,delta_amount,evidence=None):
    amount=Decimal(str(delta_amount))
    if not amount.is_finite():
        raise ValidationError("Adjustment amount must be finite")
    record,created=MonthlyCostAdjustment.objects.get_or_create(tenant_id=tenant_id,source_key=source_key,
        defaults=dict(sku_id=sku_id,warehouse_id=warehouse_id,receipt_line_id=receipt_line_id,
            original_month=original_month,effective_month=effective_month,delta_amount=amount,evidence=evidence or {}))
    if not created and (record.delta_amount!=amount or record.sku_id!=sku_id or record.warehouse_id!=warehouse_id
        or record.original_month!=original_month or record.effective_month!=effective_month or record.receipt_line_id!=receipt_line_id):
        raise ValidationError("Adjustment source key was reused with different content")
    return record


def sync_late_adjustments(tenant_id,effective_month):
    """Read immutable supply cost revisions and record only this month's late deltas."""
    from apps.supply_chain.cost_models import CostVersion
    from apps.supply_chain.inbound_costs import receipt_allocations
    from apps.supply_chain.models import InternalStockReceiptLine
    zone=ZoneInfo(getattr(settings,"MONTHLY_PRODUCT_COST_TIMEZONE","Asia/Shanghai"))
    # Stream all revisions in order; zero payment-only revisions never add cost.
    versions=CostVersion.objects.filter(tenant_id=tenant_id,batch__isnull=False,stage="received").order_by("batch_id","sequence","pk")
    receipts={r.pk:r for r in InternalStockReceiptLine.objects.filter(tenant_id=tenant_id).select_related("receipt__inbound")}
    previous={};created=pending=0;keys=[]
    for version in versions.iterator(chunk_size=200):
        version_month=business_month(version.created_at)
        for allocation in receipt_allocations(version):
            receipt_id=allocation.get("receipt_line_id");receipt=receipts.get(receipt_id)
            if receipt is None:
                continue
            occurred=receipt.receipt.inbound.confirmed_at
            if occurred is None:
                continue
            original_month=business_month(occurred)
            current=allocation.get("received_total")
            key=(version.batch_id,receipt_id)
            before=previous.get(key)
            if current is not None:
                previous[key]=Decimal(str(current))
            if version_month==effective_month and original_month<effective_month and before is None and current is not None:
                closed=MonthlyProductCost.objects.filter(tenant_id=tenant_id,sku_id=receipt.sku_id,
                    warehouse_id=receipt.receipt.warehouse_id,month=original_month,status="finalized").exists()
                if closed:
                    record=register_adjustment(tenant_id=tenant_id,sku_id=receipt.sku_id,
                        warehouse_id=receipt.receipt.warehouse_id,receipt_line_id=receipt_id,
                        original_month=original_month,effective_month=effective_month,
                        source_key=f"missing-baseline:{version.pk}:receipt:{receipt_id}",delta_amount=0,
                        evidence={"cost_version_id":version.pk,"observed_amount":str(current),"baseline_unknown":True})
                    record.reason="历史已核定，但原批次金额基线缺失，须补充来源差额依据";record.save()
                    pending+=1
            if version_month!=effective_month or original_month>=effective_month or before is None or current is None:
                continue
            delta=Decimal(str(current))-before
            if delta==0:
                continue
            source_key=f"supply-cost:{version.pk}:receipt:{receipt_id}"
            existing=MonthlyCostAdjustment.objects.filter(tenant_id=tenant_id,source_key=source_key).first()
            if existing and existing.status=="allocated":
                keys.append(source_key)
                continue
            # An old effective month already finalized is never rewritten. A newly
            # discovered delta is posted into the current open month instead.
            target=effective_month
            if MonthlyProductCost.objects.filter(tenant_id=tenant_id,sku_id=receipt.sku_id,
                warehouse_id=receipt.receipt.warehouse_id,month=target,status="finalized").exists():
                target=timezone.localdate().replace(day=1)
            record=register_adjustment(tenant_id=tenant_id,sku_id=receipt.sku_id,
                warehouse_id=receipt.receipt.warehouse_id,receipt_line_id=receipt_id,
                original_month=original_month,effective_month=target,source_key=source_key,delta_amount=delta,
                evidence={"cost_version_id":version.pk,"before":str(before),"after":str(current),"original_effective_month":effective_month.isoformat()})
            try:
                allocate_adjustment(record,original_quantity=receipt.received_quantity)
            except ValidationError as exc:
                if record.status!="allocated":
                    record.reason=str(exc)[:255];record.save()
                pending+=1
            created+=1;keys.append(source_key)
    return {"processed":created,"pending":pending,"source_keys":keys}
