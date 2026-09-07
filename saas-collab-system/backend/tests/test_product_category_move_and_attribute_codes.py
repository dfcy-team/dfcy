import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.coding_services import SEASON_CODES, allocate_spu_code
from apps.products.models import ProductCategory, ProductCodeSequence, ProductSKU, ProductSPU
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def _client(tenant, username):
    user = CustomUser.objects.create_user(
        username=username,
        password="test-password",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    role = Role.objects.create(tenant=tenant, code=f"{username}-role", name="Product manager")
    role.permissions.add(
        *Permission.objects.filter(
            code__in=[
                "products.category.view",
                "products.category.manage",
                "products.master.view",
                "products.master.manage",
                "products.attribute.view",
                "products.attribute.manage",
            ]
        )
    )
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _tree(tenant, *, l1_code="1", l2_code="01", l3_code="01"):
    l1 = ProductCategory.objects.create(tenant=tenant, level=1, code=l1_code, name=f"L1-{l1_code}")
    l2 = ProductCategory.objects.create(tenant=tenant, parent=l1, level=2, code=l2_code, name=f"L2-{l2_code}")
    l3 = ProductCategory.objects.create(
        tenant=tenant,
        parent=l2,
        level=3,
        code=l3_code,
        name=f"L3-{l3_code}",
        spec_dimensions=[{"code": "size", "name": "尺寸"}],
    )
    return l1, l2, l3


def test_category_patch_moves_parent_and_preserves_existing_product_codes():
    tenant = Tenant.objects.create(name="Move tenant", code="category-move")
    client = _client(tenant, "category-move-manager")
    source_l1, l2, l3 = _tree(tenant)
    target_l1 = ProductCategory.objects.create(tenant=tenant, level=1, code="2", name="Target")
    spu = ProductSPU.objects.create(
        tenant=tenant,
        spu_code="101016001",
        product_name="Existing product",
        category_node=l3,
        category=l3.name,
        l1_code="1",
        l2_code="01",
        l3_code="01",
        season_code="6",
    )
    sku = ProductSKU.objects.create(
        tenant=tenant,
        spu=spu,
        sku_code="101016001-RED-0",
        color_code="RED",
        specification="0",
    )

    response = client.patch(
        f"/api/internal/products/categories/{l2.pk}/",
        {"parent": target_l1.pk},
        format="json",
    )

    assert response.status_code == 200, response.content
    l2.refresh_from_db()
    l3.refresh_from_db()
    spu.refresh_from_db()
    sku.refresh_from_db()
    assert l2.parent_id == target_l1.pk
    assert l2.code == "01"
    assert l3.parent_id == l2.pk
    assert spu.spu_code == "101016001"
    assert sku.sku_code == "101016001-RED-0"

    # A later generated code follows the moved path and starts its new
    # sequence independently from the historical identifier.
    generated = client.post(
        "/api/internal/products/spus/",
        {"product_name": "New product", "category_node": l3.pk, "season_code": "6"},
        format="json",
    )
    assert generated.status_code == 201, generated.content
    assert generated.json()["data"]["spu_code"] == "201016001"


def test_category_move_rejects_wrong_tenant_level_cycle_duplicate_and_immutable_codes():
    tenant = Tenant.objects.create(name="Move validation tenant", code="category-move-validation")
    foreign_tenant = Tenant.objects.create(name="Foreign tenant", code="category-move-foreign")
    client = _client(tenant, "category-move-validation-manager")
    source_l1, l2, l3 = _tree(tenant)
    target_l1 = ProductCategory.objects.create(tenant=tenant, level=1, code="2", name="Target")
    foreign_l1 = ProductCategory.objects.create(tenant=foreign_tenant, level=1, code="9", name="Foreign")

    wrong_tenant = client.patch(
        f"/api/internal/products/categories/{l2.pk}/",
        {"parent": foreign_l1.pk},
        format="json",
    )
    wrong_level = client.patch(
        f"/api/internal/products/categories/{l3.pk}/",
        {"parent": target_l1.pk},
        format="json",
    )
    cycle = client.patch(
        f"/api/internal/products/categories/{l3.pk}/",
        {"parent": l3.pk},
        format="json",
    )
    immutable = client.patch(
        f"/api/internal/products/categories/{l2.pk}/",
        {"code": "02"},
        format="json",
    )

    assert wrong_tenant.status_code == 400
    assert wrong_level.status_code == 400
    assert cycle.status_code == 400
    assert immutable.status_code == 400

    ProductCategory.objects.create(tenant=tenant, parent=target_l1, level=2, code="01", name="Taken")
    duplicate = client.patch(
        f"/api/internal/products/categories/{l2.pk}/",
        {"parent": target_l1.pk},
        format="json",
    )
    assert duplicate.status_code == 400
    l2.refresh_from_db()
    assert l2.parent_id == source_l1.pk


def test_category_specification_put_supports_leaf_l2_and_l3_but_not_parent_l2():
    tenant = Tenant.objects.create(name="Specification tenant", code="category-spec-put")
    client = _client(tenant, "category-spec-manager")
    l1 = ProductCategory.objects.create(tenant=tenant, level=1, code="1", name="Home")
    leaf_l2 = ProductCategory.objects.create(tenant=tenant, parent=l1, level=2, code="01", name="Leaf")
    branch_l2 = ProductCategory.objects.create(tenant=tenant, parent=l1, level=2, code="02", name="Branch")
    l3 = ProductCategory.objects.create(tenant=tenant, parent=branch_l2, level=3, code="01", name="L3")

    dimensions = [{"code": "width", "name": "宽度"}, {"code": "length", "name": "长度"}]
    leaf_response = client.put(
        f"/api/internal/products/categories/{leaf_l2.pk}/attributes/",
        {"spec_dimensions": dimensions},
        format="json",
    )
    l3_response = client.put(
        f"/api/internal/products/categories/{l3.pk}/attributes/",
        {"spec_dimensions": dimensions},
        format="json",
    )
    branch_response = client.put(
        f"/api/internal/products/categories/{branch_l2.pk}/attributes/",
        {"spec_dimensions": dimensions},
        format="json",
    )

    assert leaf_response.status_code == 200, leaf_response.content
    assert l3_response.status_code == 200, l3_response.content
    assert branch_response.status_code == 400
    assert client.get(f"/api/internal/products/categories/{leaf_l2.pk}/attributes/").json()["data"]["spec_dimensions"] == dimensions
    assert client.get(f"/api/internal/products/categories/{l3.pk}/attributes/").json()["data"]["spec_dimensions"] == dimensions
    leaf_l2.refresh_from_db()
    l3.refresh_from_db()
    assert leaf_l2.spec_dimensions == dimensions
    assert l3.spec_dimensions == dimensions


@pytest.mark.parametrize("attribute_code", ["0", "6", "9"])
def test_spu_generation_accepts_attribute_codes_and_syncs_stale_sequences(attribute_code):
    tenant = Tenant.objects.create(name=f"Attribute tenant {attribute_code}", code=f"attribute-{attribute_code}")
    l1, l2, l3 = _tree(tenant)
    assert SEASON_CODES == {"1", "2", "3", "4", "5"}

    # The allocator must skip an existing generated-format code even when a
    # sequence row is stale or absent (as can happen after a category move or
    # an old manual import).
    ProductSPU.objects.create(
        tenant=tenant,
        spu_code=f"10101{attribute_code}001",
        product_name="Existing",
        category_node=l3,
        l1_code="1",
        l2_code="01",
        l3_code="01",
        season_code=attribute_code,
    )
    ProductCodeSequence.objects.create(
        tenant=tenant,
        l1_code="1",
        l2_code="01",
        l3_code="01",
        season_code=attribute_code,
        current_value=0,
    )

    code, segments = allocate_spu_code(tenant=tenant, category=l3, season_code=attribute_code)
    assert code == f"10101{attribute_code}002"
    assert segments == ("1", "01", "01")


def test_spu_api_defaults_to_attribute_code_zero_and_accepts_codes_six_and_nine():
    tenant = Tenant.objects.create(name="Attribute API tenant", code="attribute-api")
    client = _client(tenant, "attribute-api-manager")
    _l1, _l2, l3 = _tree(tenant)

    for attribute_code in ("0", "6", "9"):
        payload = {"product_name": f"Product {attribute_code}", "category_node": l3.pk}
        if attribute_code != "0":
            payload["season_code"] = attribute_code
        response = client.post("/api/internal/products/spus/", payload, format="json")
        assert response.status_code == 201, response.content
        assert response.json()["data"]["season_code"] == attribute_code
        assert response.json()["data"]["spu_code"] == f"10101{attribute_code}001"
