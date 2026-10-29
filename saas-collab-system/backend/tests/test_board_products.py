import pytest
from django.db import connection

from apps.commerce.models import SalesOrderItem
from apps.products.models import ProductCategory, ProductSKU, ProductSPU
from apps.masterdata.models import StoreMaster
from apps.tenants.models import Tenant

from tests.test_sales_realtime_board import DAY, URL, _fixture, _order


@pytest.mark.django_db
def test_product_rankings_use_safe_store_keys_system_ids_category_and_valid_sales():
    user, tenant, platform, store, run, client = _fixture("board-product-dimensions")
    other_store = StoreMaster.objects.create(
        tenant=tenant, platform=platform, code="other", name="Other", country_code="PH",
        currency="PHP", timezone="Asia/Manila",
    )
    root = ProductCategory.objects.create(tenant=tenant, level=1, code="1", name="Home")
    leaf = ProductCategory.objects.create(tenant=tenant, parent=root, level=2, code="01", name="Kitchen")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-A", product_name="Pot", category_node=leaf)
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="SKU-A", product_name="Pot Red", inventory_type="physical")

    first = _order(tenant, platform, store, run, "one", amount="30")
    second = _order(tenant, platform, store, run, "two", amount="20")
    other = _order(tenant, platform, other_store, run, "other", amount="10")
    cancelled = _order(tenant, platform, store, run, "cancel", amount="900", status="cancelled")
    thb = _order(tenant, platform, store, run, "thb", currency="THB", amount="7")
    for order, variant in ((first, "red"), (second, "blue"), (other, "red"), (cancelled, "red"), (thb, "red")):
        SalesOrderItem.objects.filter(sales_order=order).update(
            internal_sku=sku, internal_spu=None, platform_product_id="same-product",
            platform_variant_id=variant,
        )

    data = client.get(URL, {"date_from": DAY, "date_to": DAY}).json()["data"]
    group = next(row for row in data["currency_groups"] if row["currency"] == "PHP")
    rankings = group["product_rankings"]
    assert len(rankings["store_spu"]["sales_amount"]) == 2  # same product ID, distinct stores
    assert len(rankings["store_sku"]["sales_amount"]) == 3  # two variants plus second store
    assert rankings["product_spu"]["sales_amount"][0]["key"] == f"spu:{spu.id}"
    assert rankings["product_spu"]["sales_amount"][0]["sales_amount"] == "60"
    assert rankings["product_sku"]["sales_amount"][0]["key"] == f"sku:{sku.id}"
    category = rankings["category"]["sales_amount"][0]
    assert category["key"] == f"category:{leaf.id}"
    assert category["name"] == "Home/Kitchen"
    assert all("inventory" in row for row in rankings["product_sku"]["sales_amount"])
    thb_group = next(row for row in data["currency_groups"] if row["currency"] == "THB")
    assert thb_group["product_rankings"]["product_sku"]["sales_amount"][0]["sales_amount"] == "7"
    scoped = client.get(URL, {"date_from": DAY, "date_to": DAY, "store_id": store.id, "currency": "PHP"}).json()["data"]
    scoped_keys = {row["key"] for row in scoped["currency_groups"][0]["product_rankings"]["store_spu"]["sales_amount"]}
    assert scoped_keys == {f"store:{store.id}:p:12:same-product"}


