import hashlib
import json
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.audit.services import write_operation_log
from apps.common.security import mask_sensitive_text
from apps.permissions.services import check_user_permission
from apps.permissions.ui_p6_scopes import lifecycle_target_allowed

from .models import (
    ProductLifecycleDecision,
    ProductLifecycleReview,
    ProductLifecycleStage,
    ProductSKU,
    ProductSPU,
)


HIGH_RISK_STAGES = {
    ProductLifecycleStage.CLEARANCE,
    ProductLifecycleStage.STOPPED,
    ProductLifecycleStage.ARCHIVED,
}

ALLOWED_LIFECYCLE_TRANSITIONS = {
    ProductLifecycleStage.NEW_OBSERVATION: {
        ProductLifecycleStage.GROWTH,
        ProductLifecycleStage.STABLE,
        ProductLifecycleStage.SLOW_MOVING_OBSERVATION,
    },
    ProductLifecycleStage.GROWTH: {
        ProductLifecycleStage.STABLE,
        ProductLifecycleStage.SLOW_MOVING_OBSERVATION,
    },
    ProductLifecycleStage.STABLE: {
        ProductLifecycleStage.SLOW_MOVING_OBSERVATION,
        ProductLifecycleStage.CLEARANCE_CANDIDATE,
    },
    ProductLifecycleStage.SLOW_MOVING_OBSERVATION: {
        ProductLifecycleStage.STABLE,
        ProductLifecycleStage.CLEARANCE_CANDIDATE,
    },
    ProductLifecycleStage.CLEARANCE_CANDIDATE: {
        ProductLifecycleStage.SLOW_MOVING_OBSERVATION,
        ProductLifecycleStage.CLEARANCE,
    },
    ProductLifecycleStage.CLEARANCE: {ProductLifecycleStage.STOPPED},
    ProductLifecycleStage.STOPPED: {ProductLifecycleStage.ARCHIVED},
    ProductLifecycleStage.ARCHIVED: set(),
}


def _assert_product(tenant, spu=None, sku=None):
    if not spu and not sku:
        raise ValidationError("A SKU or SPU is required.")
    if spu and spu.tenant_id != tenant.id:
        raise ValidationError("SPU is outside the requested tenant.")
    if sku and sku.tenant_id != tenant.id:
        raise ValidationError("SKU is outside the requested tenant.")
    if spu and sku and sku.spu_id != spu.id:
        raise ValidationError("SKU does not belong to the supplied SPU.")


def _assert_transition(from_stage, to_stage):
    if to_stage not in ALLOWED_LIFECYCLE_TRANSITIONS.get(from_stage, set()):
        raise ValidationError("Illegal product lifecycle transition.")


