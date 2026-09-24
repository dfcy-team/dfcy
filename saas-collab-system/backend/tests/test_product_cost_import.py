import io
import zipfile
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.audit.models import DataImportLog
from apps.masterdata.models import WarehouseMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.cost_services import append_cost_version
from apps.products.models import ProductCostVersion, ProductSKU, ProductSPU
from apps.tenants.models import Tenant


HEADERS = "sku_code,warehouse_code,effective_from,effective_to,currency,purchase_cost,freight_cost,duty_cost,packaging_cost,other_cost,confirmed_cost,reason\n"


def make_context(code="import"):
    tenant = Tenant.objects.create(name=f"Cost {code}", code=f"cost-{code}")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code=f"SPU-{code}", product_name="Imported product")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code=f"SKU-{code}", product_name="Imported product")
    WarehouseMaster.objects.create(tenant=tenant, code="WH-CN", name="China warehouse",
                                   country_code="CN", warehouse_type="owned")
    user = CustomUser.objects.create_user(
        username=f"cost-{code}", tenant=tenant, user_type=CustomUser.UserType.INTERNAL
    )
    return tenant, sku, user


def grant(user, *codes):
    role = Role.objects.create(tenant=user.tenant, name=f"Cost {user.id}", code=f"cost-import-{user.id}")
    role.permissions.add(*Permission.objects.filter(code__in=codes))
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def csv_file(sku_code, start="2026-01-01", end="2026-02-01", purchase="10.0000"):
    body = HEADERS + f"{sku_code},WH-CN,{start},{end},CNY,{purchase},2,1,0.5,0.5,14,monthly import\n"
    return body.encode("utf-8-sig")


def upload(raw, name="costs.csv"):
    content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if name.endswith("xlsx") else "text/csv"
    return SimpleUploadedFile(name, raw, content_type=content_type)


def xlsx_file(rows):
    strings = []
    for row_number, row in enumerate(rows, start=1):
        cells = []
        for column_number, value in enumerate(row, start=1):
            column = ""
            number = column_number
            while number:
                number, remainder = divmod(number - 1, 26)
                column = chr(65 + remainder) + column
            cells.append(f'<c r="{column}{row_number}" t="inlineStr"><is><t>{value}</t></is></c>')
        strings.append(f'<row r="{row_number}">{"".join(cells)}</row>')
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Costs" sheetId="1" r:id="rId1"/></sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        archive.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{"".join(strings)}</sheetData></worksheet>')
    return stream.getvalue()


@pytest.mark.django_db
def test_csv_preview_confirm_and_idempotent_replay():
    tenant, sku, user = make_context("csv")
    grant(user, "products.cost.backfill", "products.cost.approve")
    client = client_for(user)
    raw = csv_file(sku.sku_code)
    preview = client.post("/api/internal/products/costs/import/preview/", {"file": upload(raw)}, format="multipart")
    assert preview.status_code == 200
    detail = preview.json()["data"]
    assert (detail["total"], detail["valid"], detail["errors"]) == (1, 1, [])
    assert len(detail["digest"]) == 64 and detail["token"]

    payload = {"file": upload(raw), "token": detail["token"]}
    first = client.post("/api/internal/products/costs/import/confirm/", payload, format="multipart", HTTP_IDEMPOTENCY_KEY="cost-import-0001")
    assert first.status_code == 201
    replay = client.post(
        "/api/internal/products/costs/import/confirm/",
        {"file": upload(raw), "token": detail["token"]}, format="multipart", HTTP_IDEMPOTENCY_KEY="cost-import-0001",
    )
    assert replay.status_code == 201
    assert replay.json()["data"] == first.json()["data"]
    assert ProductCostVersion.objects.filter(tenant=tenant, source=ProductCostVersion.Source.IMPORT).count() == 1


@pytest.mark.django_db
def test_downloadable_chinese_csv_template_headers_are_accepted():
    _, sku, user = make_context("zh-template")
    grant(user, "products.cost.backfill")
    headers = "*SKU编码,*仓库编码,*生效开始,生效结束,*币种,采购成本,物流分摊,税费,包装费,其他费用,*确认成本,调整原因\n"
    raw = (headers + f"{sku.sku_code},WH-CN,2026-07-01,2026-08-01,CNY,10,2,1,0.5,0.5,14,月度导入\n").encode("utf-8-sig")
    response = client_for(user).post(
        "/api/internal/products/costs/import/preview/",
        {"file": upload(raw, "商品成本导入模板.csv")},
        format="multipart",
    )
    assert response.status_code == 200
    assert response.json()["data"]["errors"] == []
    assert response.json()["data"]["valid"] == 1


