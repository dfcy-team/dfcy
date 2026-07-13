import hashlib
import json
from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import write_operation_log
from apps.permissions.services import check_user_permission

from .models import ReplenishmentRecommendation


def _decimal(value, field_name, *, nullable=False):
    if value is None and nullable:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(f"{field_name} must be numeric.") from exc
    if result < 0:
        raise ValidationError(f"{field_name} cannot be negative.")
    return result


@transaction.atomic
def evaluate_replenishment(
    *, tenant, sku=None, spu=None, available_stock, in_transit_stock, average_daily_sales,
    safety_stock_days, supplier_lead_days, replenishment_cycle_days,
    evaluated_at=None, formula_version="replenishment-v1",
):
    if not sku and not spu:
        raise ValidationError("A SKU or SPU is required.")
    if sku and sku.tenant_id != tenant.id:
        raise ValidationError("SKU is outside the requested tenant.")
    if spu and spu.tenant_id != tenant.id:
        raise ValidationError("SPU is outside the requested tenant.")
    if sku and spu and sku.spu_id != spu.id:
        raise ValidationError("SKU does not belong to the supplied SPU.")
    available_stock = _decimal(available_stock, "available_stock")
    in_transit_stock = _decimal(in_transit_stock, "in_transit_stock")
    average_daily_sales = _decimal(average_daily_sales, "average_daily_sales", nullable=True)
    safety_stock_days = int(safety_stock_days)
    supplier_lead_days = int(supplier_lead_days)
    replenishment_cycle_days = int(replenishment_cycle_days)
    if min(safety_stock_days, supplier_lead_days, replenishment_cycle_days) < 0:
        raise ValidationError("Day inputs cannot be negative.")

    evaluated_at = evaluated_at or timezone.now()
    total_stock = available_stock + in_transit_stock
    if average_daily_sales is None or average_daily_sales == 0:
        suggested_quantity = 0
        suggested_date = evaluated_at.date()
        confidence = Decimal("0.0000")
        reason_code = "insufficient_sales_data"
        reason_detail = "Average daily sales is unavailable; no quantity was inferred."
    else:
        coverage_days = total_stock / average_daily_sales
        demand_days = safety_stock_days + supplier_lead_days + replenishment_cycle_days
        demand_quantity = average_daily_sales * Decimal(demand_days)
        gap = max(Decimal(0), demand_quantity - total_stock)
        suggested_quantity = int(gap.quantize(Decimal("1"), rounding=ROUND_CEILING))
        days_until_order = max(
            Decimal(0),
            coverage_days - Decimal(safety_stock_days + supplier_lead_days),
        )
        suggested_date = evaluated_at.date() + timedelta(
            days=int(days_until_order.quantize(Decimal("1"), rounding=ROUND_FLOOR))
        )
        confidence = Decimal("1.0000")
        reason_code = "coverage_gap" if suggested_quantity else "stock_sufficient"
        reason_detail = (
            "Suggested quantity covers safety stock, supplier lead time, and replenishment cycle."
            if suggested_quantity
            else "Current available and in-transit stock covers the configured demand window."
        )

    snapshot = {
        "product": f"sku:{sku.id}" if sku else f"spu:{spu.id}",
        "available_stock": str(available_stock),
        "in_transit_stock": str(in_transit_stock),
        "average_daily_sales": str(average_daily_sales) if average_daily_sales is not None else None,
        "safety_stock_days": safety_stock_days,
        "supplier_lead_days": supplier_lead_days,
        "replenishment_cycle_days": replenishment_cycle_days,
        "formula_version": formula_version,
    }
    dedup_key = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode("utf-8")).hexdigest()
    recommendation, _ = ReplenishmentRecommendation.objects.get_or_create(
        tenant=tenant,
        dedup_key=dedup_key,
        defaults={
            "spu": spu or (sku.spu if sku else None),
            "sku": sku,
            "available_stock": available_stock,
            "in_transit_stock": in_transit_stock,
            "average_daily_sales": average_daily_sales,
            "safety_stock_days": safety_stock_days,
            "supplier_lead_days": supplier_lead_days,
            "replenishment_cycle_days": replenishment_cycle_days,
            "suggested_quantity": suggested_quantity,
            "suggested_date": suggested_date,
            "confidence": confidence,
            "reason_code": reason_code,
            "reason_detail": reason_detail,
            "source_summary": {"mode": "mock", "contains_real_data": False},
            "formula_version": formula_version,
        },
    )
    return recommendation


@transaction.atomic
def review_recommendation(*, recommendation, actor, decision, reason):
    if (
        not actor
        or not actor.is_active
        or actor.user_type != "internal"
        or not check_user_permission(actor, "replenishment.review")
    ):
        raise ValidationError("An authorized internal reviewer is required.")
    recommendation = ReplenishmentRecommendation.objects.select_for_update().get(
        pk=recommendation.pk,
        tenant=actor.tenant,
    )
    if recommendation.status != ReplenishmentRecommendation.Status.SUGGESTED:
        raise ValidationError("Only suggested recommendations can be reviewed.")
    if decision not in {ReplenishmentRecommendation.Status.ACCEPTED, ReplenishmentRecommendation.Status.REJECTED}:
        raise ValidationError("Unsupported replenishment review decision.")
    reason = str(reason or "").strip()
    if not reason:
        raise ValidationError("A review reason is required.")
    recommendation.status = decision
    recommendation.reviewed_by = actor
    recommendation.reviewed_at = timezone.now()
    recommendation.review_reason = reason
    recommendation._review_service_write = True
    recommendation.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_reason", "updated_at"])
    write_operation_log(
        tenant=recommendation.tenant,
        user=actor,
        module="replenishment",
        action=f"recommendation.{decision}",
        object_type="ReplenishmentRecommendation",
        object_id=recommendation.id,
        before_data={"status": ReplenishmentRecommendation.Status.SUGGESTED},
        after_data={"status": decision, "reason": reason, "purchase_order_created": False},
    )
    return recommendation
