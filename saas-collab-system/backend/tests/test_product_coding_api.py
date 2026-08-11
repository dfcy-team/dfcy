import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.models import ProductBundleComponent, ProductCategory, ProductColor, ProductSPU
from apps.tenants.models import Tenant


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def manager_for(tenant, username="coding-manager"):
    user = CustomUser.objects.create_user(username=username, tenant=tenant, user_type=CustomUser.UserType.INTERNAL)
    role = Role.objects.create(tenant=tenant, code=f"{username}-role", name="Coding manager")
    role.permissions.add(*Permission.objects.filter(code__in=["products.master.view", "products.master.manage"]))
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})
    return user


def create_category_tree(client):
    l1 = client.post("/api/internal/products/categories/", {"level": 1, "code": "1", "name": "家纺"}, format="json").json()["data"]
    l2 = client.post(
        "/api/internal/products/categories/",
        {"level": 2, "parent": l1["id"], "code": "01", "name": "床上用品"},
        format="json",
    ).json()["data"]
    response = client.post(
        "/api/internal/products/categories/",
        {
            "level": 3,
            "parent": l2["id"],
            "code": "08",
            "name": "床垫",
            "spec_dimensions": [
                {"code": "width", "name": "宽度"},
                {"code": "length", "name": "长度"},
                {"code": "thickness", "name": "厚度"},
            ],
        },
        format="json",
    )
    assert response.status_code == 201
    return response.json()["data"]


@pytest.mark.django_db
def test_tenant_can_configure_category_and_generate_spu_and_sku_codes():
    tenant = Tenant.objects.create(name="Coding Tenant", code="coding-tenant")
    client = client_for(manager_for(tenant))
    category = create_category_tree(client)
    color = client.post(
        "/api/internal/products/colors/", {"code": "White", "name": "白色"}, format="json"
    )
    assert color.status_code == 201

    first_spu = client.post(
        "/api/internal/products/spus/",
        {"product_name": "床垫 A", "category_node": category["id"], "season_code": "5", "product_type": "standard"},
        format="json",
    )
    second_spu = client.post(
        "/api/internal/products/spus/",
        {"product_name": "床垫 B", "category_node": category["id"], "season_code": "5", "product_type": "standard"},
        format="json",
    )
    assert first_spu.status_code == 201
    assert first_spu.json()["data"]["spu_code"] == "101085001"
    assert second_spu.json()["data"]["spu_code"] == "101085002"

    sku = client.post(
        "/api/internal/products/skus/",
        {
            "spu": first_spu.json()["data"]["id"],
            "color_code": "White",
            "spec_values": {"width": "180cm", "length": "200cm", "thickness": "20cm"},
        },
        format="json",
    )
    assert sku.status_code == 201
    assert sku.json()["data"]["sku_code"] == "101085001-White-180cm×200cm×20cm"
    assert sku.json()["data"]["specification"] == "180cm×200cm×20cm"


@pytest.mark.django_db
def test_bundle_sku_accepts_standard_components_and_rejects_nested_bundle():
    tenant = Tenant.objects.create(name="Bundle Tenant", code="bundle-tenant")
    client = client_for(manager_for(tenant, "bundle-manager"))
    category = create_category_tree(client)
    client.post("/api/internal/products/colors/", {"code": "Multi", "name": "混色"}, format="json")

    def create_spu(name, product_type):
        response = client.post(
            "/api/internal/products/spus/",
            {"product_name": name, "category_node": category["id"], "season_code": "5", "product_type": product_type},
            format="json",
        )
        assert response.status_code == 201
        return response.json()["data"]

    standard_spu = create_spu("单品", ProductSPU.ProductType.STANDARD)
    bundle_spu = create_spu("组合装", ProductSPU.ProductType.BUNDLE)
    nested_spu = create_spu("另一个组合装", ProductSPU.ProductType.BUNDLE)

    def create_sku(spu):
        response = client.post(
            "/api/internal/products/skus/",
            {
                "spu": spu["id"],
                "color_code": "Multi",
                "spec_values": {"width": "0", "length": "0", "thickness": "0"},
            },
            format="json",
        )
        assert response.status_code == 201
        return response.json()["data"]

    standard_sku = create_sku(standard_spu)
    bundle_sku = create_sku(bundle_spu)
    nested_sku = create_sku(nested_spu)

    created = client.post(
        "/api/internal/products/bundle-components/",
        {"bundle_sku": bundle_sku["id"], "component_sku": standard_sku["id"], "quantity": 2},
        format="json",
    )
    rejected = client.post(
        "/api/internal/products/bundle-components/",
        {"bundle_sku": bundle_sku["id"], "component_sku": nested_sku["id"], "quantity": 1},
        format="json",
    )

    assert created.status_code == 201
    assert ProductBundleComponent.objects.get(pk=created.json()["data"]["id"]).quantity == 2
    assert rejected.status_code == 400


@pytest.mark.django_db
def test_category_and_color_are_tenant_isolated():
    tenant_a = Tenant.objects.create(name="Tenant A", code="coding-a")
    tenant_b = Tenant.objects.create(name="Tenant B", code="coding-b")
    client_a = client_for(manager_for(tenant_a, "manager-a"))
    client_b = client_for(manager_for(tenant_b, "manager-b"))
    category = create_category_tree(client_a)
    ProductColor.objects.create(tenant=tenant_a, code="Blue", name="蓝色")

    assert client_b.get("/api/internal/products/categories/").json()["data"] == []
    assert client_b.get("/api/internal/products/colors/").json()["data"] == []
    denied = client_b.post(
        "/api/internal/products/spus/",
        {"product_name": "越权商品", "category_node": category["id"], "season_code": "1"},
        format="json",
    )
    assert denied.status_code == 400
