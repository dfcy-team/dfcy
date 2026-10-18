from django.db import connection
from django.test.utils import CaptureQueriesContext
from apps.masterdata.models import CountrySiteMaster, SupplierMaster
from apps.products.models import ProductSKU, ProductSPU

from apps.tenants.models import Tenant
from tests.test_supply_chain_v2_foundation import confirmed_order, internal_user, po_payload, supplier_user, world
from tests.test_supply_chain_v2_shipments import EXTERNAL, INTERNAL, buyer_client, supplier_client


def _count_list_queries(client, url, limit=100):
    with CaptureQueriesContext(connection) as queries:
        response = client.get(url, {"limit": limit})
    assert response.status_code == 200, response.data
    return response.data["data"], len(queries)


def test_purchase_lists_batch_active_lines_and_keep_tenant_and_supplier_scope(world):
    buyer = internal_user(world)
    orders = [confirmed_order(world, buyer, key=f"batch-{i}", payload=po_payload(
        world, key=f"batch-{i}", number=f"PO-BATCH-{i}")) for i in range(20)]

    foreign_tenant = Tenant.objects.create(name="Other purchase tenant", code="other-purchase-list")
    foreign_country = CountrySiteMaster.objects.create(
        tenant=foreign_tenant, code="us", name="USA", country_code="US")
    foreign_supplier = SupplierMaster.objects.create(
        tenant=foreign_tenant, code="foreign-supplier", name="Foreign supplier")
    foreign_spu = ProductSPU.objects.create(
        tenant=foreign_tenant, spu_code="FOREIGN-SPU", product_name="Foreign widget")
    foreign_sku = ProductSKU.objects.create(tenant=foreign_tenant, spu=foreign_spu, sku_code="FOREIGN-SKU")
    foreign_world = {
        "tenant": foreign_tenant, "country": foreign_country, "supplier": foreign_supplier,
        "supplier_b": foreign_supplier, "sku": foreign_sku, "sku_b": foreign_sku,
    }
    foreign_buyer = internal_user(foreign_world, username="foreign-buyer")
    foreign_order = confirmed_order(
        foreign_world, foreign_buyer, key="foreign",
        payload=po_payload(foreign_world, key="foreign", number="PO-FOREIGN"))

    internal = buyer_client(buyer)
    internal_data, internal_queries = _count_list_queries(internal, INTERNAL + "purchase-orders/")
    _, internal_single_queries = _count_list_queries(internal, INTERNAL + "purchase-orders/", limit=1)
    assert {row["id"] for row in internal_data} == {order.pk for order in orders}
    assert foreign_order.pk not in {row["id"] for row in internal_data}
    assert all("supplier_reference_price" in row["lines"][0] for row in internal_data)

    supplier = supplier_user(world, world["supplier"], "purchase-list-supplier")
    external = supplier_client(supplier)
    supplier_data, supplier_queries = _count_list_queries(external, EXTERNAL + "purchase-orders/")
    _, supplier_single_queries = _count_list_queries(external, EXTERNAL + "purchase-orders/", limit=1)
    assert {row["id"] for row in supplier_data} == {order.pk for order in orders}
    assert all("supplier_reference_price" not in row["lines"][0] for row in supplier_data)

    assert internal_queries == internal_single_queries
    assert supplier_queries == supplier_single_queries