@pytest.mark.django_db
def test_product_rankings_distinguish_unmapped_and_unclassified_and_bound_top_ten():
    user, tenant, platform, store, run, client = _fixture("board-product-buckets")
    for index in range(12):
        _order(tenant, platform, store, run, f"rank-{index}", amount=str(20 - index))
    _order(tenant, platform, store, run, "unmapped", amount="1")
    data = client.get(URL, {"date_from": DAY, "date_to": DAY}).json()["data"]
    group = data["currency_groups"][0]
    assert len(group["product_rankings"]["store_sku"]["sales_amount"]) == 10
    category_keys = {row["key"] for row in group["product_rankings"]["category"]["sales_amount"]}
    assert "unmapped" not in category_keys
    assert all(row["mapping_status"] == "unmapped" for row in group["product_rankings"]["product_spu"]["sales_amount"])
    assert all(row["mapping_status"] == "unmapped" for row in group["product_rankings"]["product_sku"]["sales_amount"])
    assert "未映射商品按店铺及平台商品身份单列" in group["product_mapping_note"]
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="NO-CAT", product_name="No category")
    order = _order(tenant, platform, store, run, "unclassified", amount="2")
    SalesOrderItem.objects.filter(sales_order=order).update(internal_spu=spu)
    data = client.get(URL, {"date_from": DAY, "date_to": DAY}).json()["data"]
    category_keys = {row["key"] for row in data["currency_groups"][0]["product_rankings"]["category"]["sales_amount"]}
    assert "unclassified" in category_keys


@pytest.mark.django_db
def test_product_sku_units_ranking_includes_high_volume_outside_sales_top_ten():
    user, tenant, platform, store, run, client = _fixture("board-product-volume")
    orders = []
    for index in range(12):
        order = _order(tenant, platform, store, run, f"volume-{index}", amount=str(30 - index))
        spu = ProductSPU.objects.create(tenant=tenant, spu_code=f"VOL-SPU-{index}", product_name=f"Volume {index}")
        sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code=f"VOL-SKU-{index}")
        SalesOrderItem.objects.filter(sales_order=order).update(internal_sku=sku, platform_product_id=f"product-{index}", platform_variant_id=f"variant-{index}")
        orders.append(order)
    low_order = _order(tenant, platform, store, run, "volume-low", amount="1")
    low_spu = ProductSPU.objects.create(tenant=tenant, spu_code="VOL-SPU-LOW", product_name="High volume")
    low_sku = ProductSKU.objects.create(tenant=tenant, spu=low_spu, sku_code="VOL-SKU-LOW")
    SalesOrderItem.objects.filter(sales_order=low_order).update(
        internal_sku=low_sku, platform_product_id="product-low", platform_variant_id="variant-low", quantity=500,
    )

    group = client.get(URL, {"date_from": DAY, "date_to": DAY}).json()["data"]["currency_groups"][0]
    sales_keys = {row["key"] for row in group["product_rankings"]["product_sku"]["sales_amount"]}
    units_rows = group["product_rankings"]["product_sku"]["units_sold"]
    units_by_key = {row["key"]: row for row in units_rows}
    assert f"sku:{low_sku.id}" not in sales_keys
    assert f"sku:{low_sku.id}" in units_by_key
    assert units_by_key[f"sku:{low_sku.id}"]["units_sold"] == 500


@pytest.mark.django_db
def test_store_variant_mapping_multiple_internal_skus_has_no_inventory_or_drill():
    user, tenant, platform, store, run, client = _fixture("board-product-ambiguous-sku")
    spus = [ProductSPU.objects.create(tenant=tenant, spu_code=f"AMB-SPU-{i}", product_name=f"Ambiguous {i}") for i in (1, 2)]
    skus = [ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code=f"AMB-SKU-{index}") for index, spu in enumerate(spus, 1)]
    for index, sku in enumerate(skus, 1):
        order = _order(tenant, platform, store, run, f"amb-{index}", amount="10")
        SalesOrderItem.objects.filter(sales_order=order).update(
            internal_sku=sku, platform_product_id="shared-product", platform_variant_id="shared-variant",
        )

    group = client.get(URL, {"date_from": DAY, "date_to": DAY}).json()["data"]["currency_groups"][0]
    row = next(row for row in group["product_rankings"]["store_sku"]["sales_amount"] if "shared-product" in row["key"])
    assert "internal_sku_id" not in row
    assert "drill_internal_sku_id" not in row
    assert row["inventory"]["available_qty"] is None


