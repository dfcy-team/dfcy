"""SQLite contract smoke tests for the merged supply-flow HTTP adapters."""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import CustomUser, ExternalUserProfile
from apps.masterdata.models import SupplierMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


ALL_PERMISSIONS = (
    "supply.consolidation_site.view", "supply.consolidation_site.manage",
    "supply.consolidation.view", "supply.consolidation.create",
    "supply.consolidation.manage", "supply.consolidation.allocate",
    "supply.consolidation.release", "supply.consolidation.receive",
    "supply.consolidation.exception.manage", "supply.consolidation.cancel",
    "supply.shipment.view", "supply.shipment.create", "supply.shipment.update",
    "supply.shipment.allocate", "supply.shipment.customs.confirm",
    "supply.shipment.dispatch", "supply.shipment.port_arrival.confirm",
    "supply.shipment.warehouse_arrival.confirm", "supply.shipment.clearance.complete",
    "supply.shipment.exception.manage", "supply.shipment.cancel",
)


def internal_user(tenant, name, permissions=ALL_PERMISSIONS, *, scope_type=DataScope.ScopeType.ALL, config=None):
    user = CustomUser.objects.create_user(username=name, tenant=tenant, user_type=CustomUser.UserType.INTERNAL)
    role = Role.objects.create(tenant=tenant, code=f"{name}-role", name=name)
    for code in permissions:
        permission, _ = Permission.objects.get_or_create(
            code=code, defaults={"name": code, "module": "supply", "action": code.rsplit(".", 1)[-1], "description": "API2 test"},
        )
        role.permissions.add(permission)
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=scope_type, config=config or {})
    return user


def test_internal_consolidation_site_create_replay_and_strict_fields():
    tenant = Tenant.objects.create(name="API2 tenant", code="api2-site")
    user = internal_user(tenant, "api2-site-user", permissions=("supply.consolidation_site.view", "supply.consolidation_site.manage"))
    client = APIClient(); client.force_authenticate(user=user)
    body = {"site_code": "API2-SITE", "name": "API2 Site", "region_code": "CN-SOUTH"}
    first = client.post(
        "/api/internal/supply-chain/consolidations/sites/", body,
        format="json", HTTP_IDEMPOTENCY_KEY="api2-site-create",
    )
    replay = client.post(
        "/api/internal/supply-chain/consolidations/sites/", body,
        format="json", HTTP_IDEMPOTENCY_KEY="api2-site-create",
    )
    unknown = client.post(
        "/api/internal/supply-chain/consolidations/sites/", {**body, "tenant_id": tenant.id},
        format="json", HTTP_IDEMPOTENCY_KEY="api2-site-unknown",
    )
    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    assert replay["Idempotency-Replayed"] == "true"
    assert unknown.status_code == 400


def test_custom_scope_must_be_complete_and_miniapp_channel_is_exclusive():
    tenant = Tenant.objects.create(name="API2 scope", code="api2-scope")
    user = internal_user(tenant, "api2-scope-user", permissions=("supply.consolidation_site.view",), scope_type=DataScope.ScopeType.CUSTOM, config={"consolidation_site_ids": [1]})
    client = APIClient(); client.force_authenticate(user=user)
    response = client.get("/api/internal/supply-chain/consolidations/sites/")
    assert response.status_code == 403

    mini = RefreshToken.for_user(user)
    mini["channel"] = "miniapp"
    mini_client = APIClient(); mini_client.credentials(HTTP_AUTHORIZATION=f"Bearer {mini.access_token}")
    response = mini_client.get("/api/internal/supply-chain/consolidations/sites/")
    assert response.status_code == 403


def test_shipment_create_and_supplier_unknown_assignment_are_scoped():
    tenant = Tenant.objects.create(name="API2 shipment", code="api2-shipment")
    user = internal_user(tenant, "api2-shipment-user", permissions=("supply.shipment.view", "supply.shipment.create"))
    client = APIClient(); client.force_authenticate(user=user)
    response = client.post(
        "/api/internal/supply-chain/shipments/",
        {"shipment_no": "S-API2", "region_code": "CN-SOUTH", "destination_country_code": "US"},
        format="json", HTTP_IDEMPOTENCY_KEY="api2-shipment-create",
    )
    assert response.status_code == 201
    detail = client.get(f"/api/internal/supply-chain/shipments/{response.json()['data']['id']}/")
    assert detail.status_code == 200

    supplier = SupplierMaster.objects.create(tenant=tenant, code="api2-supplier", name="API2 supplier")
    external = CustomUser.objects.create_user(username="api2-external", tenant=tenant, user_type=CustomUser.UserType.EXTERNAL)
    ExternalUserProfile.objects.create(user=external, tenant=tenant, supplier_id=supplier.id, company_name="API2 supplier")
    external_client = APIClient(); external_client.force_authenticate(user=external)
    hidden = external_client.get("/api/external/supplier/consolidations/assignments/999999/")
    assert hidden.status_code == 404