@pytest.mark.django_db
def test_cost_import_accepts_legacy_sku_code_without_current_sku_code():
    _, sku, user = make_context("legacy-code")
    sku.legacy_sku_code = "OLD-SKU-001"
    sku.save(update_fields=["legacy_sku_code"])
    grant(user, "products.cost.backfill")
    headers = "旧SKU编码（二选一）,*仓库编码,*生效开始,生效结束,*币种,采购成本,物流分摊,税费,包装费,其他费用,*确认成本,调整原因\n"
    raw = (headers + "OLD-SKU-001,WH-CN,2026-09-01,,CNY,10,2,1,0.5,0.5,14,旧编码导入\n").encode("utf-8-sig")
    response = client_for(user).post(
        "/api/internal/products/costs/import/preview/",
        {"file": upload(raw, "商品成本导入模板.csv")},
        format="multipart",
    )
    assert response.status_code == 200
    assert response.json()["data"]["errors"] == []
    assert response.json()["data"]["valid"] == 1


@pytest.mark.django_db
def test_cost_import_rejects_conflicting_current_and_legacy_sku_codes():
    tenant, sku, user = make_context("code-conflict")
    sku.legacy_sku_code = "OLD-SKU-A"
    sku.save(update_fields=["legacy_sku_code"])
    other_spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-OTHER", product_name="Other")
    ProductSKU.objects.create(
        tenant=tenant,
        spu=other_spu,
        sku_code="SKU-OTHER",
        legacy_sku_code="OLD-SKU-B",
        product_name="Other",
    )
    grant(user, "products.cost.backfill")
    headers = "SKU编码（二选一）,旧SKU编码（二选一）,*仓库编码,*生效开始,生效结束,*币种,采购成本,物流分摊,税费,包装费,其他费用,*确认成本,调整原因\n"
    raw = (headers + f"{sku.sku_code},OLD-SKU-B,WH-CN,2026-09-01,,CNY,10,2,1,0.5,0.5,14,冲突校验\n").encode("utf-8-sig")
    response = client_for(user).post(
        "/api/internal/products/costs/import/preview/",
        {"file": upload(raw)},
        format="multipart",
    )
    assert response.status_code == 200
    errors = response.json()["data"]["errors"]
    assert any(item["field"] == "legacy_sku_code" and "不一致" in item["message"] for item in errors)


@pytest.mark.django_db
def test_same_idempotency_key_rejects_different_file():
    _, sku, user = make_context("key")
    grant(user, "products.cost.backfill", "products.cost.approve")
    client = client_for(user)
    raw = csv_file(sku.sku_code)
    preview = client.post("/api/internal/products/costs/import/preview/", {"file": upload(raw)}, format="multipart").json()["data"]
    assert client.post("/api/internal/products/costs/import/confirm/", {"file": upload(raw), "token": preview["token"]}, format="multipart", HTTP_IDEMPOTENCY_KEY="same-key-0001").status_code == 201
    changed = csv_file(sku.sku_code, start="2026-03-01", end="2026-04-01", purchase="12")
    changed_preview = client.post("/api/internal/products/costs/import/preview/", {"file": upload(changed)}, format="multipart").json()["data"]
    response = client.post("/api/internal/products/costs/import/confirm/", {"file": upload(changed), "token": changed_preview["token"]}, format="multipart", HTTP_IDEMPOTENCY_KEY="same-key-0001")
    assert response.status_code == 400
    assert ProductCostVersion.objects.filter(sku=sku).count() == 1


@pytest.mark.django_db
def test_preview_reports_batch_and_database_overlap():
    tenant, sku, user = make_context("overlap")
    grant(user, "products.cost.backfill")
    start = timezone.now()
    append_cost_version(
        tenant=tenant, sku=sku, warehouse=WarehouseMaster.objects.get(tenant=tenant, code="WH-CN"),
        actor=user, status="confirmed", source="manual", currency="CNY",
        purchase_cost=10, freight_cost=0, duty_cost=0, packaging_cost=0, other_cost=0,
        system_cost=None, confirmed_cost=10, effective_from=start, effective_to=start + timedelta(days=30), reason="existing",
    )
    date = start.strftime("%Y-%m-%dT%H:%M:%S%z")
    body = HEADERS + f"{sku.sku_code},WH-CN,{date},,CNY,10,0,0,0,0,10,one\n{sku.sku_code},WH-CN,{date},,CNY,11,0,0,0,0,11,two\n"
    response = client_for(user).post("/api/internal/products/costs/import/preview/", {"file": upload(body.encode())}, format="multipart")
    assert response.status_code == 200
    errors = response.json()["data"]["errors"]
    assert any("import row" in item["message"] for item in errors)
    assert any("existing version" in item["message"] for item in errors)
    batch_id = response.json()["data"]["error_batch_id"]
    log = DataImportLog.objects.get(pk=batch_id, import_type="product_cost_preview")
    assert log.status == DataImportLog.Status.FAILED
    assert log.error_summary["errors"] == errors


