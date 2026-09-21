from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.cost_services import append_cost_version, effective_cost_for
from apps.products.models import ProductCostVersion, ProductSKU, ProductSPU
from apps.tenants.models import Tenant


def make_sku(tenant, suffix, purchase_price="10.0000"):
    spu = ProductSPU.objects.create(tenant=tenant, spu_code=f"SPU-{suffix}", product_name=f"Product {suffix}")
    return ProductSKU.objects.create(
        tenant=tenant, spu=spu, sku_code=f"SKU-{suffix}", product_name=f"Product {suffix}", purchase_price=purchase_price
    )


def make_user(tenant, suffix):
    return CustomUser.objects.create_user(
        username=f"cost-{suffix}", tenant=tenant, user_type=CustomUser.UserType.INTERNAL
    )


def grant(user, *codes):
    role = Role.objects.create(tenant=user.tenant, name=f"Cost {user.id}", code=f"cost-{user.id}")
    role.permissions.add(*Permission.objects.filter(code__in=codes))
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def values(start, end, status=ProductCostVersion.Status.CONFIRMED):
    return {
        "status": status,
        "source": ProductCostVersion.Source.MANUAL,
        "currency": "CNY",
        "purchase_cost": Decimal("10"),
        "freight_cost": Decimal("2"),
        "duty_cost": Decimal("1"),
        "packaging_cost": Decimal("0.5"),
        "other_cost": Decimal("0.5"),
        "system_cost": Decimal("14"),
        "confirmed_cost": Decimal("14") if status == ProductCostVersion.Status.CONFIRMED else None,
        "effective_from": start,
        "effective_to": end,
        "reason": "periodic review",
    }


@pytest.mark.django_db
def test_append_only_versions_and_non_overlap():
    tenant = Tenant.objects.create(name="Cost tenant", code="cost-append")
    user = make_user(tenant, "append")
    sku = make_sku(tenant, "APPEND")
    start = timezone.now()
    first = append_cost_version(tenant=tenant, sku=sku, actor=user, **values(start, start + timedelta(days=10)))
    second = append_cost_version(
        tenant=tenant, sku=sku, actor=user, **values(start + timedelta(days=10), start + timedelta(days=20))
    )
    assert (first.version_no, second.version_no) == (1, 2)
    with pytest.raises(ValidationError, match="overlaps"):
        append_cost_version(
            tenant=tenant, sku=sku, actor=user, **values(start + timedelta(days=5), start + timedelta(days=12))
        )
    first.reason = "rewrite"
    with pytest.raises(ValidationError, match="append-only"):
        first.save()
    with pytest.raises(ValidationError, match="append-only"):
        first.delete()


@pytest.mark.django_db
def test_as_of_lookup_uses_half_open_intervals():
    tenant = Tenant.objects.create(name="As of tenant", code="cost-asof")
    user = make_user(tenant, "asof")
    sku = make_sku(tenant, "ASOF")
    start = timezone.now()
    boundary = start + timedelta(days=10)
    first = append_cost_version(tenant=tenant, sku=sku, actor=user, **values(start, boundary))
    second_values = values(boundary, boundary + timedelta(days=10))
    second_values["confirmed_cost"] = Decimal("20")
    second = append_cost_version(tenant=tenant, sku=sku, actor=user, **second_values)
    assert effective_cost_for(tenant=tenant, sku=sku, occurred_at=boundary - timedelta(seconds=1)) == first
    assert effective_cost_for(tenant=tenant, sku=sku, occurred_at=boundary) == second


@pytest.mark.django_db
def test_appending_a_new_current_version_closes_the_previous_open_interval():
    tenant = Tenant.objects.create(name="Rolling tenant", code="cost-rolling")
    user = make_user(tenant, "rolling")
    sku = make_sku(tenant, "ROLLING")
    start = timezone.now()
    first = append_cost_version(tenant=tenant, sku=sku, actor=user, **values(start, None))
    boundary = start + timedelta(days=10)
    second_values = values(boundary, None)
    second_values["confirmed_cost"] = Decimal("20")
    second = append_cost_version(tenant=tenant, sku=sku, actor=user, **second_values)
    first.refresh_from_db()
    assert first.effective_to == boundary
    assert effective_cost_for(tenant=tenant, sku=sku, occurred_at=boundary - timedelta(seconds=1)) == first
    assert effective_cost_for(tenant=tenant, sku=sku, occurred_at=boundary) == second


@pytest.mark.django_db
def test_cost_api_is_tenant_isolated_and_requires_view_permission():
    tenant_a = Tenant.objects.create(name="A", code="cost-a")
    tenant_b = Tenant.objects.create(name="B", code="cost-b")
    user_a = make_user(tenant_a, "view")
    user_without = make_user(tenant_a, "none")
    grant(user_a, "products.cost.view")
    start = timezone.now()
    own = append_cost_version(tenant=tenant_a, sku=make_sku(tenant_a, "A"), actor=user_a, **values(start, start + timedelta(days=1)))
    other_user = make_user(tenant_b, "other")
    append_cost_version(tenant=tenant_b, sku=make_sku(tenant_b, "B"), actor=other_user, **values(start, start + timedelta(days=1)))
    response = client_for(user_a).get("/api/internal/products/costs/")
    assert response.status_code == 200
    assert [row["id"] for row in response.json()["data"]] == [own.id]
    assert client_for(user_without).get("/api/internal/products/costs/").status_code == 403


@pytest.mark.django_db
def test_create_confirmed_version_requires_manage_and_approve():
    tenant = Tenant.objects.create(name="API tenant", code="cost-api")
    manager = make_user(tenant, "manager")
    approver = make_user(tenant, "approver")
    grant(manager, "products.cost.manage")
    grant(approver, "products.cost.manage", "products.cost.approve")
    sku = make_sku(tenant, "API")
    start = timezone.now()
    payload = {
        "sku": sku.id, "status": "confirmed", "source": "manual", "currency": "CNY",
        "purchase_cost": "10", "freight_cost": "2", "duty_cost": "1", "packaging_cost": "0.5",
        "other_cost": "0.5", "system_cost": "14", "confirmed_cost": "14",
        "effective_from": start.isoformat(), "effective_to": (start + timedelta(days=1)).isoformat(),
        "reason": "approved",
    }
    assert client_for(manager).post("/api/internal/products/costs/versions/", payload, format="json").status_code == 403
    response = client_for(approver).post("/api/internal/products/costs/versions/", payload, format="json")
    assert response.status_code == 201
    assert response.json()["data"]["version_no"] == 1


@pytest.mark.django_db
def test_backfill_is_dry_run_and_has_independent_permission():
    tenant = Tenant.objects.create(name="Backfill tenant", code="cost-backfill")
    operator = make_user(tenant, "backfill")
    viewer = make_user(tenant, "viewer-only")
    grant(operator, "products.cost.backfill")
    grant(viewer, "products.cost.view")
    sku = make_sku(tenant, "BACKFILL", "12.3400")
    url = "/api/internal/products/costs/backfill-preview/"
    assert client_for(viewer).post(url, {"sku_ids": [sku.id]}, format="json").status_code == 403
    response = client_for(operator).post(url, {"sku_ids": [sku.id]}, format="json")
    assert response.status_code == 200
    assert response.json()["data"]["results"][0]["system_cost"] == 12.34
    assert ProductCostVersion.objects.count() == 0
