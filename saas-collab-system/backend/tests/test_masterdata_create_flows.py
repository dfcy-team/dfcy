import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.masterdata.models import PlatformMaster, StoreMaster, SupplierMaster, WarehouseMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


@pytest.fixture
def manager_client():
    tenant = Tenant.objects.create(name="Archive create test", code="archive-create-test")
    user = CustomUser.objects.create_user(
        username="archive-create-manager", password="unused", tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    role = Role.objects.create(tenant=tenant, code="archive-manager", name="Archive manager")
    for code in ("masterdata.view", "masterdata.manage"):
        permission, _ = Permission.objects.get_or_create(
            code=code, defaults={"name": code, "module": "masterdata", "action": code.split(".")[1]},
        )
        role.permissions.add(permission)
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})
    client = APIClient()
    client.force_authenticate(user)
    return client, tenant


def test_create_four_archives_and_list_them(manager_client):
    client, tenant = manager_client
    cases = (
        ("platforms", {"code": "qa-platform", "name": "QA Platform", "platform_type": "other", "status": "active"}, PlatformMaster),
        ("stores", {"code": "qa-store", "name": "QA Store", "platform_id": None, "country_code": "TH", "currency": "THB", "timezone": "Asia/Bangkok"}, StoreMaster),
        ("warehouses", {"code": "qa-warehouse", "name": "QA Warehouse", "country_code": "TH", "warehouse_type": "owned", "service_platform_id": "", "status": "active"}, WarehouseMaster),
        ("suppliers", {"code": "qa-supplier", "name": "QA Supplier", "contact_alias": "QA"}, SupplierMaster),
    )
    platform_id = None
    for resource, raw, model in cases:
        payload = {**raw}
        if resource == "stores":
            payload["platform_id"] = platform_id
        response = client.post(f"/api/internal/master-data/{resource}/", payload, format="json")
        assert response.status_code == 201, (resource, response.data)
        assert response.data["data"]["code"] == payload["code"]
        assert model.objects.filter(tenant=tenant, code=payload["code"]).exists()
        listed = client.get(f"/api/internal/master-data/{resource}/")
        assert listed.status_code == 200, (resource, listed.data)
        assert any(row["code"] == payload["code"] for row in listed.data["data"]["results"])
        if resource == "platforms":
            platform_id = response.data["data"]["id"]


def test_warehouse_blank_platform_is_allowed_only_for_owned_warehouse(manager_client):
    client, tenant = manager_client
    payload = {
        "code": "qa-owned", "name": "QA Owned", "country_code": "TH",
        "warehouse_type": "owned", "service_platform_id": "", "status": "active",
    }
    created = client.post("/api/internal/master-data/warehouses/", payload, format="json")
    assert created.status_code == 201, created.data
    assert WarehouseMaster.objects.get(tenant=tenant, code="qa-owned").service_platform_id is None

    invalid = client.post(
        "/api/internal/master-data/warehouses/",
        {**payload, "code": "qa-third-party", "warehouse_type": "third_party"},
        format="json",
    )
    assert invalid.status_code == 400, invalid.data
    assert not WarehouseMaster.objects.filter(tenant=tenant, code="qa-third-party").exists()
