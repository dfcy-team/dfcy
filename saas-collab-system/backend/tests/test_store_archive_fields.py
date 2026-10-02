import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.models import ProductCategory
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def _manager(tenant):
    user = CustomUser.objects.create_user("store-archive-manager", password="not-a-real-password", tenant=tenant, user_type="internal")
    role = Role.objects.create(tenant=tenant, code="store-archive-manager-role", name="Store archive manager")
    permission, _ = Permission.objects.get_or_create(code="masterdata.manage", defaults={"name": "masterdata.manage", "module": "masterdata", "action": "manage"})
    role.permissions.add(permission)
    view_permission, _ = Permission.objects.get_or_create(
        code="masterdata.view", defaults={"name": "masterdata.view", "module": "masterdata", "action": "view"}
    )
    role.permissions.add(view_permission)
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})
    return user


def test_store_archive_fields_and_import_are_tenant_scoped_and_idempotent():
    tenant = Tenant.objects.create(name="Store archive tenant", code="store-archive")
    manager = _manager(tenant)
    operator = CustomUser.objects.create_user("store-operator", password="not-a-real-password", tenant=tenant, user_type="internal", full_name="运营")
    platform = PlatformMaster.objects.create(tenant=tenant, code="shopee", name="Shopee", platform_type="shopee")
    category = ProductCategory.objects.create(tenant=tenant, level=1, code="1", name="服装")
    client = APIClient(); client.force_authenticate(manager)

    response = client.post("/api/internal/master-data/stores/", {
        "platform_id": platform.pk, "code": "store-ph", "name": "菲律宾店铺", "platform_store_name": "Shopee PH",
        "category_id": category.pk, "operator_id": operator.pk, "is_connected": True, "tactical_client": "战斧-01",
        "country_code": "PH", "currency": "PHP", "timezone": "Asia/Manila",
    }, format="json")
    assert response.status_code == 201
    assert response.data["data"]["operator_name"] == "运营"
    assert response.data["data"]["is_connected"] is True

    csv = "店铺档案编码,店铺名称,平台,平台店铺名,类目,负责运营,是否建联,战斧客户端,国家代码,币种,时区\nstore-ph,菲律宾店铺更新,Shopee,Shopee PH Updated,1,store-operator,是,战斧-02,PH,PHP,Asia/Manila\n".encode("utf-8-sig")
    imported = client.post("/api/internal/master-data/stores/", {"file": SimpleUploadedFile("stores.csv", csv, content_type="text/csv")})
    assert imported.status_code == 200
    assert imported.data["data"]["created"] == 0
    assert imported.data["data"]["updated"] == 1
    store = StoreMaster.objects.get(tenant=tenant, code="store-ph")
    assert store.name == "菲律宾店铺更新"
    assert store.tactical_client == "战斧-02"


