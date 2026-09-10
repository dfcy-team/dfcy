from decimal import Decimal

import pytest
from django.db import transaction
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.import_service import ImportRowError, _active_categories, _resolve_category
from apps.products.models import ProductCategory, ProductColor, ProductLegacyItem, ProductSKU, ProductSPU
from apps.tenants.models import Tenant


def _user(tenant, suffix="user"):
    user = CustomUser.objects.create_user(
        username=f"legacy-import-{tenant.code}-{suffix}",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    role = Role.objects.create(tenant=tenant, code=f"legacy-import-role-{tenant.code}-{suffix}", name="Legacy import")
    role.permissions.add(*Permission.objects.filter(code__in=["products.master.view", "products.master.manage"]))
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})
    return user


def _client(tenant, suffix="user"):
    client = APIClient()
    client.force_authenticate(user=_user(tenant, suffix))
    return client


@pytest.mark.django_db
def test_import_create_update_sparse_columns_and_modes():
    tenant = Tenant.objects.create(name="Import v2 tenant", code="import-v2")
    client = _client(tenant)

    created = client.post(
        "/api/internal/products/legacy-items/",
        {
            "mode": "create",
            "csv_text": (
                "旧SKU编码,商品名称,采购价格,重量(g),体积(m³),原产国\n"
                "OLD-V2-001,Imported V2,12.5000,1.250,0.123456,CN\n"
            ),
        },
        format="json",
    )
    assert created.status_code == 201
    assert created.json()["data"]["created"] == 1
    item = ProductLegacyItem.objects.get(tenant=tenant, legacy_sku_code="OLD-V2-001")
    assert item.product_name == "Imported V2"
    assert item.purchase_price == Decimal("12.5000")
    assert item.package_volume == Decimal("0.123456")

    updated = client.post(
        "/api/internal/products/legacy-items/",
        {
            "mode": "update",
            "csv_text": "旧SKU编码,采购价格,商品描述\nOLD-V2-001,13.2500,partial update\n",
        },
        format="json",
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["updated"] == 1
    item.refresh_from_db()
    assert item.purchase_price == Decimal("13.2500")
    assert item.product_name == "Imported V2"
    assert item.package_weight == Decimal("1.250")
    assert item.product_description == "partial update"

    rejected_create = client.post(
        "/api/internal/products/legacy-items/",
        {
            "mode": "create",
            "csv_text": "旧SKU编码,商品名称\nOLD-V2-001,Should not replace\n",
        },
        format="json",
    )
    assert rejected_create.status_code == 200
    assert rejected_create.json()["data"]["created"] == 0
    assert rejected_create.json()["data"]["error_count"] == 1
    item.refresh_from_db()
    assert item.product_name == "Imported V2"


@pytest.mark.django_db
def test_create_import_without_legacy_codes_returns_id_and_generates_compatible_empty_code():
    tenant = Tenant.objects.create(name="Import optional codes", code="import-optional")
    client = _client(tenant)
    l1 = ProductCategory.objects.create(tenant=tenant, level=1, code="1", name="Home")
    l2 = ProductCategory.objects.create(tenant=tenant, parent=l1, level=2, code="01", name="Bedding")
    ProductCategory.objects.create(
        tenant=tenant,
        parent=l2,
        level=3,
        code="08",
        name="Mattress",
        spec_dimensions=[{"code": "spec", "name": "Specification", "values": ["150cm"]}],
    )
    ProductColor.objects.create(tenant=tenant, code="noc", name="No color")

    response = client.post(
        "/api/internal/products/legacy-items/",
        {
            "mode": "create",
            "csv_text": (
                "旧SPU编码,旧SKU编码,商品名称,完整类目编码,属性编码,颜色英文编码,规格\n"
                ",,Anonymous imported product,10108,1,noc,150cm\n"
            ),
        },
        format="json",
    )

    assert response.status_code == 201
    payload = response.json()["data"]
    assert payload["created"] == 1
    assert len(payload["created_ids"]) == 1
    item = ProductLegacyItem.objects.get(pk=payload["created_ids"][0], tenant=tenant)
    assert item.legacy_spu_code == ""
    assert item.legacy_sku_code is None

    generated = client.post(f"/api/internal/products/legacy-items/{item.id}/generate/", format="json")

    assert generated.status_code == 200
    assert generated.json()["data"]["legacy_sku_code"] == ""
    item.refresh_from_db()
    assert item.generated_sku.legacy_sku_code == ""

    retried = client.post(f"/api/internal/products/legacy-items/{item.id}/generate/", format="json")
    assert retried.status_code == 200
    assert retried.json()["data"]["legacy_sku_code"] == ""


@pytest.mark.django_db
def test_auto_and_update_imports_still_require_a_sku_key():
    tenant = Tenant.objects.create(name="Import keyed modes", code="import-keyed")
    client = _client(tenant)

    for mode in ("auto", "update"):
        response = client.post(
            "/api/internal/products/legacy-items/",
            {"mode": mode, "csv_text": "旧SKU编码,商品名称\n,No key\n"},
            format="json",
        )
        assert response.status_code == 200
        assert response.json()["data"]["created"] == 0
        assert response.json()["data"]["error_count"] == 1

    assert not ProductLegacyItem.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db(transaction=True)
def test_stale_category_cache_rechecks_active_parent_inside_row_transaction():
    tenant = Tenant.objects.create(name="Import category race", code="import-category-race")
    l1 = ProductCategory.objects.create(tenant=tenant, level=1, code="1", name="Home")
    l2 = ProductCategory.objects.create(tenant=tenant, parent=l1, level=2, code="01", name="Bedding")
    l3 = ProductCategory.objects.create(tenant=tenant, parent=l2, level=3, code="08", name="Mattress")
    cached = _active_categories(tenant)
    ProductCategory.objects.filter(pk=l2.pk).update(is_active=False)

    with transaction.atomic(), pytest.raises(ImportRowError, match="未找到有效的完整类目编码"):
        _resolve_category(cached, "10108")


@pytest.mark.django_db(transaction=True)
def test_stale_category_cache_rechecks_composite_code_after_category_move():
    tenant = Tenant.objects.create(name="Import category move", code="import-category-move")
    l1 = ProductCategory.objects.create(tenant=tenant, level=1, code="1", name="Home")
    other_l1 = ProductCategory.objects.create(tenant=tenant, level=1, code="2", name="Other")
    l2 = ProductCategory.objects.create(tenant=tenant, parent=l1, level=2, code="01", name="Bedding")
    ProductCategory.objects.create(tenant=tenant, parent=l2, level=3, code="08", name="Mattress")
    cached = _active_categories(tenant)
    ProductCategory.objects.filter(pk=l2.pk).update(parent=other_l1)

    with transaction.atomic(), pytest.raises(ImportRowError, match="未找到有效的完整类目编码"):
        _resolve_category(cached, "10108")


@pytest.mark.django_db
def test_generate_rechecks_locked_category_parent_is_active():
    tenant = Tenant.objects.create(name="Generate category race", code="generate-category-race")
    client = _client(tenant)
    l1 = ProductCategory.objects.create(tenant=tenant, level=1, code="1", name="Home")
    l2 = ProductCategory.objects.create(tenant=tenant, parent=l1, level=2, code="01", name="Bedding")
    l3 = ProductCategory.objects.create(tenant=tenant, parent=l2, level=3, code="08", name="Mattress")
    item = ProductLegacyItem.objects.create(
        tenant=tenant,
        legacy_sku_code=None,
        product_name="Blocked generation",
        category_node=l3,
        color_code="noc",
        specification="150cm",
    )
    ProductCategory.objects.filter(pk=l2.pk).update(is_active=False)

    response = client.post(f"/api/internal/products/legacy-items/{item.id}/generate/", format="json")

    assert response.status_code == 400
    assert not ProductSKU.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db
def test_import_new_sku_exact_update_and_unmatched_code_never_creates_legacy():
    tenant = Tenant.objects.create(name="New SKU import tenant", code="new-sku-import")
    client = _client(tenant)
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-V2", product_name="Base")
    sku = ProductSKU.objects.create(
        tenant=tenant,
        spu=spu,
        sku_code="SKU-V2-001",
        product_name="Before",
        purchase_price=Decimal("5.0000"),
        is_active=True,
    )

    updated = client.post(
        "/api/internal/products/legacy-items/",
        {
            "mode": "update",
            "csv_text": "新SKU编码,商品名称,采购价格,商品状态\nSKU-V2-001,After,6.2500,下架\n",
        },
        format="json",
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["updated"] == 1
    sku.refresh_from_db()
    assert sku.product_name == "After"
    assert sku.purchase_price == Decimal("6.2500")
    assert sku.is_active is False
    assert not ProductLegacyItem.objects.filter(tenant=tenant).exists()

    unmatched = client.post(
        "/api/internal/products/legacy-items/",
        {
            "mode": "auto",
            "csv_text": "新SKU编码,商品名称\nSKU-DOES-NOT-EXIST,Must not stage\n",
        },
        format="json",
    )
    assert unmatched.status_code == 200
    assert unmatched.json()["data"]["skipped"] == 1
    assert ProductLegacyItem.objects.filter(tenant=tenant).count() == 0


@pytest.mark.django_db
def test_import_rejects_mismatched_keys_and_keeps_invalid_row_atomic():
    tenant = Tenant.objects.create(name="Atomic import tenant", code="atomic-import")
    client = _client(tenant)
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-ATOMIC", product_name="Base")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="SKU-ATOMIC", product_name="SKU")
    ProductLegacyItem.objects.create(
        tenant=tenant,
        legacy_sku_code="OLD-ATOMIC",
        product_name="Mapped",
        status=ProductLegacyItem.Status.GENERATED,
        generated_spu=spu,
        generated_sku=sku,
    )

    mismatch = client.post(
        "/api/internal/products/legacy-items/",
        {
            "mode": "update",
            "csv_text": "旧SKU编码,新SKU编码,商品名称\nOLD-ATOMIC,SKU-NOT-MAPPED,Should fail\n",
        },
        format="json",
    )
    assert mismatch.json()["data"]["error_count"] == 1
    sku.refresh_from_db()
    assert sku.product_name == "SKU"

    result = client.post(
        "/api/internal/products/legacy-items/",
        {
            "mode": "auto",
            "csv_text": (
                "旧SKU编码,商品名称,采购价格\n"
                "OLD-ATOMIC-VALID,Valid,1.0000\n"
                "OLD-ATOMIC-BAD,Bad,12.34567\n"
            ),
        },
        format="json",
    )
    data = result.json()["data"]
    assert data["created"] == 1
    assert data["skipped"] == 1
    assert ProductLegacyItem.objects.filter(tenant=tenant, legacy_sku_code="OLD-ATOMIC-VALID").exists()
    assert not ProductLegacyItem.objects.filter(tenant=tenant, legacy_sku_code="OLD-ATOMIC-BAD").exists()


@pytest.mark.django_db
def test_import_does_not_cross_tenant_on_new_sku_lookup():
    tenant_a = Tenant.objects.create(name="Import tenant A", code="import-a")
    tenant_b = Tenant.objects.create(name="Import tenant B", code="import-b")
    spu = ProductSPU.objects.create(tenant=tenant_a, spu_code="SPU-A", product_name="A")
    ProductSKU.objects.create(tenant=tenant_a, spu=spu, sku_code="SKU-CROSS", product_name="Keep")

    client = _client(tenant_b)
    response = client.post(
        "/api/internal/products/legacy-items/",
        {"mode": "update", "csv_text": "新SKU编码,商品名称\nSKU-CROSS,Should not cross\n"},
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["data"]["skipped"] == 1
    assert not ProductLegacyItem.objects.filter(tenant=tenant_b).exists()
    assert ProductSKU.objects.get(tenant=tenant_a, sku_code="SKU-CROSS").product_name == "Keep"


@pytest.mark.django_db
def test_import_old_sku_updates_standalone_sku_without_creating_pending_bridge():
    tenant = Tenant.objects.create(name="Standalone old SKU tenant", code="standalone-old")
    client = _client(tenant)
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-STANDALONE", product_name="Base")
    sku = ProductSKU.objects.create(
        tenant=tenant,
        spu=spu,
        sku_code="SKU-STANDALONE",
        legacy_sku_code="OLD-STANDALONE",
        product_name="Before",
        purchase_price=Decimal("5.0000"),
    )

    response = client.post(
        "/api/internal/products/legacy-items/",
        {
            "mode": "update",
            "csv_text": "旧SKU编码,商品名称,采购价格\nOLD-STANDALONE,After,6.2500\n",
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["data"]["updated"] == 1
    sku.refresh_from_db()
    assert sku.product_name == "After"
    assert sku.purchase_price == Decimal("6.2500")
    assert not ProductLegacyItem.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db
def test_import_rejects_wrong_old_code_when_new_sku_bridge_exists():
    tenant = Tenant.objects.create(name="Bridge key tenant", code="bridge-key")
    client = _client(tenant)
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-BRIDGE", product_name="Base")
    sku = ProductSKU.objects.create(
        tenant=tenant,
        spu=spu,
        sku_code="SKU-BRIDGE",
        product_name="Before",
    )
    bridge = ProductLegacyItem.objects.create(
        tenant=tenant,
        legacy_sku_code="OLD-BRIDGE",
        product_name="Before",
        status=ProductLegacyItem.Status.GENERATED,
        generated_spu=spu,
        generated_sku=sku,
    )

    response = client.post(
        "/api/internal/products/legacy-items/",
        {
            "mode": "update",
            "csv_text": "旧SKU编码,新SKU编码,商品名称\nOLD-WRONG,SKU-BRIDGE,Should fail\n",
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["data"]["error_count"] == 1
    sku.refresh_from_db()
    bridge.refresh_from_db()
    assert sku.product_name == "Before"
    assert bridge.product_name == "Before"


@pytest.mark.django_db
def test_import_rejects_ambiguous_old_sku_code():
    tenant = Tenant.objects.create(name="Ambiguous old SKU tenant", code="ambiguous-old")
    client = _client(tenant)
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-AMBIGUOUS", product_name="Base")
    ProductSKU.objects.create(
        tenant=tenant,
        spu=spu,
        sku_code="SKU-AMBIGUOUS-1",
        legacy_sku_code="OLD-AMBIGUOUS",
        product_name="Keep one",
    )
    ProductSKU.objects.create(
        tenant=tenant,
        spu=spu,
        sku_code="SKU-AMBIGUOUS-2",
        legacy_sku_code="OLD-AMBIGUOUS",
        product_name="Keep two",
    )

    response = client.post(
        "/api/internal/products/legacy-items/",
        {
            "mode": "update",
            "csv_text": "旧SKU编码,商品名称\nOLD-AMBIGUOUS,Should fail\n",
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["data"]["error_count"] == 1
    assert not ProductLegacyItem.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db
def test_import_rejects_status_for_new_pending_legacy_row():
    tenant = Tenant.objects.create(name="Pending status tenant", code="pending-status")
    client = _client(tenant)

    response = client.post(
        "/api/internal/products/legacy-items/",
        {
            "mode": "create",
            "csv_text": "旧SKU编码,商品名称,商品状态\nOLD-PENDING,Pending,下架\n",
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["data"]["error_count"] == 1
    assert not ProductLegacyItem.objects.filter(tenant=tenant, legacy_sku_code="OLD-PENDING").exists()


@pytest.mark.django_db
def test_import_rejects_repeated_old_or_new_keys_within_one_csv():
    tenant = Tenant.objects.create(name="Duplicate import tenant", code="duplicate-import")
    client = _client(tenant)
    response = client.post(
        "/api/internal/products/legacy-items/",
        {
            "mode": "auto",
            "csv_text": (
                "旧SKU编码,商品名称\n"
                "OLD-DUP,First\n"
                "OLD-DUP,Second\n"
            ),
        },
        format="json",
    )
    data = response.json()["data"]
    assert data["created"] == 1
    assert data["skipped"] == 1
    assert ProductLegacyItem.objects.filter(tenant=tenant, legacy_sku_code="OLD-DUP").count() == 1
