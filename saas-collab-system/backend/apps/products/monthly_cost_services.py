from django.conf import settings
from zoneinfo import ZoneInfo
"""Atomic month-average valuation and immutable finalization."""
from decimal import Decimal, ROUND_HALF_UP
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from .monthly_cost_models import MonthlyProductCost, MonthlyProductCostVersion, MonthlyCostAdjustment

MONEY_QUANTUM = Decimal("0.0001")
INPUT_FIELDS = ("opening_quantity", "opening_amount", "receipt_quantity", "receipt_amount",
    "adjustment_amount", "outbound_quantity", "other_in_quantity", "other_in_amount",
    "other_out_quantity", "historical_sold_adjustment", "is_complete")


def _inputs(record):
    result = {key: (str(value) if isinstance(value, Decimal) else value)
            for key in INPUT_FIELDS for value in [getattr(record, key)]}
    result["source_metadata"] = {key: record.watermark.get(key) for key in ("source_keys", "contains_estimates", "payment_state", "opening_evidence_id")}
    return result


def _snapshot(record):
    result = _inputs(record)
    result.update(status=record.status, missing_reason=record.missing_reason, watermark=record.watermark,
        **{key: str(getattr(record,key)) if getattr(record,key) is not None else None
           for key in ("unit_cost", "closing_quantity", "closing_amount", "sales_cost_amount")})
    return result


@transaction.atomic
def recalculate_month(record):
    record = MonthlyProductCost.objects.select_for_update().get(pk=record.pk)
    if record.status == MonthlyProductCost.Status.FINALIZED:
        raise ValidationError("Finalized monthly costs cannot be recalculated")
    previous = record.versions.order_by("-version_no").first()
    inputs = _inputs(record)
    if previous and all(previous.snapshot.get(key) == value for key,value in inputs.items()):
        return record
    denominator = record.opening_quantity + record.receipt_quantity + record.other_in_quantity
    record.closing_quantity = denominator - record.outbound_quantity - record.other_out_quantity
    known = record.is_complete and all(v is not None for v in
        (record.opening_amount, record.receipt_amount, record.adjustment_amount, record.other_in_amount))
    if not known:
        record.is_complete=False; record.unit_cost=None; record.closing_amount=None; record.sales_cost_amount=None
        record.missing_reason=record.missing_reason or "Core quantity or amount inputs are incomplete"
    elif denominator < 0 or record.closing_quantity < 0:
        record.is_complete=False; record.unit_cost=None; record.closing_amount=None; record.sales_cost_amount=None
        record.missing_reason="No positive available quantity or negative closing inventory"
    else:
        amount=record.opening_amount+record.receipt_amount+record.other_in_amount+record.adjustment_amount
        if amount < 0:
            raise ValidationError("Total monthly cost amount cannot be negative")
        if denominator == 0:
            if amount != 0:
                raise ValidationError("Zero quantity cannot carry an unexplained stock amount")
            record.unit_cost=Decimal(0); record.closing_amount=Decimal(0); record.sales_cost_amount=Decimal(0)
        else:
            record.unit_cost=(amount/denominator).quantize(Decimal("0.000001"),rounding=ROUND_HALF_UP)
            out_amount=(amount*(record.outbound_quantity+record.other_out_quantity)/denominator).quantize(MONEY_QUANTUM,rounding=ROUND_HALF_UP)
            record.sales_cost_amount=(amount*record.outbound_quantity/denominator).quantize(MONEY_QUANTUM,rounding=ROUND_HALF_UP)
            record.closing_amount=amount-out_amount
        if record.status != MonthlyProductCost.Status.PENDING_REVIEW:
            record.missing_reason=""
    record.version_no+=1
    record.calculated_at=timezone.now()
    record.save()
    MonthlyProductCostVersion.objects.create(monthly_cost=record,version_no=record.version_no,snapshot=_snapshot(record))
    return record


@transaction.atomic
def finalize_month(record, watermark):
    record=MonthlyProductCost.objects.select_for_update().get(pk=record.pk)
    if record.status==MonthlyProductCost.Status.FINALIZED:
        return record
    if record.month>=timezone.localdate(timezone=ZoneInfo(getattr(settings,"MONTHLY_PRODUCT_COST_TIMEZONE","Asia/Shanghai"))).replace(day=1):
        raise ValidationError("Only a completed month can be finalized")
    record=recalculate_month(record)
    if not record.is_complete or record.unit_cost is None:
        raise ValidationError("Incomplete monthly cost cannot be finalized")
    if not isinstance(watermark,dict) or any(watermark.get(key) is not True for key in
        ("source_complete","inventory_reconciled","opening_verified")):
        raise ValidationError("A complete source watermark and reconciled opening/inventory are required to finalize")
    if watermark.get("adjustment_source_pending") or MonthlyCostAdjustment.objects.filter(
        tenant_id=record.tenant_id,sku_id=record.sku_id,warehouse_id=record.warehouse_id,
        effective_month=record.month,status="pending").exists():
        raise ValidationError("Unallocated source adjustments must be resolved first")
    if MonthlyProductCost.objects.filter(tenant_id=record.tenant_id,sku_id=record.sku_id,
        warehouse_id=record.warehouse_id,month__lt=record.month).exclude(status=MonthlyProductCost.Status.FINALIZED).exists():
        raise ValidationError("Earlier open periods must be finalized first")
    record.watermark=watermark
    record.status=MonthlyProductCost.Status.FINALIZED
    record.finalized_at=timezone.now()
    record.version_no+=1
    record.save()
    MonthlyProductCostVersion.objects.create(monthly_cost=record,version_no=record.version_no,snapshot=_snapshot(record))
    return record
