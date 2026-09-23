from datetime import timedelta
from decimal import Decimal
from urllib.parse import quote

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.masterdata.models import PlatformMaster, StoreMaster, WarehouseMaster
from apps.masterdata.serializers import WarehouseMasterSerializer
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.cost_services import append_cost_version, effective_cost_for
from apps.products.models import ProductCostVersion, ProductSKU, ProductSPU
from apps.tenants.models import Tenant


def make_sku(tenant, suffix, purchase_price="10.0000"):
    spu = ProductSPU.objects.create(tenant=tenant, spu_code=f"SPU-{suffix}", product_name=f"Product {suffix}")
    return ProductSKU.objects.create(
        tenant=tenant, spu=spu, sku_code=f"SKU-{suffix}", product_name=f"Product {suffix}", purchase_price=purchase_price
    )


def make_warehouse(tenant, suffix="CN"):
    return WarehouseMaster.objects.create(tenant=tenant, code=f"WH-{suffix}", name=f"Warehouse {suffix}",
                                         country_code=suffix, warehouse_type="owned")


def make_store(tenant, suffix):
    platform = PlatformMaster.objects.create(
        tenant=tenant, code=f"platform-{suffix.lower()}", name=f"Platform {suffix}", platform_type="other"
    )
    return StoreMaster.objects.create(
        tenant=tenant, platform=platform, code=f"store-{suffix.lower()}", name=f"Store {suffix}",
        country_code=suffix, currency="CNY",
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
    warehouse = make_warehouse(tenant)
    start = timezone.now()
    payload = {
        "sku": sku.id, "warehouse": warehouse.id, "status": "confirmed", "source": "manual", "currency": "CNY",
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
    warehouse = make_warehouse(tenant)
    url = "/api/internal/products/costs/backfill-preview/"
    assert client_for(viewer).post(url, {"sku_ids": [sku.id]}, format="json").status_code == 403
    response = client_for(operator).post(url, {"sku_ids": [sku.id], "warehouse_id": warehouse.id}, format="json")
    assert response.status_code == 200
    assert response.json()["data"]["results"][0]["system_cost"] == 12.34
    assert ProductCostVersion.objects.count() == 0


@pytest.mark.django_db
def test_backfill_execute_creates_pending_version_then_approver_confirms_it():
    tenant = Tenant.objects.create(name="Backfill flow", code="cost-backfill-flow")
    operator = make_user(tenant, "operator-flow")
    approver = make_user(tenant, "approver-flow")
    grant(operator, "products.cost.backfill")
    grant(approver, "products.cost.approve")
    sku = make_sku(tenant, "FLOW", "18.2500")
    warehouse = make_warehouse(tenant)
    effective_from = timezone.now() + timedelta(days=1)

    execute_url = "/api/internal/products/costs/backfill-execute/"
    payload = {"sku_ids": [sku.id], "warehouse_id": warehouse.id,
               "effective_from": effective_from.isoformat(), "reason": "monthly backfill"}
    first = client_for(operator).post(execute_url, payload, format="json")
    replay = client_for(operator).post(execute_url, payload, format="json")
    assert first.status_code == 201
    assert replay.status_code == 201
    assert first.json()["data"]["created"] == 1
    assert replay.json()["data"]["unchanged"] == 1
    pending = ProductCostVersion.objects.get(sku=sku)
    assert pending.status == ProductCostVersion.Status.PENDING
    assert pending.confirmed_cost is None

    confirm = client_for(approver).post(
        f"/api/internal/products/costs/versions/{pending.id}/confirm/",
        {"confirmed_cost": "18.5000", "reason": "finance approved"},
        format="json",
    )
    assert confirm.status_code == 200
    pending.refresh_from_db()
    assert pending.status == ProductCostVersion.Status.CONFIRMED
    assert pending.confirmed_cost == Decimal("18.5000")


def test_postgres_migration_declares_confirmed_interval_exclusion_constraint():
    from pathlib import Path

    migration = Path(__file__).parents[1] / "apps" / "products" / "migrations" / "0024_product_cost_confirmed_interval_exclusion.py"
    source = migration.read_text(encoding="utf-8")
    assert "EXCLUDE USING gist" in source
    assert "tstzrange" in source
    assert "status = 'confirmed'" in source


@pytest.mark.django_db
def test_cost_intervals_and_lookup_are_scoped_to_warehouse():
    tenant = Tenant.objects.create(name="Regional cost", code="cost-warehouse-scope")
    user = make_user(tenant, "warehouse-scope")
    sku = make_sku(tenant, "WAREHOUSE")
    china = make_warehouse(tenant, "CN")
    usa = make_warehouse(tenant, "US")
    start = timezone.now()
    china_cost = append_cost_version(
        tenant=tenant, sku=sku, warehouse=china, actor=user,
        **values(start, start + timedelta(days=10)),
    )
    usa_values = values(start, start + timedelta(days=10))
    usa_values["confirmed_cost"] = Decimal("25")
    usa_cost = append_cost_version(tenant=tenant, sku=sku, warehouse=usa, actor=user, **usa_values)
    assert usa_cost.version_no != china_cost.version_no
    assert effective_cost_for(tenant=tenant, sku=sku, warehouse=china, occurred_at=start) == china_cost
    assert effective_cost_for(tenant=tenant, sku=sku, warehouse=usa, occurred_at=start) == usa_cost
    assert effective_cost_for(tenant=tenant, sku=sku, occurred_at=start) is None
    with pytest.raises(ValidationError, match="overlaps"):
        append_cost_version(
            tenant=tenant, sku=sku, warehouse=china, actor=user,
            **values(start + timedelta(days=1), start + timedelta(days=2)),
        )


@pytest.mark.django_db
def test_cost_api_requires_warehouse_and_lists_options_under_cost_permission():
    tenant = Tenant.objects.create(name="Cost warehouse API", code="cost-wh-api")
    user = make_user(tenant, "warehouse-view")
    grant(user, "products.cost.view", "products.cost.manage")
    warehouse = make_warehouse(tenant)
    sku = make_sku(tenant, "WAREHOUSE-API")
    options = client_for(user).get("/api/internal/products/costs/warehouses/")
    assert options.status_code == 200
    assert options.json()["data"] == [{"id": warehouse.pk, "code": warehouse.code,
                                        "name": warehouse.name, "country_code": warehouse.country_code}]
    payload = {"sku": sku.pk, "effective_from": timezone.now().isoformat(), "purchase_cost": "10"}
    response = client_for(user).post("/api/internal/products/costs/versions/", payload, format="json")
    assert response.status_code == 400
    assert ProductCostVersion.objects.filter(sku=sku).count() == 0


@pytest.mark.django_db
def test_effective_cost_api_requires_store_country_match():
    tenant = Tenant.objects.create(name="Cost country match", code="cost-country-match")
    user = make_user(tenant, "country-match")
    grant(user, "products.cost.view")
    warehouse = make_warehouse(tenant, "US")
    us_store = make_store(tenant, "US")
    cn_store = make_store(tenant, "CN")
    sku = make_sku(tenant, "COUNTRY-MATCH")
    moment = timezone.now()
    append_cost_version(tenant=tenant, sku=sku, warehouse=warehouse, actor=user,
                        **values(moment - timedelta(days=1), None))
    path = f"/api/internal/products/costs/?sku_id={sku.pk}&warehouse_id={warehouse.pk}&occurred_at={quote(moment.isoformat(), safe='')}"
    assert client_for(user).get(path).status_code == 400
    assert client_for(user).get(f"{path}&store_id={cn_store.pk}").status_code == 400
    response = client_for(user).get(f"{path}&store_id={us_store.pk}")
    assert response.status_code == 200
    assert response.json()["data"]["warehouse"] == warehouse.pk


@pytest.mark.django_db
def test_warehouse_country_cannot_change_after_cost_history_exists():
    tenant = Tenant.objects.create(name="Cost country history", code="cost-country-history")
    user = make_user(tenant, "country-history")
    warehouse = make_warehouse(tenant, "US")
    sku = make_sku(tenant, "COUNTRY-HISTORY")
    append_cost_version(tenant=tenant, sku=sku, warehouse=warehouse, actor=user,
                        **values(timezone.now(), None))
    serializer = WarehouseMasterSerializer(
        warehouse, data={"country_code": "CN"}, partial=True,
        context={"request": type("Request", (), {"user": user})()},
    )
    assert not serializer.is_valid()
    assert "country_code" in serializer.errors