@transaction.atomic
def evaluate_lifecycle_review(
    *, tenant, current_stage, recommended_stage, review_period_start, review_period_end,
    reason_code, reason_detail, confidence, source_metrics, source_type="mock",
    rule_version="lifecycle-v1", spu=None, sku=None,
):
    _assert_product(tenant, spu=spu, sku=sku)
    _assert_transition(current_stage, recommended_stage)
    if review_period_start > review_period_end:
        raise ValidationError("review_period_start must not exceed review_period_end.")
    confidence = Decimal(str(confidence))
    if confidence < 0 or confidence > 1:
        raise ValidationError("confidence must be between 0 and 1.")
    if source_type not in {"mock", "api", "rpa_readback", "manual"}:
        raise ValidationError("Unsupported lifecycle source type.")
    product_key = f"sku:{sku.id}" if sku else f"spu:{spu.id}"
    snapshot = {
        "product": product_key,
        "current_stage": current_stage,
        "recommended_stage": recommended_stage,
        "period_start": str(review_period_start),
        "period_end": str(review_period_end),
        "source_metrics": source_metrics,
        "source_type": source_type,
        "rule_version": rule_version,
    }
    dedup_key = hashlib.sha256(json.dumps(snapshot, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    review, _ = ProductLifecycleReview.objects.get_or_create(
        tenant=tenant,
        dedup_key=dedup_key,
        defaults={
            "spu": spu or (sku.spu if sku else None),
            "sku": sku,
            "current_stage": current_stage,
            "recommended_stage": recommended_stage,
            "review_period_start": review_period_start,
            "review_period_end": review_period_end,
            "reason_code": reason_code,
            "reason_detail": reason_detail,
            "confidence": confidence,
            "source_metrics": source_metrics,
            "source_type": source_type,
            "rule_version": rule_version,
        },
    )
    return review


def _latest_confirmed_stage(review):
    queryset = ProductLifecycleDecision.objects.filter(
        tenant=review.tenant,
        decision=ProductLifecycleDecision.Decision.CONFIRM,
    )
    queryset = queryset.filter(review__sku=review.sku) if review.sku_id else queryset.filter(review__spu=review.spu, review__sku__isnull=True)
    decision = queryset.order_by("-created_at", "-id").first()
    return decision.to_stage if decision else review.current_stage


@transaction.atomic
def decide_lifecycle_review(*, review, actor, decision, reason):
    if (
        not actor
        or not actor.is_active
        or actor.user_type != "internal"
        or not check_user_permission(actor, "products.lifecycle.confirm")
    ):
        raise PermissionDenied("Lifecycle confirmation permission is required.")
    reason = mask_sensitive_text(str(reason or "").strip())
    if not reason:
        raise ValidationError("A lifecycle decision reason is required.")
    review = ProductLifecycleReview.objects.select_for_update().select_related("spu", "sku").get(
        pk=review.pk,
        tenant=actor.tenant,
    )
    if review.status != ProductLifecycleReview.Status.SUGGESTED:
        raise ValidationError("Lifecycle review has already been handled.")
    if review.spu_id:
        ProductSPU.objects.select_for_update().get(pk=review.spu_id, tenant=actor.tenant)
    if review.sku_id:
        ProductSKU.objects.select_for_update().get(pk=review.sku_id, tenant=actor.tenant)
    current_stage = _latest_confirmed_stage(review)
    if current_stage != review.current_stage:
        raise ValidationError("Lifecycle review is stale for the current product stage.")

    if decision == ProductLifecycleDecision.Decision.CONFIRM:
        _assert_transition(current_stage, review.recommended_stage)
        if review.recommended_stage in HIGH_RISK_STAGES and not check_user_permission(
            actor, "products.lifecycle.high_risk_confirm"
        ):
            raise PermissionDenied("High-risk lifecycle confirmation permission is required.")
        if review.recommended_stage in HIGH_RISK_STAGES and not lifecycle_target_allowed(
            actor,
            "products.lifecycle.high_risk_confirm",
            spu_id=review.spu_id,
            sku_id=review.sku_id,
        ):
            raise PermissionDenied("Lifecycle target is outside the high-risk confirmation data scope.")
        to_stage = review.recommended_stage
        review.status = ProductLifecycleReview.Status.CONFIRMED
    elif decision == ProductLifecycleDecision.Decision.REJECT:
        to_stage = current_stage
        review.status = ProductLifecycleReview.Status.REJECTED
    else:
        raise ValidationError("Unsupported lifecycle decision.")
    review.reviewed_by = actor
    review.reviewed_at = timezone.now()
    review._decision_service_write = True
    review.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])
    decision_record = ProductLifecycleDecision(
        tenant=review.tenant,
        review=review,
        decision=decision,
        from_stage=current_stage,
        to_stage=to_stage,
        actor=actor,
        reason=reason,
    )
    decision_record._decision_service_write = True
    decision_record.save()
    write_operation_log(
        tenant=review.tenant,
        user=actor,
        module="lifecycle",
        action=f"lifecycle_review.{decision}",
        object_type="ProductLifecycleReview",
        object_id=review.id,
        before_data={"stage": current_stage, "status": ProductLifecycleReview.Status.SUGGESTED},
        after_data={
            "stage": to_stage,
            "status": review.status,
            "price_changed": False,
            "listing_changed": False,
            "rpa_triggered": False,
            "reason": reason,
        },
    )
    return decision_record
