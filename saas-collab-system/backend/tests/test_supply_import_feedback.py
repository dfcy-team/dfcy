from io import BytesIO

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from openpyxl import Workbook

from apps.products.models import ProductSKU, ProductSPU
from apps.supply_chain.archives import save_price
from apps.supply_chain.dates import business_date
from apps.supply_chain.documents import IMPORT_HEADERS, IMPORT_SHEET
from apps.supply_chain.imports import preview_excel
from tests.test_supply_chain_v2_foundation import internal_user, world


def workbook(rows, headers=None):
    book = Workbook()
    sheet = book.active
    sheet.title = IMPORT_SHEET
    sheet.append(headers or IMPORT_HEADERS)
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def import_row(world, *, group="A", sku=None, quantity=1):
    return [group, world["supplier"].code, world["country"].code,
            sku or world["sku"].sku_code, quantity, "2.5", "", str(business_date()), ""]


@pytest.mark.django_db
def test_legacy_sku_and_required_header_markers_resolve_with_batched_queries(world):
    buyer = internal_user(world)
    legacy_skus = [world["sku"], world["sku_b"]]
    legacy_skus[0].legacy_sku_code = "HY118-Yellow"
    legacy_skus[0].save(update_fields=["legacy_sku_code"])
    legacy_skus[1].legacy_sku_code = "HY118-Pink"
    legacy_skus[1].save(update_fields=["legacy_sku_code"])
    for code in ("HY118-Green", "HY118-Black"):
        legacy_skus.append(ProductSKU.objects.create(
            tenant=world["tenant"], spu=world["spu"], sku_code=f"{code}-NEW", legacy_sku_code=code,
        ))
    rows = [
        import_row(world, group="G1", sku="HY118-Yellow", quantity=20),
        import_row(world, group="G1", sku="HY118-Pink", quantity=100),
        import_row(world, group="G1", sku="HY118-Green", quantity=10),
        import_row(world, group="G1", sku="HY118-Black", quantity=170),
        import_row(world, group="G2", sku="HY118-Black", quantity=100),
    ]
    headers = [f"{label} *" if index < 5 else label for index, label in enumerate(IMPORT_HEADERS)]
    content = workbook(rows, headers)
    with CaptureQueriesContext(connection) as captured:
        preview = preview_excel(buyer, content)
    sku_queries = [query for query in captured if "products_productsku" in query["sql"].lower()]
    assert preview["valid"]
    assert preview["groups_count"] == 2 and preview["total_quantity"] == 400
    assert [line["sku_id"] for line in preview["groups"][0]["lines"]] == [sku.pk for sku in legacy_skus]
    assert preview["groups"][1]["lines"][0]["sku_id"] == legacy_skus[3].pk
    # One batched ProductSKU lookup and one batched generated-legacy lookup join ProductSKU.
    assert len(sku_queries) == 2


@pytest.mark.django_db
def test_duplicate_sku_is_group_scoped_and_reports_excel_rows(world):
    buyer = internal_user(world)
    preview = preview_excel(buyer, workbook([
        import_row(world, group="same"),
        import_row(world, group="same"),
        import_row(world, group="other"),
    ]))
    assert not preview["valid"]
    assert preview["errors"] == [{
        "row": 3,
        "field": "商品SKU",
        "message": f"同一分组内 SKU“{world['sku'].sku_code}”重复；请检查 Excel 第 2 行和第 3 行。",
    }]
    assert preview["groups_count"] == 2
    assert [group["lines_count"] for group in preview["groups"]] == [1, 1]


@pytest.mark.django_db
def test_blank_prices_use_batched_supplier_sku_price_lookup(world):
    buyer = internal_user(world)
    save_price(buyer, {
        "supplier_id": world["supplier"].pk, "sku_id": world["sku"].pk,
        "unit_price": "3.5", "effective_date": business_date(), "expected_version": 0,
    }, idempotency_key="seed-import-price")
    rows = [import_row(world, group=f"G{i}") for i in range(12)]
    for row in rows:
        row[5] = ""
    with CaptureQueriesContext(connection) as captured:
        preview = preview_excel(buyer, workbook(rows))
    price_queries = [query for query in captured if "supply_chain_supplierproductprice" in query["sql"].lower()]
    sku_queries = [query for query in captured if "products_productsku" in query["sql"].lower()]
    assert preview["valid"] and preview["missing_prices_count"] == 0
    assert preview["total_amount"] == "42.0000"
    assert len(price_queries) == 1
    assert len(sku_queries) == 2


@pytest.mark.django_db
def test_required_fields_and_sku_state_diagnostics_are_field_specific(world):
    buyer = internal_user(world)
    inactive = ProductSKU.objects.create(
        tenant=world["tenant"], spu=world["spu"], sku_code="INACTIVE", is_active=False,
    )
    bundle = ProductSPU.objects.create(
        tenant=world["tenant"], spu_code="BUNDLE-SPU", product_name="Bundle", product_type="bundle",
    )
    bundle_sku = ProductSKU.objects.create(tenant=world["tenant"], spu=bundle, sku_code="BUNDLE-SKU")
    rows = [
        ["", world["supplier"].code, world["country"].code, world["sku"].sku_code, 1, "2.5", "", str(business_date()), ""],
        import_row(world, group="inactive", sku=inactive.sku_code),
        import_row(world, group="bundle", sku=bundle_sku.sku_code),
        import_row(world, group="missing", sku="NO-SUCH-SKU"),
    ]
    preview = preview_excel(buyer, workbook(rows))
    assert not preview["valid"] and preview["error_count"] == 4
    assert [(item["row"], item["field"]) for item in preview["errors"]] == [
        (2, "导入分组号"), (3, "商品SKU"), (4, "商品SKU"), (5, "商品SKU"),
    ]
    assert "已停用" in preview["errors"][1]["message"]
    assert "组合商品" in preview["errors"][2]["message"]
    assert "旧 SKU" in preview["errors"][3]["message"]
