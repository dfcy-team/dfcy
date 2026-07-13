from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.audit.models import OperationLog
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.lifecycle_services import decide_lifecycle_review, evaluate_lifecycle_review
from apps.products.models import (
    ProductLifecycleDecision,
    ProductLifecycleReview,
    ProductLifecycleStage,
    ProductSKU,
    ProductSPU,
)
from apps.rpa.models import RPATask
from apps.tenants.models import Tenant


def create_sku(tenant, suffix):
    spu = ProductSPU.objects.create(tenant=tenant, spu_code=f"SPU-{suffix}", product_name="Demo product")
    return ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code=f"SKU-{suffix}")


def create_user(tenant, username, user_type=CustomUser.UserType.INTERNAL):
    return CustomUser.objects.create_user(username=username, tenant=tenant, user_type=user_type)


def grant(user, code, scope_type=DataScope.ScopeType.ALL, config=None):
    role = Role.objects.create(tenant=user.tenant, name=code, code=f"{code}-{user.id}")
    role.permissions.add(Permission.objects.get(code=code))
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=scope_type, config=config or {})


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def create_review(tenant, sku, current=ProductLifecycleStage.NEW_OBSERVATION, recommended=ProductLifecycleStage.GROWTH, source_type="mock", **overrides):
    values = {
        "tenant": tenant,
        "sku": sku,
        "current_stage": current,
        "recommended_stage": recommended,
        "review_period_start": date.today() - timedelta(days=7),
        "review_period_end": date.today(),
        "reason_code": "demo_metrics",
        "reason_detail": "Generated from demo metrics only.",
        "confidence": Decimal("0.8000"),
        "source_metrics": {"sales_trend": "demo"},
        "source_type": source_type,
    }
    values.update(overrides)
    return evaluate_lifecycle_review(**values)


@pytest.mark.django_db
def test_lifecycle_api_and_rpa_sources_only_create_suggestions():
    tenant = Tenant.objects.create(name="Tenant", code="lifecycle-sources")
    api_sku = create_sku(tenant, "API")
    rpa_sku = create_sku(tenant, "RPA")

    api_review = create_review(tenant, api_sku, source_type="api")
    rpa_review = create_review(tenant, rpa_sku, source_type="rpa_readback")

    assert api_review.status == ProductLifecycleReview.Status.SUGGESTED
    assert rpa_review.status == ProductLifecycleReview.Status.SUGGESTED
    assert ProductLifecycleDecision.objects.count() == 0
    assert RPATask.objects.count() == 0


@pytest.mark.django_db
def test_lifecycle_standard_confirm_and_reject_are_audited_without_product_mutation():
    tenant = Tenant.objects.create(name="Tenant", code="lifecycle-decisions")
    first_sku = create_sku(tenant, "CONFIRM")
    second_sku = create_sku(tenant, "REJECT")
    actor = create_user(tenant, "lifecycle-actor")
    grant(actor, "products.lifecycle.confirm")
    confirm_review = create_review(tenant, first_sku)
    reject_review = create_review(tenant, second_sku)
    original_lifecycle = first_sku.spu.lifecycle_status
    original_sales = first_sku.spu.sales_status

    confirmed = decide_lifecycle_review(
        review=confirm_review, actor=actor,
        decision=ProductLifecycleDecision.Decision.CONFIRM, reason="Confirm demo growth.",
    )
    rejected = decide_lifecycle_review(
        review=reject_review, actor=actor,
        decision=ProductLifecycleDecision.Decision.REJECT, reason="Reject demo growth.",
    )

    first_sku.spu.refresh_from_db()
    assert confirmed.to_stage == ProductLifecycleStage.GROWTH
    assert rejected.to_stage == ProductLifecycleStage.NEW_OBSERVATION
    assert first_sku.spu.lifecycle_status == original_lifecycle
    assert first_sku.spu.sales_status == original_sales
    assert OperationLog.objects.filter(tenant=tenant, module="lifecycle").count() == 2


@pytest.mark.django_db
@pytest.mark.parametrize("target", [ProductLifecycleStage.CLEARANCE, ProductLifecycleStage.STOPPED, ProductLifecycleStage.ARCHIVED])
def test_lifecycle_high_risk_stages_require_separate_permission(target):
    tenant = Tenant.objects.create(name="Tenant", code=f"lifecycle-risk-{target}")
    sku = create_sku(tenant, target)
    actor = create_user(tenant, f"actor-{target}")
    grant(actor, "products.lifecycle.confirm")
    previous = {
        ProductLifecycleStage.CLEARANCE: ProductLifecycleStage.CLEARANCE_CANDIDATE,
        ProductLifecycleStage.STOPPED: ProductLifecycleStage.CLEARANCE,
        ProductLifecycleStage.ARCHIVED: ProductLifecycleStage.STOPPED,
    }[target]
    review = create_review(tenant, sku, current=previous, recommended=target)

    with pytest.raises(PermissionDenied, match="High-risk"):
        decide_lifecycle_review(
            review=review, actor=actor,
            decision=ProductLifecycleDecision.Decision.CONFIRM, reason="Attempt without high-risk permission.",
        )
    grant(actor, "products.lifecycle.high_risk_confirm")
    decision = decide_lifecycle_review(
        review=review, actor=actor,
        decision=ProductLifecycleDecision.Decision.CONFIRM, reason="Authorized high-risk decision.",
    )
    assert decision.to_stage == target


