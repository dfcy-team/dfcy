import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.products.models import (
    ProductSPU,
    ProductStatus,
    ProductStatusRecommendation,
    ProductStatusSnapshot,
    ProductStatusTransition,
)
from apps.products.status_services import create_status_recommendation
from apps.tenants.models import Tenant


def create_user(tenant, username, user_type=CustomUser.UserType.INTERNAL, is_staff=False):
    return CustomUser.objects.create_user(
        username=username,
        tenant=tenant,
        user_type=user_type,
        is_staff=is_staff,
    )


def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def create_spu(tenant, code="SPU-STATUS"):
    return ProductSPU.objects.create(tenant=tenant, spu_code=code, product_name="Demo Product")


def create_recommendation(tenant, spu, status=ProductStatus.ACTIVE, source=ProductStatusSnapshot.Source.API):
    return create_status_recommendation(
        tenant=tenant,
        source=source,
        recommended_status=status,
        metrics_payload={"sales_30d": 12, "stock_days": 20},
        reason_code="demo_metrics",
        reason_detail="demo only",
        spu=spu,
        source_reference=f"demo:{source}",
    )


@pytest.mark.django_db
def test_status_recommendation_api_filters_by_tenant():
    tenant_a = Tenant.objects.create(name="Tenant A", code="tenant-a")
    tenant_b = Tenant.objects.create(name="Tenant B", code="tenant-b")
    user_a = create_user(tenant_a, "internal-a")
    spu_a = create_spu(tenant_a, "SPU-A")
    spu_b = create_spu(tenant_b, "SPU-B")
    create_recommendation(tenant_a, spu_a, ProductStatus.ACTIVE)
    hidden = create_recommendation(tenant_b, spu_b, ProductStatus.ACTIVE)

    client = authenticated_client(user_a)
    list_response = client.get("/api/internal/products/status-recommendations/")
    hidden_response = client.get(f"/api/internal/products/status-recommendations/{hidden.id}/")

    assert list_response.status_code == 200
    assert len(list_response.json()["data"]) == 1
    assert list_response.json()["data"][0]["tenant_id"] == tenant_a.id
    assert hidden_response.status_code == 404


@pytest.mark.django_db
def test_api_and_rpa_sources_only_create_pending_recommendations():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    spu = create_spu(tenant)

    api_recommendation = create_recommendation(
        tenant,
        spu,
        ProductStatus.SLOW_MOVING,
        source=ProductStatusSnapshot.Source.API,
    )
    rpa_recommendation = create_recommendation(
        tenant,
        spu,
        ProductStatus.SLOW_MOVING,
        source=ProductStatusSnapshot.Source.RPA_READBACK,
    )

    assert api_recommendation.status == ProductStatusRecommendation.Status.PENDING
    assert rpa_recommendation.status == ProductStatusRecommendation.Status.PENDING
    assert ProductStatusTransition.objects.count() == 0


@pytest.mark.django_db
def test_evaluate_mock_uses_demo_metrics_and_creates_recommendation():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "internal")
    spu = create_spu(tenant)

    response = authenticated_client(user).post(
        "/api/internal/products/status/evaluate-mock/",
        {"spu": spu.id, "metrics": {"sales_30d": 2, "stock_days": 120}},
        format="json",
    )

    assert response.status_code == 201
    assert response.json()["success"] is True
    assert response.json()["data"]["recommended_status"] == ProductStatus.SLOW_MOVING
    assert response.json()["data"]["source_snapshot"]["metrics_payload"] == {"sales_30d": 2, "stock_days": 120}


@pytest.mark.django_db
def test_plain_internal_cannot_confirm_high_risk_status_but_staff_can():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    plain_user = create_user(tenant, "plain")
    staff_user = create_user(tenant, "staff", is_staff=True)
    spu = create_spu(tenant)
    active = create_recommendation(tenant, spu, ProductStatus.ACTIVE, source=ProductStatusSnapshot.Source.MANUAL)
    authenticated_client(staff_user).post(
        f"/api/internal/products/status-recommendations/{active.id}/confirm/",
        {"reason": "activate demo product"},
        format="json",
    )
    risky = create_recommendation(
        tenant,
        spu,
        ProductStatus.STOPPED,
        source=ProductStatusSnapshot.Source.MANUAL,
    )

    plain_response = authenticated_client(plain_user).post(
        f"/api/internal/products/status-recommendations/{risky.id}/confirm/",
        {"reason": "not authorized"},
        format="json",
    )
    staff_response = authenticated_client(staff_user).post(
        f"/api/internal/products/status-recommendations/{risky.id}/confirm/",
        {"reason": "authorized high-risk confirmation"},
        format="json",
    )

    assert plain_response.status_code == 403
    assert staff_response.status_code == 200
    assert staff_response.json()["data"]["to_status"] == ProductStatus.STOPPED
    assert ProductStatusTransition.objects.filter(to_status=ProductStatus.STOPPED).exists()


@pytest.mark.django_db
def test_illegal_transition_is_rejected_and_duplicate_confirm_is_rejected():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    staff_user = create_user(tenant, "staff", is_staff=True)
    spu = create_spu(tenant)
    illegal = create_recommendation(
        tenant,
        spu,
        ProductStatus.CLEARANCE,
        source=ProductStatusSnapshot.Source.MANUAL,
    )
    client = authenticated_client(staff_user)

    illegal_response = client.post(
        f"/api/internal/products/status-recommendations/{illegal.id}/confirm/",
        {"reason": "new to clearance is illegal"},
        format="json",
    )

    active = create_recommendation(tenant, spu, ProductStatus.ACTIVE, source=ProductStatusSnapshot.Source.MANUAL)
    first_confirm = client.post(
        f"/api/internal/products/status-recommendations/{active.id}/confirm/",
        {"reason": "first confirm"},
        format="json",
    )
    duplicate_confirm = client.post(
        f"/api/internal/products/status-recommendations/{active.id}/confirm/",
        {"reason": "duplicate confirm"},
        format="json",
    )

    assert illegal_response.status_code == 400
    assert first_confirm.status_code == 200
    assert duplicate_confirm.status_code == 400


@pytest.mark.django_db
def test_reject_creates_audit_transition_without_status_change():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "internal")
    spu = create_spu(tenant)
    recommendation = create_recommendation(tenant, spu, ProductStatus.ACTIVE)

    response = authenticated_client(user).post(
        f"/api/internal/products/status-recommendations/{recommendation.id}/reject/",
        {"reason": "demo reject"},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == ProductStatusRecommendation.Status.REJECTED
    transition = ProductStatusTransition.objects.get(recommendation=recommendation)
    assert transition.trigger_type == ProductStatusTransition.TriggerType.MANUAL_REJECT
    assert transition.from_status == transition.to_status == ProductStatus.NEW


@pytest.mark.django_db
def test_external_and_rpa_cannot_access_internal_status_confirmation():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    spu = create_spu(tenant)
    recommendation = create_recommendation(tenant, spu, ProductStatus.ACTIVE)
    external = create_user(tenant, "external", CustomUser.UserType.EXTERNAL)
    rpa = create_user(tenant, "rpa", CustomUser.UserType.RPA)

    for user in [external, rpa]:
        response = authenticated_client(user).post(
            f"/api/internal/products/status-recommendations/{recommendation.id}/confirm/",
            {"reason": "not internal"},
            format="json",
        )
        assert response.status_code == 403