@pytest.mark.django_db
def test_xlsx_preview_and_confirm_requires_both_permissions():
    _, sku, user = make_context("xlsx")
    grant(user, "products.cost.backfill")
    row = [sku.sku_code, "WH-CN", "2026-01-01", "2026-02-01", "CNY", "10", "2", "1", "0.5", "0.5", "14", "xlsx"]
    raw = xlsx_file([list(EXPECTED_HEADERS := HEADERS.strip().split(",")), row])
    client = client_for(user)
    preview = client.post("/api/internal/products/costs/import/preview/", {"file": upload(raw, "costs.xlsx")}, format="multipart")
    assert preview.status_code == 200 and preview.json()["data"]["valid"] == 1
    confirm = client.post(
        "/api/internal/products/costs/import/confirm/",
        {"file": upload(raw, "costs.xlsx"), "token": preview.json()["data"]["token"]},
        format="multipart", HTTP_IDEMPOTENCY_KEY="xlsx-import-0001",
    )
    assert confirm.status_code == 403


@pytest.mark.django_db
def test_real_openpyxl_workbook_with_date_cells_previews_and_confirms():
    openpyxl = pytest.importorskip("openpyxl")
    tenant, sku, user = make_context("real-xlsx")
    grant(user, "products.cost.backfill", "products.cost.approve")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Costs"
    sheet.append(HEADERS.strip().split(","))
    sheet.append([
        sku.sku_code,
        "WH-CN",
        datetime(2026, 5, 1),
        datetime(2026, 6, 1),
        "CNY", 10, 2, 1, 0.5, 0.5, 14, "real workbook",
    ])
    stream = io.BytesIO()
    workbook.save(stream)
    raw = stream.getvalue()
    client = client_for(user)
    preview = client.post(
        "/api/internal/products/costs/import/preview/",
        {"file": upload(raw, "real-costs.xlsx")},
        format="multipart",
    )
    assert preview.status_code == 200
    detail = preview.json()["data"]
    assert (detail["total"], detail["valid"], detail["errors"]) == (1, 1, [])
    confirm = client.post(
        "/api/internal/products/costs/import/confirm/",
        {"file": upload(raw, "real-costs.xlsx"), "token": detail["token"]},
        format="multipart",
        HTTP_IDEMPOTENCY_KEY="real-xlsx-import-0001",
    )
    assert confirm.status_code == 201
    version = ProductCostVersion.objects.get(tenant=tenant, sku=sku)
    assert timezone.localtime(version.effective_from).date().isoformat() == "2026-05-01"
    assert timezone.localtime(version.effective_to).date().isoformat() == "2026-06-01"


@pytest.mark.django_db
def test_import_rejects_missing_or_other_tenant_warehouse_code():
    tenant, sku, user = make_context("warehouse-invalid")
    grant(user, "products.cost.backfill")
    other = Tenant.objects.create(name="Other warehouse owner", code="cost-other-wh")
    WarehouseMaster.objects.create(tenant=other, code="WH-US", name="Other warehouse",
                                   country_code="US", warehouse_type="owned")
    body = HEADERS + f"{sku.sku_code},WH-US,2026-01-01,,CNY,10,0,0,0,0,10,bad warehouse\n"
    response = client_for(user).post("/api/internal/products/costs/import/preview/",
                                     {"file": upload(body.encode())}, format="multipart")
    assert response.status_code == 200
    errors = response.json()["data"]["errors"]
    assert any(error["row"] == 2 and error["field"] == "warehouse_code" for error in errors)
    missing_header = HEADERS.replace("warehouse_code,", "")
    response = client_for(user).post("/api/internal/products/costs/import/preview/",
                                     {"file": upload(missing_header.encode())}, format="multipart")
    assert any(error["field"] == "headers" for error in response.json()["data"]["errors"])


