import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.models import ProductBundleComponent, ProductSKU, ProductSPU
from apps.products.models import ProductCategory, ProductColor, ProductLegacyItem
from apps.tenants.models import Tenant


def _bundle_client(tenant, username):
    user = CustomUser.objects.create_user(username=username, tenant=tenant, user_type=CustomUser.UserType.INTERNAL)
    role = Role.objects.create(tenant=tenant, code=f"{username}-role", name="Bundle user")
    for code in ("products.bundle.view", "products.bundle.manage"):
        permission, _ = Permission.objects.get_or_create(code=code, defaults={"name": code, "module": "products", "action": code.rsplit(".", 1)[-1]})
        role.permissions.add(permission)
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _manager(tenant, username):
    user = CustomUser.objects.create_user(username=username, tenant=tenant, user_type=CustomUser.UserType.INTERNAL)
    role = Role.objects.create(tenant=tenant, code=f"{username}-role", name="Product manager")
    for code in ("products.master.view", "products.master.manage"):
        permission, _ = Permission.objects.get_or_create(code=code, defaults={"name": code, "module": "products", "action": code.rsplit(".", 1)[-1]})
        role.permissions.add(permission)
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})
    return user


def _leaf_category(tenant):
    first = ProductCategory.objects.create(tenant=tenant, level=1, code="1", name="Home")
    second = ProductCategory.objects.create(tenant=tenant, parent=first, level=2, code="01", name="Bedding")
    return ProductCategory.objects.create(tenant=tenant, parent=second, level=3, code="08", name="Mattress", spec_dimensions=[])


@pytest.mark.django_db
def test_one_spu_can_have_standard_and_bundle_skus_and_bom_component():
    tenant = Tenant.objects.create(name="Mixed SKU tenant", code="mixed-sku")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="MIXED-SPU", product_name="混合")
    standard = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="MIXED-STD", product_type="standard")
    bundle = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="MIXED-BUNDLE", product_type="bundle")

    ProductBundleComponent.objects.create(
        tenant=tenant, bundle_sku=bundle, component_sku=standard, quantity=1,
    )
    assert standard.product_type == "standard"
    assert bundle.product_type == "bundle"


@pytest.mark.django_db
def test_bundle_cannot_be_component_and_sku_type_survives_spu_change():
    tenant = Tenant.objects.create(name="Nested SKU tenant", code="nested-sku")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="NEST-SPU", product_name="普通SPU")
    other_spu = ProductSPU.objects.create(
        tenant=tenant, spu_code="OTHER-SPU", product_name="组合SPU", product_type="bundle",
    )
    bundle = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="OUTER", product_type="bundle")
    nested = ProductSKU.objects.create(tenant=tenant, spu=other_spu, sku_code="INNER", product_type="bundle")
    with pytest.raises(ValidationError):
        ProductBundleComponent.objects.create(
            tenant=tenant, bundle_sku=bundle, component_sku=nested, quantity=1,
        )

    bundle.spu = other_spu
    bundle.save(update_fields=["spu"])
    bundle.refresh_from_db()
    assert bundle.product_type == "bundle"


@pytest.mark.django_db
def test_legacy_direct_sku_creation_inherits_spu_type():
    tenant = Tenant.objects.create(name="Legacy SKU tenant", code="legacy-sku")
    spu = ProductSPU.objects.create(
        tenant=tenant, spu_code="LEGACY-SPU", product_name="组合默认", product_type="bundle",
    )
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="LEGACY-SKU")
    assert sku.product_type == "bundle"


@pytest.mark.django_db
def test_bundle_create_on_standard_spu_and_standard_sku_component():
    from tests.test_product_bundle_create_atomic import _catalog, _payload

    tenant = Tenant.objects.create(name="Mixed API", code="mixed-api-create")
    client = _bundle_client(tenant, "mixed-api-create-user")
    category = _catalog(tenant, "混合")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="MIXED-API-SPU", product_name="普通SPU", category_node=category)
    standard = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="MIXED-API-STD", product_name="标准SKU")
    payload = _payload(category, [standard])
    payload.update(spu_mode="existing", existing_spu=spu.id)
    created = client.post("/api/internal/products/bundles/create/", payload, format="json")
    assert created.status_code == 201
    data = created.json()["data"]
    assert data["spu"]["id"] == spu.id and data["spu"]["product_type"] == "standard"
    assert data["sku"]["product_type"] == "bundle"
    assert ProductBundleComponent.objects.get(bundle_sku_id=data["sku"]["id"]).component_sku_id == standard.id


