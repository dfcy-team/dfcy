from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .monthly_cost_models import MonthlyProductCost, MonthlyProductCostVersion

MONEY_QUANTUM = Decimal("0.000001")


@transaction.atomic
def recalculate_month(record):
    """Recompute one open month with one weighted average price for all outbounds."""
    record = MonthlyProductCost.objects.select_for_update().get(pk=record.pk)
    if record.status == MonthlyProductCost.Status.FINALIZED:
        raise ValidationError("Finalized monthly costs cannot be recalculated")
    previous = MonthlyProductCostVersion.objects.filter(monthly_cost=record).order_by("-version_no").first()
    inputs = {
        "opening_quantity": str(record.opening_quantity),
        "opening_amount": str(record.opening_amount) if record.opening_amount is not None else None,
        "receipt_quantity": str(record.receipt_quantity),
        "receipt_amount": str(record.receipt_amount) if record.receipt_amount is not None else None,
        "adjustment_amount": str(record.adjustment_amount) if record.adjustment_amount is not None else None,
        "outbound_quantity": str(record.outbound_quantity),
        "is_complete": record.is_complete,
        "missing_reason": record.missing_reason,
    }
    if previous and all(previous.snapshot.get(key) == value for key, value in inputs.items()):
        return record
    denominator = record.opening_quantity + record.receipt_quantity
    record.closing_quantity = denominator - record.outbound_quantity
    if not record.is_complete or any(v is None for v in (record.opening_amount, record.receipt_amount, record.adjustment_amount)):
        record.is_complete = False
        record.unit_cost = None
        record.closing_amount = None
        record.missing_reason = record.missing_reason or "Core quantity or amount inputs are incomplete"
    elif denominator <= 0 or record.closing_quantity < 0:
        record.unit_cost = None
        record.closing_amount = None
        record.is_complete = False
        record.missing_reason = "No positive available quantity or negative closing inventory"
    else:
        # A valid zero-cost version is complete and yields Decimal zero, distinct from missing.
        weighted_amount = record.opening_amount + record.receipt_amount + record.adjustment_amount
        if weighted_amount < 0:
            raise ValidationError("Total monthly cost amount cannot be negative")
        record.unit_cost = (weighted_amount / denominator).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
        outbound_amount = (weighted_amount * record.outbound_quantity / denominator).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        record.closing_amount = weighted_amount - outbound_amount
        record.missing_reason = ""
    record.version_no += 1
    record.calculated_at = timezone.now()
    record.save()
    MonthlyProductCostVersion.objects.create(
        monthly_cost=record,
        version_no=record.version_no,
        snapshot={
            "status": record.status,
            "opening_quantity": str(record.opening_quantity),
            "opening_amount": str(record.opening_amount) if record.opening_amount is not None else None,
            "receipt_quantity": str(record.receipt_quantity),
            "receipt_amount": str(record.receipt_amount) if record.receipt_amount is not None else None,
            "adjustment_amount": str(record.adjustment_amount) if record.adjustment_amount is not None else None,
            "outbound_quantity": str(record.outbound_quantity),
            "closing_quantity": str(record.closing_quantity),
            "closing_amount": str(record.closing_amount) if record.closing_amount is not None else None,
            "unit_cost": str(record.unit_cost) if record.unit_cost is not None else None,
            "is_complete": record.is_complete,
            "missing_reason": record.missing_reason,
        },
    )
    return record


@transaction.atomic
def finalize_month(record, watermark):
    """Finalize a complete SKU/warehouse month once its source watermark is supplied."""
    record = MonthlyProductCost.objects.select_for_update().get(pk=record.pk)
    if record.status == MonthlyProductCost.Status.FINALIZED:
        return record
    if record.month >= timezone.localdate().replace(day=1):
        raise ValidationError("Only a completed month can be finalized")
    record = recalculate_month(record)
    if not record.is_complete or record.unit_cost is None:
        raise ValidationError("Incomplete monthly cost cannot be finalized")
    if not isinstance(watermark, dict) or any(watermark.get(key) is not True for key in ("source_complete", "inventory_reconciled", "opening_verified")):
        raise ValidationError("A complete source watermark and reconciled opening/inventory are required to finalize")
    if MonthlyProductCost.objects.filter(tenant_id=record.tenant_id, sku_id=record.sku_id, warehouse_id=record.warehouse_id, month__lt=record.month).exclude(status=MonthlyProductCost.Status.FINALIZED).exists():
        raise ValidationError("Earlier open periods must be finalized first")
    record.watermark = watermark
    record.status = MonthlyProductCost.Status.FINALIZED
    record.finalized_at = timezone.now()
    record.version_no += 1
    snapshot = dict(record.versions.order_by("-version_no").first().snapshot)
    snapshot.update(status=record.status, watermark=watermark)
    record.save()
    MonthlyProductCostVersion.objects.create(monthly_cost=record, version_no=record.version_no, snapshot=snapshot)
    return record
