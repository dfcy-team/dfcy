from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import CustomUser

from .models import (
    ProductSKU,
    ProductSPU,
    ProductStatus,
    ProductStatusRecommendation,
    ProductStatusSnapshot,
    ProductStatusTransition,
)


HIGH_RISK_STATUSES = {
    ProductStatus.CLEARANCE,
    ProductStatus.STOPPED,
    ProductStatus.ARCHIVED,
}

ALLOWED_TRANSITIONS = {
    ProductStatus.NEW: {ProductStatus.ACTIVE, ProductStatus.STOPPED},
    ProductStatus.ACTIVE: {ProductStatus.SLOW_MOVING, ProductStatus.CLEARANCE_CANDIDATE, ProductStatus.STOPPED},
    ProductStatus.SLOW_MOVING: {ProductStatus.ACTIVE, ProductStatus.CLEARANCE_CANDIDATE, ProductStatus.STOPPED},
    ProductStatus.CLEARANCE_CANDIDATE: {ProductStatus.CLEARANCE, ProductStatus.STOPPED},
    ProductStatus.CLEARANCE: {ProductStatus.STOPPED, ProductStatus.ARCHIVED},
    ProductStatus.STOPPED: {ProductStatus.ARCHIVED, ProductStatus.ACTIVE},
    ProductStatus.ARCHIVED: set(),
}


def get_current_status(spu=None, sku=None):
    transition = (
        ProductStatusTransition.objects.filter(spu=spu, sku=sku)
        .order_by("-created_at", "-id")
        .first()
    )
    if transition:
        return transition.to_status
    return ProductStatus.NEW


def assert_product_target(tenant, spu=None, sku=None):
    if not spu and not sku:
        raise ValidationError("Either spu or sku is required.")
    if spu and spu.tenant_id != tenant.id:
        raise ValidationError("SPU does not belong to current tenant.")
    if sku and sku.tenant_id != tenant.id:
        raise ValidationError("SKU does not belong to current tenant.")
    if spu and sku and sku.spu_id != spu.id:
        raise ValidationError("SKU does not belong to SPU.")


def create_status_recommendation(
    tenant,
    source,
    recommended_status,
    metrics_payload,
    reason_code,
    reason_detail="",
    confidence=Decimal("0.8000"),
    spu=None,
    sku=None,
    source_reference="",
):
    assert_product_target(tenant, spu=spu, sku=sku)
    snapshot = ProductStatusSnapshot.objects.create(
        tenant=tenant,
        spu=spu,
        sku=sku,
        source=source,
        source_reference=source_reference,
        metrics_payload=metrics_payload,
        calculated_status=recommended_status,
    )
    return ProductStatusRecommendation.objects.create(
        tenant=tenant,
        spu=spu,
        sku=sku,
        recommended_status=recommended_status,
        reason_code=reason_code,
        reason_detail=reason_detail,
        confidence=confidence,
        source_snapshot=snapshot,
    )


def evaluate_mock_status(tenant, user, spu_id=None, sku_id=None, metrics=None, source=ProductStatusSnapshot.Source.SYSTEM_RULE):
    spu = ProductSPU.objects.filter(id=spu_id, tenant=tenant).first() if spu_id else None
    sku = ProductSKU.objects.filter(id=sku_id, tenant=tenant).first() if sku_id else None
    metrics = metrics or {"sales_30d": 0, "stock_days": 120}
    sales_30d = int(metrics.get("sales_30d", 0))
    stock_days = int(metrics.get("stock_days", 0))
    if sales_30d == 0 and stock_days >= 180:
        status = ProductStatus.CLEARANCE_CANDIDATE
        reason = "zero_sales_high_stock"
    elif sales_30d < 5 and stock_days >= 90:
        status = ProductStatus.SLOW_MOVING
        reason = "low_sales_high_stock"
    else:
        status = ProductStatus.ACTIVE
        reason = "demo_metrics_active"
    return create_status_recommendation(
        tenant=tenant,
        source=source,
        recommended_status=status,
        metrics_payload=metrics,
        reason_code=reason,
        reason_detail="Generated from demo metrics only.",
        spu=spu,
        sku=sku,
        source_reference=f"mock-evaluation:{getattr(user, 'id', 'system')}",
    )


def _assert_internal_confirmer(user):
    if not user or not getattr(user, "is_authenticated", False):
        raise PermissionDenied("Authentication required.")
    if user.user_type != CustomUser.UserType.INTERNAL:
        raise PermissionDenied("Only internal users can confirm product status.")


def confirm_recommendation(recommendation, user, reason=""):
    _assert_internal_confirmer(user)
    if recommendation.tenant_id != user.tenant_id:
        raise PermissionDenied("Recommendation does not belong to current tenant.")
    if recommendation.status != ProductStatusRecommendation.Status.PENDING:
        raise ValidationError("Recommendation has already been handled.")

    from_status = get_current_status(spu=recommendation.spu, sku=recommendation.sku)
    to_status = recommendation.recommended_status
    if to_status not in ALLOWED_TRANSITIONS.get(from_status, set()):
        raise ValidationError("Illegal product status transition.")
    if to_status in HIGH_RISK_STATUSES and not (user.is_staff or getattr(user, "is_superuser", False)):
        raise PermissionDenied("High-risk product status requires authorized internal confirmation.")

    with transaction.atomic():
        recommendation.status = ProductStatusRecommendation.Status.CONFIRMED
        recommendation.confirmed_by = user
        recommendation.confirmed_at = timezone.now()
        recommendation.save(update_fields=["status", "confirmed_by", "confirmed_at"])
        transition = ProductStatusTransition.objects.create(
            tenant=recommendation.tenant,
            spu=recommendation.spu,
            sku=recommendation.sku,
            from_status=from_status,
            to_status=to_status,
            trigger_type=ProductStatusTransition.TriggerType.MANUAL_CONFIRM,
            recommendation=recommendation,
            approved_by=user,
            reason=reason,
        )
    return transition


def reject_recommendation(recommendation, user, reason=""):
    _assert_internal_confirmer(user)
    if recommendation.tenant_id != user.tenant_id:
        raise PermissionDenied("Recommendation does not belong to current tenant.")
    if recommendation.status != ProductStatusRecommendation.Status.PENDING:
        raise ValidationError("Recommendation has already been handled.")
    recommendation.status = ProductStatusRecommendation.Status.REJECTED
    recommendation.confirmed_by = user
    recommendation.confirmed_at = timezone.now()
    recommendation.save(update_fields=["status", "confirmed_by", "confirmed_at"])
    ProductStatusTransition.objects.create(
        tenant=recommendation.tenant,
        spu=recommendation.spu,
        sku=recommendation.sku,
        from_status=get_current_status(spu=recommendation.spu, sku=recommendation.sku),
        to_status=get_current_status(spu=recommendation.spu, sku=recommendation.sku),
        trigger_type=ProductStatusTransition.TriggerType.MANUAL_REJECT,
        recommendation=recommendation,
        approved_by=user,
        reason=reason,
    )
    return recommendation
