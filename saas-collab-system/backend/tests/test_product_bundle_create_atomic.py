import pytest
from django.db import IntegrityError
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.models import (
    ProductBundleComponent,
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
