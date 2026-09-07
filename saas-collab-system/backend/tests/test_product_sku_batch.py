import pytest
from rest_framework import serializers
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.models import ProductCategory, ProductColor, ProductSKU, ProductSPU
from apps.products.serializers import ProductSKUSerializer
from apps.tenants.models import Tenant


def _user(tenant, suffix, *, scope=DataScope.ScopeType.ALL):
    user = CustomUser.objects.create_user(
        username=f"batch-{suffix}",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    role = Role.objects.create(tenant=tenant, code=f"batch-role-{suffix}", name="Batch product role")
    role.permissions.add(*Permission.objects.filter(code__in=["products.master.view", "products.master.manage"]))
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=scope, config={})
    return user


def _category(tenant, *, dimensions):
    l1 = ProductCategory.objects.create(tenant=tenant, level=1, code="1", name="家居")
    l2 = ProductCategory.objects.create(tenant=tenant, level=2, code="01", name="床上用品", parent=l1)
    return ProductCategory.objects.create(
        tenant=tenant,
        level=3,
        code="01",
        name="床笠",
        parent=l2,
        spec_dimensions=dimensions,
    )


def _client_and_spu(*, suffix="one", dimensions=None):
    tenant = Tenant.objects.create(name=f"Batch tenant {suffix}", code=f"batch-{suffix}")
    user = _user(tenant, suffix)
    category = _category(tenant, dimensions=dimensions or [])
    spu = ProductSPU.objects.create(
        tenant=tenant,
        spu_code=f"SPU-{suffix}",
        product_name="批量商品",
        category_node=category,
    )
    return APIClient(), user, tenant, category, spu


def _post(client, user, payload):
    client.force_authenticate(user=user)
    return client.post("/api/internal/products/skus/batch/", payload, format="json")


@pytest.mark.django_db
def test_batch_creates_cartesian_product_and_is_idempotent():
    client, user, tenant, category, spu = _client_and_spu(
        dimensions=[{"code": "size", "name": "尺寸", "values": []}]
    )
    ProductColor.objects.create(tenant=tenant, code="red", name="红")
    ProductColor.objects.create(tenant=tenant, code="blue", name="蓝")

    response = _post(
        client,
        user,
        {
            "spu": spu.id,
            "color_codes": ["red", "blue", "red"],
            "spec_values": {"size": ["180cm", "200cm", "180cm"]},
        },
    )

    assert response.status_code == 201
    assert response.json()["data"]["created"] == 4
    assert response.json()["data"]["skipped"] == 0
    assert response.json()["data"]["total"] == 4
    assert ProductSKU.objects.filter(tenant=tenant, spu=spu).count() == 4
    assert set(ProductSKU.objects.filter(spu=spu).values_list("sku_code", flat=True)) == {
        "SPU-one-red-180cm",
        "SPU-one-red-200cm",
        "SPU-one-blue-180cm",
        "SPU-one-blue-200cm",
    }

    retry = _post(
        client,
        user,
        {
            "spu": spu.id,
            "color_codes": ["blue", "red"],
            "spec_values": {"size": ["200cm", "180cm"]},
        },
    )
    assert retry.status_code == 200
    assert retry.json()["data"] == {"created": 0, "skipped": 4, "total": 4, "results": []}


@pytest.mark.django_db
def test_batch_supports_multiple_dimensions_and_no_specification_categories():
    client, user, tenant, _category_with_specs, spu = _client_and_spu(
        suffix="multi",
        dimensions=[
            {"code": "length", "name": "长度", "values": []},
            {"code": "width", "name": "宽度", "values": []},
        ],
    )
    ProductColor.objects.create(tenant=tenant, code="red", name="红")
    response = _post(
        client,
        user,
        {
            "spu": spu.id,
            "color_codes": ["red"],
            "spec_values": {"length": ["180cm", "200cm"], "width": ["80cm", "100cm"]},
        },
    )
    assert response.status_code == 201
    assert response.json()["data"]["total"] == 4
    assert ProductSKU.objects.filter(spu=spu).count() == 4
    assert {sku.spec_values["length"] for sku in ProductSKU.objects.filter(spu=spu)} == {"180cm", "200cm"}

    no_spec_client, no_spec_user, no_spec_tenant, _category, no_spec_spu = _client_and_spu(
        suffix="none", dimensions=[]
    )
    ProductColor.objects.create(tenant=no_spec_tenant, code="black", name="黑")
    no_spec = _post(
        no_spec_client,
        no_spec_user,
        {"spu": no_spec_spu.id, "color_codes": ["black"], "spec_values": {}},
    )
    assert no_spec.status_code == 201
    assert no_spec.json()["data"]["results"][0]["sku_code"] == "SPU-none-black"


