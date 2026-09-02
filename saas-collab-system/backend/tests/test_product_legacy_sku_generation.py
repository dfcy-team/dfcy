import hashlib

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.coding_services import allocate_legacy_sku_code
from apps.products.models import ProductCategory, ProductColor, ProductLegacyItem, ProductSKU
from apps.tenants.models import Tenant


def _manager(tenant, username):
    user = CustomUser.objects.create_user(
        username=username,
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    role = Role.objects.create(tenant=tenant, code=f"{username}-role", name="Product manager")
    role.permissions.add(*Permission.objects.filter(code__in=["products.master.view", "products.master.manage"]))
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})
    return user


def _leaf_category(tenant):
    l1 = ProductCategory.objects.create(tenant=tenant, level=1, code="1", name="Home")
    l2 = ProductCategory.objects.create(tenant=tenant, parent=l1, level=2, code="01", name="Bedding")
    return ProductCategory.objects.create(
        tenant=tenant,
        parent=l2,
        level=3,
        code="08",
        name="Mattress",
        spec_dimensions=[{"code": "spec", "name": "Specification", "values": ["150cm"]}],
    )


def _legacy_item(tenant, category, legacy_sku_code):
    return ProductLegacyItem.objects.create(
        tenant=tenant,
        legacy_spu_code="OLD-SPU-115",
        legacy_sku_code=legacy_sku_code,
        product_name="Imported mattress",
        category_node=category,
        attribute_code="1",
        color_code="noc",
        specification="150cm",
    )


@pytest.mark.django_db
def test_legacy_variants_with_same_color_and_spec_get_distinct_codes():
    tenant = Tenant.objects.create(name="Legacy SKU tenant", code="legacy-sku")
    user = _manager(tenant, "legacy-sku-manager")
    category = _leaf_category(tenant)
    ProductColor.objects.create(tenant=tenant, code="noc", name="No color")
    first = _legacy_item(tenant, category, "OLD-SKU-001")
    second = _legacy_item(tenant, category, "OLD-SKU-002")
    client = APIClient()
    client.force_authenticate(user=user)

    first_response = client.post(f"/api/internal/products/legacy-items/{first.id}/generate/", format="json")
    second_response = client.post(f"/api/internal/products/legacy-items/{second.id}/generate/", format="json")

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    first.refresh_from_db()
    second.refresh_from_db()
    first_sku = ProductSKU.objects.get(pk=first.generated_sku_id)
    second_sku = ProductSKU.objects.get(pk=second.generated_sku_id)
    assert first_sku.sku_code != second_sku.sku_code
    assert first_sku.sku_code == f"{first_sku.spu.spu_code}-noc-150cm"
    assert second_sku.sku_code.endswith("-L" + hashlib.sha256(b"OLD-SKU-002").hexdigest()[:10].upper())
    assert len(first_sku.sku_code) <= 80
    assert len(second_sku.sku_code) <= 80
    assert {first_sku.legacy_sku_code, second_sku.legacy_sku_code} == {"OLD-SKU-001", "OLD-SKU-002"}


@pytest.mark.django_db
def test_retrying_one_legacy_item_reuses_the_generated_sku():
    tenant = Tenant.objects.create(name="Legacy retry tenant", code="legacy-retry")
    user = _manager(tenant, "legacy-retry-manager")
    category = _leaf_category(tenant)
    ProductColor.objects.create(tenant=tenant, code="noc", name="No color")
    item = _legacy_item(tenant, category, "OLD-SKU-RETRY")
    client = APIClient()
    client.force_authenticate(user=user)

    first_response = client.post(f"/api/internal/products/legacy-items/{item.id}/generate/", format="json")
    item.refresh_from_db()
    generated_id = item.generated_sku_id
    generated_code = item.generated_sku.sku_code
    second_response = client.post(f"/api/internal/products/legacy-items/{item.id}/generate/", format="json")

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    item.refresh_from_db()
    assert item.generated_sku_id == generated_id
    assert item.generated_sku.sku_code == generated_code
    assert ProductSKU.objects.filter(tenant=tenant, legacy_sku_code="OLD-SKU-RETRY").count() == 1


@pytest.mark.django_db
def test_legacy_code_fallback_is_length_safe_and_deterministic():
    tenant = Tenant.objects.create(name="Legacy length tenant", code="legacy-length")
    base_code = "SPU-" + "x" * 120
    legacy_sku_code = "OLD-SKU-LONG"

    candidate = allocate_legacy_sku_code(
        tenant=tenant,
        base_code=base_code,
        legacy_sku_code=legacy_sku_code,
    )
    expected_suffix = "-L" + hashlib.sha256(legacy_sku_code.encode("utf-8")).hexdigest()[:10].upper()

    assert len(candidate) <= 80
    assert candidate.endswith(expected_suffix)
    assert allocate_legacy_sku_code(
        tenant=tenant,
        base_code=base_code,
        legacy_sku_code=legacy_sku_code,
    ) == candidate