@pytest.mark.django_db
def test_import_allows_same_sku_and_period_in_two_warehouses():
    tenant, sku, user = make_context("warehouse-pair")
    grant(user, "products.cost.backfill", "products.cost.approve")
    WarehouseMaster.objects.create(tenant=tenant, code="WH-US", name="US warehouse",
                                   country_code="US", warehouse_type="owned")
    body = HEADERS + (
        f"{sku.sku_code},WH-CN,2026-01-01,2026-02-01,CNY,10,0,0,0,0,10,CN\n"
        f"{sku.sku_code},WH-US,2026-01-01,2026-02-01,USD,20,0,0,0,0,20,US\n"
    )
    raw = body.encode()
    client = client_for(user)
    preview = client.post("/api/internal/products/costs/import/preview/",
                          {"file": upload(raw)}, format="multipart").json()["data"]
    assert preview["valid"] == 2 and preview["errors"] == []
    result = client.post("/api/internal/products/costs/import/confirm/",
                         {"file": upload(raw), "token": preview["token"]}, format="multipart",
                         HTTP_IDEMPOTENCY_KEY="warehouse-pair-0001")
    assert result.status_code == 201
    assert set(ProductCostVersion.objects.filter(sku=sku).values_list("warehouse__code", flat=True)) == {"WH-CN", "WH-US"}


@pytest.mark.django_db
def test_gb18030_chinese_csv_preview_and_confirm():
    tenant, sku, user = make_context("gb18030")
    grant(user, "products.cost.backfill", "products.cost.approve")
    headers = "SKU编码（二选一）,旧SKU编码（二选一）,*仓库编码,*生效开始,生效结束,*币种,采购成本,物流分摊,税费,包装费,其他费用,*确认成本,调整原因\n"
    raw = (headers + f"{sku.sku_code},,WH-CN,2026-08-01,,CNY,,,,,,10.98,\n").encode("gb18030")
    client = client_for(user)
    preview = client.post("/api/internal/products/costs/import/preview/", {"file": upload(raw)}, format="multipart")
    assert preview.status_code == 200
    detail = preview.json()["data"]
    assert (detail["total"], detail["valid"], detail["errors"]) == (1, 1, [])
    result = client.post(
        "/api/internal/products/costs/import/confirm/",
        {"file": upload(raw), "token": detail["token"]},
        format="multipart", HTTP_IDEMPOTENCY_KEY="cost-gb18030-0001",
    )
    assert result.status_code == 201
    assert ProductCostVersion.objects.get(tenant=tenant, sku=sku).confirmed_cost == Decimal("10.9800")


@pytest.mark.django_db
def test_unreadable_csv_returns_logged_exportable_error():
    tenant, _sku, user = make_context("bad-encoding")
    grant(user, "products.cost.backfill")
    response = client_for(user).post(
        "/api/internal/products/costs/import/preview/",
        {"file": upload(b"\xff\xff\xff\xff")}, format="multipart",
    )
    assert response.status_code == 200
    detail = response.json()["data"]
    assert detail["valid"] == 0
    assert detail["errors"][0]["field"] == "file"
    assert "编码" in detail["errors"][0]["message"]
    assert detail["error_batch_id"]
    assert DataImportLog.objects.get(pk=detail["error_batch_id"], tenant=tenant).status == DataImportLog.Status.FAILED


@pytest.mark.django_db
def test_next_month_import_closes_open_previous_month_without_overwrite():
    tenant, sku, user = make_context("next-month")
    grant(user, "products.cost.backfill", "products.cost.approve")
    client = client_for(user)
    august = (HEADERS + f"{sku.sku_code},WH-CN,2026-08-01,,CNY,,,,,,10.98,August\n").encode()
    august_preview = client.post("/api/internal/products/costs/import/preview/", {"file": upload(august)}, format="multipart").json()["data"]
    assert august_preview["errors"] == []
    august_confirm = client.post(
        "/api/internal/products/costs/import/confirm/",
        {"file": upload(august), "token": august_preview["token"]},
        format="multipart", HTTP_IDEMPOTENCY_KEY="cost-august-0001",
    )
    assert august_confirm.status_code == 201

    september = (HEADERS + f"{sku.sku_code},WH-CN,2026-09-01,,CNY,,,,,,12.34,September\n").encode()
    september_preview = client.post("/api/internal/products/costs/import/preview/", {"file": upload(september)}, format="multipart").json()["data"]
    assert (september_preview["total"], september_preview["valid"], september_preview["errors"]) == (1, 1, [])
    september_confirm = client.post(
        "/api/internal/products/costs/import/confirm/",
        {"file": upload(september), "token": september_preview["token"]},
        format="multipart", HTTP_IDEMPOTENCY_KEY="cost-september-0001",
    )
    assert september_confirm.status_code == 201
    versions = list(ProductCostVersion.objects.filter(tenant=tenant, sku=sku).order_by("effective_from"))
    assert len(versions) == 2
    assert timezone.localtime(versions[0].effective_to).date().isoformat() == "2026-09-01"
    assert timezone.localtime(versions[1].effective_from).date().isoformat() == "2026-09-01"
    assert versions[0].confirmed_cost == Decimal("10.9800")
    assert versions[1].confirmed_cost == Decimal("12.3400")