@pytest.mark.django_db
def test_batch_allows_an_enabled_leaf_l2_category_for_existing_spu():
    tenant = Tenant.objects.create(name="L2 batch tenant", code="batch-l2")
    user = _user(tenant, "l2")
    l1 = ProductCategory.objects.create(tenant=tenant, level=1, code="1", name="家居")
    l2 = ProductCategory.objects.create(
        tenant=tenant,
        level=2,
        code="01",
        name="床上用品",
        parent=l1,
    )
    spu = ProductSPU.objects.create(
        tenant=tenant,
        spu_code="SPU-L2",
        product_name="二级叶子商品",
        category_node=l2,
    )
    ProductColor.objects.create(tenant=tenant, code="red", name="红")

    response = _post(
        APIClient(),
        user,
        {"spu": spu.id, "color_codes": ["red"], "spec_values": {}},
    )
    assert response.status_code == 201
    assert response.json()["data"]["results"][0]["sku_code"] == "SPU-L2-red"


@pytest.mark.django_db
def test_batch_rejects_invalid_values_scope_tenant_and_over_limit_atomically():
    client, user, tenant, _category, spu = _client_and_spu(
        suffix="invalid",
        dimensions=[{"code": "size", "name": "尺寸", "values": []}],
    )
    ProductColor.objects.create(tenant=tenant, code="red", name="红")

    invalid_dimension = _post(
        client,
        user,
        {"spu": spu.id, "color_codes": ["red"], "spec_values": {"unknown": ["180cm"]}},
    )
    assert invalid_dimension.status_code == 400
    assert ProductSKU.objects.filter(spu=spu).count() == 0

    invalid_color = _post(
        client,
        user,
        {"spu": spu.id, "color_codes": ["missing"], "spec_values": {}},
    )
    assert invalid_color.status_code == 400
    assert ProductSKU.objects.filter(spu=spu).count() == 0

    over_limit = _post(
        client,
        user,
        {
            "spu": spu.id,
            "color_codes": ["red"],
            "spec_values": {"size": [f"{number}cm" for number in range(201)]},
        },
    )
    assert over_limit.status_code == 400
    assert ProductSKU.objects.filter(spu=spu).count() == 0

    other_tenant = Tenant.objects.create(name="Other batch tenant", code="batch-other")
    other_spu = ProductSPU.objects.create(tenant=other_tenant, spu_code="SPU-OTHER", product_name="其他")
    hidden = _post(client, user, {"spu": other_spu.id, "color_codes": ["red"], "spec_values": {}})
    assert hidden.status_code == 400

    scoped_user = _user(tenant, "custom", scope=DataScope.ScopeType.CUSTOM)
    scoped = _post(
        client,
        scoped_user,
        {"spu": spu.id, "color_codes": ["red"], "spec_values": {"size": ["180cm"]}},
    )
    assert scoped.status_code == 403


@pytest.mark.django_db
def test_batch_rejects_code_collision_owned_by_another_spu_without_partial_write():
    client, user, tenant, _category, spu = _client_and_spu(
        suffix="collision",
        dimensions=[],
    )
    ProductColor.objects.create(tenant=tenant, code="red", name="红")
    other = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-OTHER", product_name="其他")
    ProductSKU.objects.create(tenant=tenant, spu=other, sku_code="SPU-collision-red")

    response = _post(
        client,
        user,
        {"spu": spu.id, "color_codes": ["red"], "spec_values": {}},
    )
    assert response.status_code == 400
    assert ProductSKU.objects.filter(spu=spu).count() == 0
    assert ProductSKU.objects.filter(spu=other, sku_code="SPU-collision-red").count() == 1