@pytest.mark.django_db
def test_foreign_category_links_collapse_into_masked_unmapped_bucket():
    user, tenant, platform, store, run, client = _fixture("board-product-foreign-category")
    foreign = Tenant.objects.create(name="foreign-categories", code="foreign-categories")
    category_a = ProductCategory.objects.create(tenant=foreign, level=1, code="1", name="Secret A")
    category_b = ProductCategory.objects.create(tenant=foreign, level=1, code="2", name="Secret B")
    spu_a = ProductSPU.objects.create(tenant=foreign, spu_code="FOREIGN-A", product_name="Foreign A", category_node=category_a)
    spu_b = ProductSPU.objects.create(tenant=foreign, spu_code="FOREIGN-B", product_name="Foreign B", category_node=category_b)
    for index, spu in enumerate((spu_a, spu_b), 1):
        order = _order(tenant, platform, store, run, f"foreign-{index}", amount="10")
        item_id = SalesOrderItem.objects.get(sales_order=order).pk
        with connection.cursor() as cursor:
            cursor.execute("UPDATE sales_order_item SET internal_spu_id = %s WHERE id = %s", [spu.id, item_id])

    group = client.get(URL, {"date_from": DAY, "date_to": DAY}).json()["data"]["currency_groups"][0]
    assert group["product_rankings"]["category"]["sales_amount"] == []
    assert all(row["mapping_status"] == "unmapped" for row in group["product_rankings"]["product_spu"]["sales_amount"])
    assert all(row["mapping_status"] == "unmapped" for row in group["product_rankings"]["product_sku"]["sales_amount"])


@pytest.mark.django_db
def test_store_sku_variant_and_seller_fallback_use_distinct_namespaces():
    user, tenant, platform, store, run, client = _fixture("board-product-seller-namespace")
    variant = _order(tenant, platform, store, run, "variant", amount="10")
    seller = _order(tenant, platform, store, run, "seller", amount="10")
    SalesOrderItem.objects.filter(sales_order=variant).update(
        platform_product_id="ambiguous/a", platform_variant_id="same", seller_sku="",
    )
    SalesOrderItem.objects.filter(sales_order=seller).update(
        platform_product_id="ambiguous/a", platform_variant_id="", seller_sku="same",
    )

    group = client.get(URL, {"date_from": DAY, "date_to": DAY}).json()["data"]["currency_groups"][0]
    rows = [row for row in group["product_rankings"]["store_sku"]["sales_amount"] if row["code"] == "same"]
    assert len(rows) == 2
    assert len({row["key"] for row in rows}) == 2


@pytest.mark.django_db
def test_partial_store_mapping_preserves_unique_tenant_inventory_identity():
    _, tenant, platform, store, run, client = _fixture("partial-store-map")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="partial", product_name="Partial")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="partial", inventory_type="physical")
    for i in range(2):
        order = _order(tenant, platform, store, run, f"partial-{i}", amount="10")
        SalesOrderItem.objects.filter(sales_order=order).update(platform_product_id="same", platform_variant_id="same", internal_sku=sku if i == 0 else None)
    group = client.get(URL, {"date_from": DAY, "date_to": DAY}).json()["data"]["currency_groups"][0]
    row = group["product_rankings"]["store_sku"]["sales_amount"][0]
    assert row["internal_sku_id"] == sku.id
    assert row["mapping_status"] == "partial" and row["mapping_gap_count"] == 1
    assert group["product_rankings"]["product_sku"]["sales_amount"][0]["sales_amount"] == "10"
    assert group["sales_amount"] == "20"


@pytest.mark.django_db
def test_unmapped_system_rows_keep_distinct_platform_ids_and_sales():
    _,tenant,platform,store,run,client = _fixture("unmapped-identities")
    for key in ("one", "two"):
        _order(tenant,platform,store,run,key,amount="10")
    group=client.get(URL,{"date_from":DAY,"date_to":DAY}).json()["data"]["currency_groups"][0]
    for dimension in ("product_spu","product_sku"):
        rows=group["product_rankings"][dimension]["sales_amount"]
        assert len(rows)==2
        assert {r["platform_product_id"] for r in rows}=={"product-one","product-two"}
        assert all(r["mapping_status"]=="unmapped" and r["store_id"]==store.id for r in rows)
        assert all("internal_sku_id" not in r for r in rows)
    assert group["sales_amount"]=="20"