@pytest.mark.django_db
def test_legacy_generate_on_bundle_target_spu_stays_standard_and_list_uses_sku_type():
    tenant = Tenant.objects.create(name="Mixed legacy", code="mixed-legacy-api")
    user = _manager(tenant, "mixed-legacy-api-user")
    category = _leaf_category(tenant)
    ProductColor.objects.create(tenant=tenant, code="noc", name="No color")
    target = ProductSPU.objects.create(tenant=tenant, spu_code="TARGET-BUNDLE", product_name="目标组合", product_type="bundle", category_node=category, season_code="1")
    item = ProductLegacyItem.objects.create(tenant=tenant, legacy_spu_code="OLD-MIXED", legacy_sku_code="OLD-MIXED-1", product_name="Imported", category_node=category, attribute_code="1", color_code="noc", specification="", target_spu=target)
    client = APIClient()
    client.force_authenticate(user=user)
    generated = client.post(f"/api/internal/products/legacy-items/{item.id}/generate/", format="json")
    assert generated.status_code == 200
    item.refresh_from_db()
    assert item.generated_sku.product_type == "standard"
    details = client.get("/api/internal/products/details/")
    assert details.status_code == 200
    rows = details.json()["data"]["results"]
    row = next(row for row in rows if row.get("sku_id") == item.generated_sku_id or row.get("id") == item.generated_sku_id)
    assert row["product_type"] == "standard"


@pytest.mark.django_db
def test_bundle_only_user_cannot_see_standard_skus_on_bundle_spu_or_legacy_rows():
    tenant = Tenant.objects.create(name="Mixed visibility", code="mixed-visibility")
    client = _bundle_client(tenant, "mixed-visibility-user")
    category = _leaf_category(tenant)
    bundle_spu = ProductSPU.objects.create(tenant=tenant, spu_code="VIS-BUNDLE-SPU", product_name="Bundle", product_type="bundle", category_node=category)
    standard = ProductSKU.objects.create(tenant=tenant, spu=bundle_spu, sku_code="VIS-STD", product_type="standard")
    ProductLegacyItem.objects.create(tenant=tenant, legacy_spu_code="LEG-1", legacy_sku_code="LEG-1-1", product_name="Legacy generated", category_node=category, generated_sku=standard, generated_spu=bundle_spu)
    ProductLegacyItem.objects.create(tenant=tenant, legacy_spu_code="LEG-2", legacy_sku_code="LEG-2-1", product_name="Legacy target", category_node=category, target_spu=bundle_spu)
    details = client.get("/api/internal/products/details/")
    assert details.status_code == 200
    assert "VIS-STD" not in str(details.json())
    assert "LEG-1-1" not in str(details.json()) and "LEG-2-1" not in str(details.json())
    options = client.get(f"/api/internal/products/skus/{standard.id}/identity/options/")
    assert options.status_code == 404


@pytest.mark.django_db
def test_product_type_migration_function_backfills_existing_sqlite_rows_without_touching_bom():
    from importlib import import_module

    copy_spu_product_type = import_module("apps.products.migrations.0030_productsku_product_type").copy_spu_product_type
    tenant = Tenant.objects.create(name="Mixed migration", code="mixed-migration")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="MIG-BUNDLE", product_name="Bundle", product_type="bundle")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="MIG-SKU", product_type="standard")
    normal_spu = ProductSPU.objects.create(tenant=tenant, spu_code="MIG-STD", product_name="Standard")
    normal = ProductSKU.objects.create(tenant=tenant, spu=normal_spu, sku_code="MIG-STD-SKU")
    sku.product_type = "bundle"
    sku.save(update_fields=["product_type"])
    relation = ProductBundleComponent.objects.create(tenant=tenant, bundle_sku=sku, component_sku=normal, quantity=2)
    before = list(ProductSKU.objects.filter(tenant=tenant).values("pk", "spu_id", "sku_code", "legacy_sku_code"))
    bom_before = ProductBundleComponent.objects.values().get(pk=relation.pk)
    ProductSKU.objects.filter(pk=normal.pk).update(product_type="")
    # Exercise the migration function against the live SQLite tables via historical model state.
    ProductSKU.objects.filter(pk=sku.pk).update(product_type="")
    class Apps:
        @staticmethod
        def get_model(app_label, model_name):
            return {"ProductSKU": ProductSKU, "ProductSPU": ProductSPU}[model_name]
    copy_spu_product_type(Apps(), type("Editor", (), {"connection": connection})())
    sku.refresh_from_db()
    assert sku.product_type == "bundle"
    normal.refresh_from_db()
    assert normal.product_type == "standard"
    assert list(ProductSKU.objects.filter(tenant=tenant).values("pk", "spu_id", "sku_code", "legacy_sku_code")) == before
    assert ProductBundleComponent.objects.values().get(pk=relation.pk) == bom_before
