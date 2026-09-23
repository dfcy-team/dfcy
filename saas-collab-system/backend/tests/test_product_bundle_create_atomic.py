import pytest
from django.db import IntegrityError
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.models import (
    ProductBundleComponent,
    ProductBundleVersion,
    ProductCategory,
    ProductCodeSequence,
    ProductColor,
    ProductSKU,
    ProductSPU,
)
from apps.tenants.models import Tenant


def _bundle_client(tenant, username="bundle-atomic-user"):
    user = CustomUser.objects.create_user(
        username=username,
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    role = Role.objects.create(tenant=tenant, code=f"{username}-role", name="Bundle atomic role")
    role.permissions.add(*Permission.objects.filter(code__in=["products.bundle.view", "products.bundle.manage"]))
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _catalog(tenant, prefix=""):
    l1 = ProductCategory.objects.create(tenant=tenant, level=1, code="1", name=f"{prefix}一级")
    l2 = ProductCategory.objects.create(tenant=tenant, level=2, parent=l1, code="01", name=f"{prefix}二级")
    l3 = ProductCategory.objects.create(
        tenant=tenant,
        level=3,
        parent=l2,
        code="08",
        name=f"{prefix}三级",
        spec_dimensions=[{"code": "size", "name": "尺寸", "values": []}],
    )
    ProductColor.objects.create(tenant=tenant, code="Multi", name="混色")
    return l3


def _component_sku(tenant, code):
    spu = ProductSPU.objects.create(
        tenant=tenant,
        spu_code=f"SPU-{code}",
        product_name=code,
        product_type=ProductSPU.ProductType.STANDARD,
    )
    return ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code=code, product_name=code)


def _payload(category, component_skus):
    return {
        "product_name": "原子组合商品",
        "category_node": category.id,
        "season_code": "5",
        "color_code": "Multi",
        "components": [
            {"component_sku": sku.id, "quantity": index + 1}
            for index, sku in enumerate(component_skus)
        ],
    }


@pytest.mark.django_db
def test_bundle_create_commits_spu_sku_and_components_together():
    tenant = Tenant.objects.create(name="Bundle atomic tenant", code="bundle-atomic")
    client = _bundle_client(tenant)
    category = _catalog(tenant)
    components = [_component_sku(tenant, "NORMAL-A"), _component_sku(tenant, "NORMAL-B")]

    response = client.post("/api/internal/products/bundles/create/", _payload(category, components), format="json")

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["spu"]["product_type"] == ProductSPU.ProductType.BUNDLE
    assert data["sku"]["spu"] == data["spu"]["id"]
    assert [item["component_sku"] for item in data["components"]] == [sku.id for sku in components]
    assert ProductSPU.objects.filter(tenant=tenant, product_type=ProductSPU.ProductType.BUNDLE).count() == 1
    assert ProductBundleComponent.objects.filter(tenant=tenant).count() == 2
    version = ProductBundleVersion.objects.get(bundle_sku_id=data["sku"]["id"])
    assert version.version == 1
    assert version.components.count() == 2


@pytest.mark.django_db
def test_bundle_edit_persists_cost_allocation_ratio_in_current_and_version_data():
    tenant = Tenant.objects.create(name="Bundle ratio tenant", code="bundle-ratio")
    client = _bundle_client(tenant, "bundle-ratio-user")
    category = _catalog(tenant, "分摊")
    component = _component_sku(tenant, "RATIO-A")
    created = client.post("/api/internal/products/bundles/create/", _payload(category, [component]), format="json")
    assert created.status_code == 201
    sku_id = created.json()["data"]["sku"]["id"]
    url = f"/api/internal/products/bundles/{sku_id}/"

    changed = client.put(url, {"reason": "调整分摊", "components": [
        {"component_sku": component.id, "quantity": 2, "cost_allocation_ratio": "1.2500"}
    ]}, format="json")
    assert changed.status_code == 200
    data = client.get(url).json()["data"]
    assert data["components"][0]["cost_allocation_ratio"] == "1.2500"
    assert data["versions"][0]["components"][0]["cost_allocation_ratio"] == "1.2500"

    invalid = client.put(url, {"reason": "无效分摊", "components": [
        {"component_sku": component.id, "quantity": 2, "cost_allocation_ratio": "0"}
    ]}, format="json")
    assert invalid.status_code == 400
    assert ProductBundleComponent.objects.get(bundle_sku_id=sku_id).cost_allocation_ratio == 1.25