@pytest.mark.django_db
def test_lifecycle_illegal_transition_and_duplicate_confirmation_are_rejected():
    tenant = Tenant.objects.create(name="Tenant", code="lifecycle-invalid")
    sku = create_sku(tenant, "INVALID")
    with pytest.raises(ValidationError, match="Illegal"):
        create_review(
            tenant, sku,
            current=ProductLifecycleStage.NEW_OBSERVATION,
            recommended=ProductLifecycleStage.ARCHIVED,
        )
    actor = create_user(tenant, "lifecycle-confirmer")
    grant(actor, "products.lifecycle.confirm")
    review = create_review(tenant, sku)
    decide_lifecycle_review(
        review=review, actor=actor,
        decision=ProductLifecycleDecision.Decision.CONFIRM, reason="First decision.",
    )
    with pytest.raises(ValidationError, match="already been handled"):
        decide_lifecycle_review(
            review=review, actor=actor,
            decision=ProductLifecycleDecision.Decision.CONFIRM, reason="Duplicate decision.",
        )


@pytest.mark.django_db
def test_lifecycle_decision_cannot_bypass_permission_or_model_guard():
    tenant = Tenant.objects.create(name="Tenant", code="lifecycle-guard")
    sku = create_sku(tenant, "GUARD")
    review = create_review(tenant, sku)
    unauthorized = create_user(tenant, "unauthorized")
    with pytest.raises(PermissionDenied):
        decide_lifecycle_review(
            review=review, actor=unauthorized,
            decision=ProductLifecycleDecision.Decision.CONFIRM, reason="Bypass.",
        )
    with pytest.raises(ValidationError, match="audited decision service"):
        ProductLifecycleReview.objects.filter(pk=review.pk).update(status=ProductLifecycleReview.Status.CONFIRMED)
    review.status = ProductLifecycleReview.Status.CONFIRMED
    with pytest.raises(ValidationError, match="audited decision service"):
        review.save()
    review.refresh_from_db()
    review.reason_detail = "Tampered evidence"
    with pytest.raises(ValidationError, match="evidence is immutable"):
        review.save()
    forged = ProductLifecycleDecision(
        tenant=tenant,
        review=review,
        decision=ProductLifecycleDecision.Decision.CONFIRM,
        from_stage=review.current_stage,
        to_stage=review.recommended_stage,
        actor=unauthorized,
        reason="Forged decision",
    )
    with pytest.raises(ValidationError, match="audited decision service"):
        forged.save()


@pytest.mark.django_db
def test_lifecycle_api_tenant_scope_and_permissions():
    tenant = Tenant.objects.create(name="Tenant", code="lifecycle-api")
    other = Tenant.objects.create(name="Other", code="lifecycle-api-other")
    sku = create_sku(tenant, "VISIBLE")
    hidden_sku = create_sku(tenant, "HIDDEN")
    other_sku = create_sku(other, "OTHER")
    visible = create_review(tenant, sku)
    create_review(tenant, hidden_sku)
    create_review(other, other_sku)
    viewer = create_user(tenant, "viewer")
    evaluator = create_user(tenant, "evaluator")
    confirmer = create_user(tenant, "confirmer")
    grant(viewer, "products.lifecycle.view", DataScope.ScopeType.CUSTOM, {"sku_ids": [sku.id]})
    grant(evaluator, "products.lifecycle.evaluate", DataScope.ScopeType.CUSTOM, {"sku_ids": [sku.id]})
    grant(confirmer, "products.lifecycle.confirm")

    response = client_for(viewer).get("/api/internal/lifecycle/reviews/")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]["items"]] == [visible.id]
    payload = {
        "sku_id": sku.id,
        "current_stage": ProductLifecycleStage.NEW_OBSERVATION,
        "recommended_stage": ProductLifecycleStage.STABLE,
        "review_period_start": str(date.today() - timedelta(days=7)),
        "review_period_end": str(date.today()),
        "reason_code": "mock_stable",
        "reason_detail": "Mock only",
        "confidence": "0.8000",
        "source_metrics": {"sales": "demo"},
    }
    assert client_for(viewer).post("/api/internal/lifecycle/evaluate-mock/", payload, format="json").status_code == 403
    assert client_for(evaluator).post("/api/internal/lifecycle/evaluate-mock/", payload, format="json").status_code == 201
    before_count = ProductLifecycleReview.objects.count()
    assert client_for(evaluator).post(
        "/api/internal/lifecycle/evaluate-mock/",
        {**payload, "sku_id": hidden_sku.id},
        format="json",
    ).status_code == 403
    assert ProductLifecycleReview.objects.count() == before_count
    assert client_for(confirmer).post(
        f"/api/internal/lifecycle/reviews/{visible.id}/confirm/", {"reason": "Reviewed"}, format="json"
    ).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("user_type", [CustomUser.UserType.EXTERNAL, CustomUser.UserType.RPA])
def test_lifecycle_api_rejects_external_and_rpa(user_type):
    tenant = Tenant.objects.create(name="Tenant", code=f"lifecycle-deny-{user_type}")
    user = create_user(tenant, f"deny-{user_type}", user_type)
    grant(user, "products.lifecycle.view")
    assert client_for(user).get("/api/internal/lifecycle/reviews/").status_code == 403
