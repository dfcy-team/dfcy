from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.audit.models import OperationLog
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.models import ProductSKU, ProductSPU
from apps.purchasing.models import PurchaseOrder
from apps.replenishment.models import ReplenishmentRecommendation
from apps.replenishment.services import evaluate_replenishment, review_recommendation
from apps.rpa.models import RPATask
from apps.suppliers.models import SupplierTask
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


def evaluate(tenant, sku, **overrides):
    values = {
        "tenant": tenant,
        "sku": sku,
        "available_stock": 10,
        "in_transit_stock": 5,
        "average_daily_sales": 2,
        "safety_stock_days": 7,
        "supplier_lead_days": 10,
        "replenishment_cycle_days": 14,
    }
    values.update(overrides)
    return evaluate_replenishment(**values)


@pytest.mark.django_db
def test_replenishment_quantity_date_and_idempotency():
    tenant = Tenant.objects.create(name="Tenant", code="replenishment-calc")
    sku = create_sku(tenant, "CALC")

    first = evaluate(tenant, sku)
    second = evaluate(tenant, sku)

    assert first.id == second.id
    assert first.suggested_quantity == 47
    assert first.reason_code == "coverage_gap"
    assert first.confidence == Decimal("1.0000")
    assert ReplenishmentRecommendation.objects.count() == 1


@pytest.mark.django_db
def test_replenishment_empty_sales_data_is_explicit_and_safe():
    tenant = Tenant.objects.create(name="Tenant", code="replenishment-empty")
    sku = create_sku(tenant, "EMPTY")

    recommendation = evaluate(tenant, sku, average_daily_sales=None)

    assert recommendation.suggested_quantity == 0
    assert recommendation.confidence == Decimal("0.0000")
    assert recommendation.reason_code == "insufficient_sales_data"


@pytest.mark.django_db
@pytest.mark.parametrize("field", ["available_stock", "in_transit_stock", "average_daily_sales", "safety_stock_days"])
def test_replenishment_rejects_negative_inputs(field):
    tenant = Tenant.objects.create(name="Tenant", code=f"replenishment-negative-{field}")
    sku = create_sku(tenant, field)
    with pytest.raises(ValidationError):
        evaluate(tenant, sku, **{field: -1})
    assert ReplenishmentRecommendation.objects.count() == 0


@pytest.mark.django_db
def test_replenishment_rejects_cross_tenant_product():
    tenant = Tenant.objects.create(name="Tenant", code="replenishment-owner")
    other = Tenant.objects.create(name="Other", code="replenishment-owner-other")
    sku = create_sku(other, "OTHER")
    with pytest.raises(ValidationError):
        evaluate(tenant, sku)


@pytest.mark.django_db
def test_accept_and_reject_only_change_recommendation_and_write_audit():
    tenant = Tenant.objects.create(name="Tenant", code="replenishment-review")
    sku = create_sku(tenant, "REVIEW")
    reviewer = create_user(tenant, "reviewer")
    grant(reviewer, "replenishment.review")
    accepted = evaluate(tenant, sku)
    rejected = evaluate(tenant, sku, available_stock=11)

    accepted = review_recommendation(
        recommendation=accepted, actor=reviewer,
        decision=ReplenishmentRecommendation.Status.ACCEPTED, reason="Demo acceptance only.",
    )
    rejected = review_recommendation(
        recommendation=rejected, actor=reviewer,
        decision=ReplenishmentRecommendation.Status.REJECTED, reason="Demo rejection.",
    )

    assert accepted.status == ReplenishmentRecommendation.Status.ACCEPTED
    assert rejected.status == ReplenishmentRecommendation.Status.REJECTED
    with pytest.raises(ValidationError):
        review_recommendation(
            recommendation=accepted, actor=reviewer,
            decision=ReplenishmentRecommendation.Status.REJECTED, reason="Repeat.",
        )
    assert PurchaseOrder.objects.count() == 0
    assert SupplierTask.objects.count() == 0
    assert RPATask.objects.count() == 0
    assert OperationLog.objects.filter(tenant=tenant, module="replenishment").count() == 2


@pytest.mark.django_db
def test_replenishment_review_cannot_bypass_permission_or_audited_service():
    tenant = Tenant.objects.create(name="Tenant", code="replenishment-review-guard")
    sku = create_sku(tenant, "GUARD")
    recommendation = evaluate(tenant, sku)
    unauthorized = create_user(tenant, "unauthorized-reviewer")

    with pytest.raises(ValidationError, match="authorized internal reviewer"):
        review_recommendation(
            recommendation=recommendation,
            actor=unauthorized,
            decision=ReplenishmentRecommendation.Status.ACCEPTED,
            reason="Bypass attempt.",
        )
    with pytest.raises(ValidationError, match="audited review service"):
        ReplenishmentRecommendation.objects.filter(pk=recommendation.pk).update(
            status=ReplenishmentRecommendation.Status.ACCEPTED
        )
    recommendation.status = ReplenishmentRecommendation.Status.ACCEPTED
    with pytest.raises(ValidationError, match="audited review service"):
        recommendation.save()


@pytest.mark.django_db
def test_replenishment_api_tenant_scope_and_action_permissions():
    tenant = Tenant.objects.create(name="Tenant", code="replenishment-api")
    other = Tenant.objects.create(name="Other", code="replenishment-api-other")
    sku = create_sku(tenant, "VISIBLE")
    hidden_sku = create_sku(tenant, "HIDDEN")
    other_sku = create_sku(other, "OTHER")
    visible = evaluate(tenant, sku)
    evaluate(tenant, hidden_sku)
    evaluate(other, other_sku)
    viewer = create_user(tenant, "viewer")
    evaluator = create_user(tenant, "evaluator")
    reviewer = create_user(tenant, "reviewer-api")
    grant(viewer, "replenishment.view", DataScope.ScopeType.CUSTOM, {"sku_ids": [sku.id]})
    grant(evaluator, "replenishment.evaluate")
    grant(reviewer, "replenishment.review")

    response = client_for(viewer).get("/api/internal/replenishment/recommendations/")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]["items"]] == [visible.id]
    payload = {
        "sku_id": sku.id, "available_stock": "10.0000", "in_transit_stock": "5.0000",
        "average_daily_sales": "2.0000", "safety_stock_days": 7,
        "supplier_lead_days": 10, "replenishment_cycle_days": 14,
    }
    assert client_for(viewer).post("/api/internal/replenishment/evaluate-mock/", payload, format="json").status_code == 403
    assert client_for(evaluator).post("/api/internal/replenishment/evaluate-mock/", payload, format="json").status_code == 201
    assert client_for(reviewer).post(
        f"/api/internal/replenishment/recommendations/{visible.id}/accept/",
        {"reason": "Reviewed only"}, format="json",
    ).status_code == 200
    assert PurchaseOrder.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize("user_type", [CustomUser.UserType.EXTERNAL, CustomUser.UserType.RPA])
def test_replenishment_api_rejects_external_and_rpa(user_type):
    tenant = Tenant.objects.create(name="Tenant", code=f"replenishment-deny-{user_type}")
    user = create_user(tenant, f"deny-{user_type}", user_type)
    grant(user, "replenishment.view")
    assert client_for(user).get("/api/internal/replenishment/recommendations/").status_code == 403


@pytest.mark.django_db
def test_replenishment_api_rejects_unauthenticated():
    assert APIClient().get("/api/internal/replenishment/recommendations/").status_code == 401