@pytest.mark.django_db
def test_bundle_image_url_is_cached_through_bundle_scoped_endpoint(monkeypatch):
    tenant = Tenant.objects.create(name="Bundle image tenant", code="bundle-image")
    client = _bundle_client(tenant, "bundle-image-user")
    category = _catalog(tenant, "图片")
    component = _component_sku(tenant, "NORMAL-IMAGE")
    created = client.post("/api/internal/products/bundles/create/", _payload(category, [component]), format="json")
    sku_id = created.json()["data"]["sku"]["id"]

    monkeypatch.setattr("apps.products.views._download_product_image", lambda url, tenant_id: ("product-images/cached.webp", "image/webp", False))
    monkeypatch.setattr("apps.products.views._attach_cached_product_image", lambda *args, **kwargs: (True, "/media/product-images/cached.webp"))

    response = client.post(
        f"/api/internal/products/bundles/{sku_id}/image-cache/",
        {"image_url": "https://cdn.example.test/bundle.webp"},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["data"]["image_url"] == "/media/product-images/cached.webp"


@pytest.mark.django_db
def test_bundle_create_rolls_back_every_write_when_a_component_insert_fails(monkeypatch):
    tenant = Tenant.objects.create(name="Bundle rollback tenant", code="bundle-rollback")
    client = _bundle_client(tenant, "bundle-rollback-user")
    category = _catalog(tenant, "回滚")
    components = [_component_sku(tenant, "ROLLBACK-A"), _component_sku(tenant, "ROLLBACK-B")]
    original_save = ProductBundleComponent.save
    calls = 0

    def fail_second_component(instance, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise IntegrityError("simulated component conflict")
        return original_save(instance, *args, **kwargs)

    monkeypatch.setattr(ProductBundleComponent, "save", fail_second_component)
    response = client.post("/api/internal/products/bundles/create/", _payload(category, components), format="json")

    assert response.status_code == 409
    assert response.json()["code"] == "STATE_CONFLICT"
    assert not ProductSPU.objects.filter(tenant=tenant, product_type=ProductSPU.ProductType.BUNDLE).exists()
    assert not ProductBundleComponent.objects.filter(tenant=tenant).exists()
    assert not ProductCodeSequence.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db
def test_bundle_create_rejects_duplicate_or_cross_tenant_components_before_writing():
    tenant = Tenant.objects.create(name="Bundle validation tenant", code="bundle-validation")
    other_tenant = Tenant.objects.create(name="Other bundle tenant", code="bundle-validation-other")
    client = _bundle_client(tenant, "bundle-validation-user")
    category = _catalog(tenant, "校验")
    component = _component_sku(tenant, "VALID-A")
    foreign_component = _component_sku(other_tenant, "FOREIGN-A")

    duplicate = client.post(
        "/api/internal/products/bundles/create/",
        _payload(category, [component, component]),
        format="json",
    )
    foreign = client.post(
        "/api/internal/products/bundles/create/",
        _payload(category, [foreign_component]),
        format="json",
    )

    assert duplicate.status_code == 400
    assert foreign.status_code == 400
    assert not ProductSPU.objects.filter(tenant=tenant, product_type=ProductSPU.ProductType.BUNDLE).exists()


@pytest.mark.django_db
def test_bundle_create_can_add_sku_to_existing_bundle_spu():
    tenant = Tenant.objects.create(name="Existing bundle tenant", code="bundle-existing")
    client = _bundle_client(tenant, "bundle-existing-user")
    category = _catalog(tenant, "已有")
    component = _component_sku(tenant, "EXISTING-A")
    existing_spu = ProductSPU.objects.create(
        tenant=tenant,
        spu_code="BUNDLE-EXISTING-SPU",
        product_name="已有组合",
        product_type=ProductSPU.ProductType.BUNDLE,
        category_node=category,
        season_code="5",
        l1_code="1",
        l2_code="01",
        l3_code="08",
    )
    payload = {
        "spu_mode": "existing",
        "existing_spu": existing_spu.id,
        "color_code": "Multi",
        "components": [{"component_sku": component.id, "quantity": 2}],
    }

    response = client.post("/api/internal/products/bundles/create/", payload, format="json")

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["spu"]["id"] == existing_spu.id
    assert data["sku"]["spu"] == existing_spu.id
    assert ProductSPU.objects.filter(tenant=tenant, product_type=ProductSPU.ProductType.BUNDLE).count() == 1
    assert ProductBundleComponent.objects.get(bundle_sku_id=data["sku"]["id"]).quantity == 2


@pytest.mark.django_db
def test_bundle_create_existing_spu_rejects_standard_and_cross_tenant_spus():
    tenant = Tenant.objects.create(name="Existing validation tenant", code="bundle-existing-validation")
    other_tenant = Tenant.objects.create(name="Foreign existing tenant", code="bundle-existing-foreign")
    client = _bundle_client(tenant, "bundle-existing-validation-user")
    category = _catalog(tenant, "已有校验")
    foreign_category = _catalog(other_tenant, "外部")
    component = _component_sku(tenant, "EXISTING-VALID-A")
    standard_spu = ProductSPU.objects.create(
        tenant=tenant, spu_code="STANDARD-SPU", product_name="普通", category_node=category,
    )
    foreign_bundle_spu = ProductSPU.objects.create(
        tenant=other_tenant,
        spu_code="FOREIGN-BUNDLE-SPU",
        product_name="外部组合",
        product_type=ProductSPU.ProductType.BUNDLE,
        category_node=foreign_category,
    )
    base_payload = {
        "spu_mode": "existing",
        "color_code": "Multi",
        "components": [{"component_sku": component.id, "quantity": 1}],
    }

    standard = client.post(
        "/api/internal/products/bundles/create/",
        {**base_payload, "existing_spu": standard_spu.id},
        format="json",
    )
    foreign = client.post(
        "/api/internal/products/bundles/create/",
        {**base_payload, "existing_spu": foreign_bundle_spu.id},
        format="json",
    )

    assert standard.status_code == 400
    assert foreign.status_code == 400
    assert not ProductSKU.objects.filter(tenant=tenant, spu=standard_spu).exists()
