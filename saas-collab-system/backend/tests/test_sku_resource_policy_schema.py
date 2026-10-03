import pytest
from django.core.exceptions import ValidationError

from apps.permissions.models import Permission
from apps.permissions.resource_policies import RESOURCE_DEFINITIONS, permission_resource, validate_resource_policy
from apps.products.models import ProductSKU, ProductSPU
from apps.tenants.models import Tenant

pytestmark = pytest.mark.django_db


def test_sku_reporting_resources_are_registered_with_bounded_dimensions():
    expected = {
        "products.master": ("商品主数据", ["sku_ids", "spu_ids"], ["products.master."]),
        "products.cost": ("商品成本", ["sku_ids", "spu_ids", "warehouse_ids"], ["products.cost."]),
        "sales_management.sales": ("销售商品数据", ["store_ids"], ["sales_management."]),
        "commerce.inventory": ("库存商品数据", ["warehouse_ids", "sku_ids", "spu_ids"], []),
    }
    for code, (name, dimensions, prefixes) in expected.items():
        assert RESOURCE_DEFINITIONS[code] == {"name": name, "dimensions": dimensions, "prefixes": prefixes}
    assert permission_resource("products.master.view") == "products.master"
    assert permission_resource("products.cost.view") == "products.cost"
    assert permission_resource("sales_management.sales.view") == "sales_management.sales"
    # Inventory shares the contextual analytics/sales adapter and has no permission prefix.
    assert permission_resource("commerce.inventory.view") is None
    assert RESOURCE_DEFINITIONS["platform_product_details"] == {
        "name": "平台商品明细", "dimensions": ["platform_ids", "site_ids", "store_ids"],
        "prefixes": ["listings.product_detail."],
    }
    assert RESOURCE_DEFINITIONS["integrations.product_mapping"] == {
        "name": "平台商品映射数据", "dimensions": ["platform_ids", "store_ids"], "prefixes": [],
    }
    assert permission_resource("integrations.product_mapping.view") is None


def test_sku_and_spu_ids_validate_only_inside_the_target_tenant():
    tenant = Tenant.objects.create(name="SKU policy", code="sku-policy")
    foreign = Tenant.objects.create(name="Foreign SKU policy", code="foreign-sku-policy")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-1", product_name="Product")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="SKU-1")
    foreign_spu = ProductSPU.objects.create(tenant=foreign, spu_code="SPU-2", product_name="Foreign")
    foreign_sku = ProductSKU.objects.create(tenant=foreign, spu=foreign_spu, sku_code="SKU-2")

    assert validate_resource_policy(tenant.pk, "products.master", "custom", {
        "sku_ids": [sku.pk], "spu_ids": [spu.pk],
    }) == {"sku_ids": [sku.pk], "spu_ids": [spu.pk]}
    for key, object_id in (("sku_ids", foreign_sku.pk), ("spu_ids", foreign_spu.pk)):
        with pytest.raises(ValidationError, match="其他租户"):
            validate_resource_policy(tenant.pk, "products.master", "custom", {key: [object_id]})


def test_registered_resource_dimensions_reject_unsupported_ids_and_do_not_grant_permissions():
    tenant = Tenant.objects.create(name="Policy dimensions", code="policy-dimensions")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-3", product_name="Product")
    ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="SKU-3")
    before = set(Permission.objects.values_list("code", flat=True))
    with pytest.raises(ValidationError, match="不支持范围字段"):
        validate_resource_policy(tenant.pk, "products.master", "custom", {"warehouse_ids": [1]})
    with pytest.raises(ValidationError, match="不支持范围字段"):
        validate_resource_policy(tenant.pk, "sales_management.sales", "custom", {"sku_ids": [1]})
    with pytest.raises(ValidationError, match="不支持范围字段"):
        validate_resource_policy(tenant.pk, "sales_management.sales", "custom", {"spu_ids": [1]})
    with pytest.raises(ValidationError, match="不存在或其他租户"):
        validate_resource_policy(tenant.pk, "products.master", "custom", {"sku_ids": [999999]})
    assert set(Permission.objects.values_list("code", flat=True)) == before
