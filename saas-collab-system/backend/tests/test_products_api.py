import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.products.models import ProductResearch, ProductSKU, ProductSPU
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


def create_user(tenant, username, user_type):
    user = CustomUser.objects.create_user(
        username=username,
        tenant=tenant,
        user_type=user_type,
    )
    if user_type == CustomUser.UserType.INTERNAL:
        role = Role.objects.create(tenant=tenant, code=f"{username}-product-role", name="Product role")
        role.permissions.add(
            *Permission.objects.filter(code__in=[
                "products.research.view", "products.research.manage",
                "products.master.view", "products.master.manage", "products.master.freeze",
            ])
        )
        UserRole.objects.create(tenant=tenant, user=user, role=role)
        DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})
    return user


def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_internal_user_can_create_and_list_product_research_with_unified_response():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "internal-products", CustomUser.UserType.INTERNAL)
    client = authenticated_client(user)

    create_response = client.post(
        "/api/internal/products/research/",
        data={
            "research_no": "RS-001",
            "product_name": "Foldable Storage Box",
            "platform": "bigseller",
            "competitor_url": "https://example.test/item/1",
            "estimated_sales": 120,
            "estimated_gross_margin": "0.3200",
            "risk_points": ["fragile packaging"],
            "approval_status": "draft",
        },
        format="json",
    )
    list_response = client.get("/api/internal/products/research/")

    assert create_response.status_code == 201
    assert create_response.json()["success"] is True
    assert create_response.json()["code"] == "OK"
    assert create_response.json()["message"] == "success"
    assert create_response.json()["data"]["tenant_id"] == tenant.id
    assert create_response.json()["data"]["created_by_id"] == user.id
    assert list_response.status_code == 200
    assert list_response.json()["data"]["count"] == 1
    assert len(list_response.json()["data"]["results"]) == 1


@pytest.mark.django_db
def test_internal_user_can_create_spu_and_sku():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "internal-spu-sku", CustomUser.UserType.INTERNAL)
    client = authenticated_client(user)

    spu_response = client.post(
        "/api/internal/products/spus/",
        data={
            "spu_code": "SPU-001",
            "product_name": "Storage Box",
            "category": "home",
            "lifecycle_status": "draft",
            "sales_status": "not_listed",
        },
        format="json",
    )
    sku_response = client.post(
        "/api/internal/products/skus/",
        data={
            "spu": spu_response.json()["data"]["id"],
            "sku_code": "SKU-001",
            "size": "M",
            "material": "PP",
            "selling_points": ["foldable"],
            "package_weight": "1.200",
            "package_volume": "0.030",
        },
        format="json",
    )

    assert spu_response.status_code == 201
    assert sku_response.status_code == 201
    assert sku_response.json()["data"]["tenant_id"] == tenant.id
    assert sku_response.json()["data"]["spu"] == spu_response.json()["data"]["id"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("user_type", "username"),
    [
        (CustomUser.UserType.EXTERNAL, "external-products-denied"),
        (CustomUser.UserType.RPA, "rpa-products-denied"),
    ],
)
def test_non_internal_users_cannot_access_product_api(user_type, username):
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, username, user_type)
    client = authenticated_client(user)

    paths = [
        "/api/internal/products/research/",
        "/api/internal/products/spus/",
        "/api/internal/products/skus/",
    ]

    for path in paths:
        get_response = client.get(path)
        post_response = client.post(path, data={}, format="json")
        assert get_response.status_code == 403
        assert post_response.status_code == 403


@pytest.mark.django_db
def test_product_api_filters_by_tenant():
    tenant_a = Tenant.objects.create(name="Tenant A", code="tenant-a")
    tenant_b = Tenant.objects.create(name="Tenant B", code="tenant-b")
    user_a = create_user(tenant_a, "tenant-a-user", CustomUser.UserType.INTERNAL)
    user_b = create_user(tenant_b, "tenant-b-user", CustomUser.UserType.INTERNAL)
    ProductResearch.objects.create(
        tenant=tenant_a,
        research_no="RS-A",
        product_name="Tenant A Product",
        created_by=user_a,
    )
    hidden_research = ProductResearch.objects.create(
        tenant=tenant_b,
        research_no="RS-B",
        product_name="Tenant B Product",
        created_by=user_b,
    )
    ProductSPU.objects.create(
        tenant=tenant_b,
        spu_code="SPU-B",
        product_name="Hidden SPU",
    )
    client = authenticated_client(user_a)

    list_response = client.get("/api/internal/products/research/")
    hidden_detail_response = client.get(f"/api/internal/products/research/{hidden_research.id}/")
    hidden_spu_response = client.get("/api/internal/products/spus/")

    assert list_response.status_code == 200
    assert [item["research_no"] for item in list_response.json()["data"]["results"]] == ["RS-A"]
    assert hidden_detail_response.status_code == 404
    assert hidden_spu_response.status_code == 200
    assert hidden_spu_response.json()["data"]["results"] == []


@pytest.mark.django_db
def test_freeze_spu_code_blocks_spu_and_sku_code_changes():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "freeze-user", CustomUser.UserType.INTERNAL)
    spu = ProductSPU.objects.create(
        tenant=tenant,
        spu_code="SPU-FREEZE",
        product_name="Frozen Product",
    )
    sku = ProductSKU.objects.create(
        tenant=tenant,
        spu=spu,
        sku_code="SKU-FREEZE",
    )
    client = authenticated_client(user)

    freeze_response = client.post(f"/api/internal/products/spus/{spu.id}/freeze-code/", data={}, format="json")
    spu_patch_response = client.patch(
        f"/api/internal/products/spus/{spu.id}/",
        data={"spu_code": "SPU-CHANGED"},
        format="json",
    )
    sku_patch_response = client.patch(
        f"/api/internal/products/skus/{sku.id}/",
        data={"sku_code": "SKU-CHANGED"},
        format="json",
    )
    name_patch_response = client.patch(
        f"/api/internal/products/spus/{spu.id}/",
        data={"product_name": "Frozen Product Updated"},
        format="json",
    )

    assert freeze_response.status_code == 200
    assert freeze_response.json()["data"]["is_code_frozen"] is True
    assert spu_patch_response.status_code == 400
    assert spu_patch_response.json()["success"] is False
    assert spu_patch_response.json()["code"] == "VALIDATION_ERROR"
    assert sku_patch_response.status_code == 400
    assert sku_patch_response.json()["code"] == "VALIDATION_ERROR"
    assert name_patch_response.status_code == 200
    spu.refresh_from_db()
    sku.refresh_from_db()
    assert spu.spu_code == "SPU-FREEZE"
    assert sku.sku_code == "SKU-FREEZE"
    assert sku.is_code_frozen is True


@pytest.mark.django_db
def test_sku_cannot_bind_spu_from_another_tenant():
    tenant_a = Tenant.objects.create(name="Tenant A", code="tenant-a")
    tenant_b = Tenant.objects.create(name="Tenant B", code="tenant-b")
    user_a = create_user(tenant_a, "tenant-a-sku-user", CustomUser.UserType.INTERNAL)
    spu_b = ProductSPU.objects.create(
        tenant=tenant_b,
        spu_code="SPU-B",
        product_name="Tenant B Product",
    )
    client = authenticated_client(user_a)

    response = client.post(
        "/api/internal/products/skus/",
        data={"spu": spu_b.id, "sku_code": "SKU-CROSS-TENANT"},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["success"] is False
    assert response.json()["code"] == "VALIDATION_ERROR"