@pytest.mark.django_db
def test_batch_rolls_back_created_rows_and_dictionary_changes_on_save_failure(monkeypatch):
    client, user, tenant, category, spu = _client_and_spu(
        suffix="rollback",
        dimensions=[{"code": "size", "name": "尺寸", "values": []}],
    )
    ProductColor.objects.create(tenant=tenant, code="red", name="红")
    ProductColor.objects.create(tenant=tenant, code="blue", name="蓝")
    original_create = ProductSKUSerializer.create
    calls = {"count": 0}

    def fail_second_create(serializer, validated_data):
        calls["count"] += 1
        if calls["count"] == 2:
            raise serializers.ValidationError("模拟批次中途失败")
        return original_create(serializer, validated_data)

    monkeypatch.setattr(ProductSKUSerializer, "create", fail_second_create)
    response = _post(
        client,
        user,
        {
            "spu": spu.id,
            "color_codes": ["red", "blue"],
            "spec_values": {"size": ["180cm"]},
        },
    )
    assert response.status_code == 400
    assert ProductSKU.objects.filter(tenant=tenant, spu=spu).count() == 0
    category.refresh_from_db()
    assert category.spec_dimensions == [{"code": "size", "name": "尺寸", "values": []}]


@pytest.mark.django_db
def test_batch_rejects_float_spu_inactive_color_invalid_unit_and_long_code():
    client, user, tenant, category, spu = _client_and_spu(
        suffix="shape",
        dimensions=[{"code": "size", "name": "尺寸", "values": []}],
    )
    ProductColor.objects.create(tenant=tenant, code="red", name="红")
    ProductColor.objects.create(tenant=tenant, code="off", name="停用", is_active=False)

    float_spu = _post(
        client,
        user,
        {"spu": spu.id + 0.5, "color_codes": ["red"], "spec_values": {}},
    )
    assert float_spu.status_code == 400

    inactive = _post(
        client,
        user,
        {"spu": spu.id, "color_codes": ["off"], "spec_values": {}},
    )
    assert inactive.status_code == 400

    invalid_unit = _post(
        client,
        user,
        {"spu": spu.id, "color_codes": ["red"], "spec_values": {"size": ["180cm", "S"]}},
    )
    assert invalid_unit.status_code in {400, 422}

    long_spu = ProductSPU.objects.create(
        tenant=tenant,
        spu_code="X" * 79,
        product_name="超长编码商品",
        category_node=category,
    )
    too_long = _post(
        client,
        user,
        {"spu": long_spu.id, "color_codes": ["red"], "spec_values": {}},
    )
    assert too_long.status_code == 400


@pytest.mark.django_db
def test_batch_accepts_production_string_dictionary_values_without_units():
    client, user, tenant, category, spu = _client_and_spu(
        suffix="101011001",
        dimensions=[
            {
                "code": "spec",
                "name": "规格",
                "values": ["90X200CM", "120X200CM", "2PCS-1"],
            }
        ],
    )
    spu.spu_code = "101011001"
    spu.save(update_fields=["spu_code"])
    for code in ("amber", "apricot", "apricotpink"):
        ProductColor.objects.create(tenant=tenant, code=code, name=code)

    invalid = _post(
        client,
        user,
        {
            "spu": spu.id,
            "color_codes": ["amber"],
            "spec_values": {"spec": ["NOT-A-SPEC"]},
        },
    )
    assert invalid.status_code == 422
    assert ProductSKU.objects.filter(tenant=tenant, spu=spu).count() == 0

    response = _post(
        client,
        user,
        {
            "spu": spu.id,
            "color_codes": ["amber", "apricot", "apricotpink"],
            "spec_values": {"spec": ["90X200CM", "2PCS-1"]},
        },
    )
    assert response.status_code == 201, response.json()
    data = response.json()["data"]
    assert data["created"] == 6
    assert data["skipped"] == 0
    assert data["total"] == 6
    assert {
        sku.sku_code
        for sku in ProductSKU.objects.filter(tenant=tenant, spu=spu)
    } == {
        f"101011001-{color}-{spec}"
        for color in ("amber", "apricot", "apricotpink")
        for spec in ("90X200CM", "2PCS-1")
    }

    retry = _post(
        client,
        user,
        {
            "spu": spu.id,
            "color_codes": ["amber", "apricot", "apricotpink"],
            "spec_values": {"spec": ["90X200CM", "2PCS-1"]},
        },
    )
    assert retry.status_code == 200, retry.json()
    assert retry.json()["data"]["created"] == 0
    assert retry.json()["data"]["skipped"] == 6
    assert retry.json()["data"]["total"] == 6
    assert ProductSKU.objects.filter(tenant=tenant, spu=spu).count() == 6