def test_store_facets_cover_all_pages_and_filters_are_platform_country_exact():
    tenant = Tenant.objects.create(name="Store facet tenant", code="store-facets")
    other_tenant = Tenant.objects.create(name="Other store facet tenant", code="store-facets-other")
    manager = _manager(tenant)
    shopee = PlatformMaster.objects.create(tenant=tenant, code="shopee", name="Shopee", platform_type="shopee")
    lazada = PlatformMaster.objects.create(tenant=tenant, code="lazada", name="Lazada", platform_type="lazada")
    foreign_platform = PlatformMaster.objects.create(
        tenant=other_tenant, code="shopee", name="Other Shopee", platform_type="shopee"
    )
    for index in range(21):
        StoreMaster.objects.create(
            tenant=tenant, platform=shopee, code=f"ph-{index:02d}", name=f"Philippines {index:02d}",
            country_code="PH", currency="PHP",
        )
    for index in range(2):
        StoreMaster.objects.create(
            tenant=tenant, platform=shopee, code=f"sg-{index}", name=f"Singapore {index}",
            country_code="SG", currency="SGD", status="inactive" if index == 0 else "active",
        )
    StoreMaster.objects.create(
        tenant=tenant, platform=shopee, code="country-missing", name="Missing country",
        country_code="", currency="USD",
    )
    StoreMaster.objects.create(
        tenant=tenant, platform=lazada, code="my-0", name="Malaysia", country_code="MY", currency="MYR",
    )
    StoreMaster.objects.create(
        tenant=other_tenant, platform=foreign_platform, code="foreign-ph", name="Other PH",
        country_code="PH", currency="PHP",
    )

    client = APIClient(); client.force_authenticate(manager)
    url = "/api/internal/master-data/stores/"
    second_page = client.get(url, {"page": 2, "page_size": 10})
    assert second_page.status_code == 200
    assert second_page.data["data"]["count"] == 25
    assert len(second_page.data["data"]["results"]) == 10
    facets = second_page.data["data"]["store_facets"]
    assert facets["total"] == 25
    by_platform = {item["platform_id"]: item for item in facets["platforms"]}
    assert by_platform[shopee.pk]["platform_name"] == "Shopee"
    assert by_platform[shopee.pk]["count"] == 24
    assert {item["country_code"]: item["count"] for item in by_platform[shopee.pk]["countries"]} == {
        "PH": 21, "SG": 2, "__unset__": 1,
    }
    assert by_platform[lazada.pk]["count"] == 1
    assert foreign_platform.pk not in by_platform

    filtered = client.get(url, {"platform_id": shopee.pk, "country_code": "ph", "page": 2, "page_size": 10})
    assert filtered.status_code == 200
    assert filtered.data["data"]["count"] == 21
    assert len(filtered.data["data"]["results"]) == 10
    assert all(item["platform_id"] == shopee.pk and item["country_code"] == "PH"
               for item in filtered.data["data"]["results"])
    assert filtered.data["data"]["store_facets"] == facets

    inactive = client.get(url, {"search": "sg-0", "status": "inactive", "platform_id": shopee.pk})
    assert inactive.status_code == 200
    assert [item["code"] for item in inactive.data["data"]["results"]] == ["sg-0"]
    assert inactive.data["data"]["store_facets"] == facets

    missing = client.get(url, {"platform_id": shopee.pk, "country_code": "__unset__"})
    assert missing.status_code == 200
    assert [item["code"] for item in missing.data["data"]["results"]] == ["country-missing"]
    assert client.get(url, {"platform_id": "bad"}).status_code == 400
    assert client.get(url, {"platform_id": "9" * 5000}).status_code == 400


def test_store_facets_respect_custom_store_scope_and_tenant():
    tenant = Tenant.objects.create(name="Scoped store tenant", code="store-facets-scope")
    other_tenant = Tenant.objects.create(name="Foreign scoped store tenant", code="store-facets-scope-other")
    platform = PlatformMaster.objects.create(tenant=tenant, code="shopee", name="Shopee", platform_type="shopee")
    foreign_platform = PlatformMaster.objects.create(
        tenant=other_tenant, code="shopee", name="Other Shopee", platform_type="shopee"
    )
    allowed = StoreMaster.objects.create(
        tenant=tenant, platform=platform, code="allowed", name="Allowed", country_code="PH", currency="PHP",
    )
    StoreMaster.objects.create(
        tenant=tenant, platform=platform, code="blocked", name="Blocked", country_code="SG", currency="SGD",
    )
    foreign = StoreMaster.objects.create(
        tenant=other_tenant, platform=foreign_platform, code="foreign", name="Foreign",
        country_code="MY", currency="MYR",
    )
    viewer = CustomUser.objects.create_user(
        "store-facet-viewer", password="not-a-real-password", tenant=tenant, user_type="internal"
    )
    role = Role.objects.create(tenant=tenant, code="store-facet-viewer-role", name="Store facet viewer")
    permission, _ = Permission.objects.get_or_create(
        code="masterdata.view", defaults={"name": "masterdata.view", "module": "masterdata", "action": "view"}
    )
    role.permissions.add(permission)
    UserRole.objects.create(tenant=tenant, user=viewer, role=role)
    DataScope.objects.create(
        tenant=tenant, role=role, scope_type=DataScope.ScopeType.CUSTOM,
        config={"store_ids": [allowed.pk, foreign.pk]},
    )

    client = APIClient(); client.force_authenticate(viewer)
    response = client.get("/api/internal/master-data/stores/")
    assert response.status_code == 200
    assert [item["id"] for item in response.data["data"]["results"]] == [allowed.pk]
    assert response.data["data"]["store_facets"] == {
        "total": 1,
        "platforms": [{
            "platform_id": platform.pk, "platform_name": "Shopee", "count": 1,
            "countries": [{"country_code": "PH", "count": 1}],
        }],
    }
    filtered = client.get("/api/internal/master-data/stores/", {"country_code": "SG"})
    assert filtered.status_code == 200
    assert filtered.data["data"]["count"] == 0
    assert filtered.data["data"]["store_facets"]["total"] == 1
