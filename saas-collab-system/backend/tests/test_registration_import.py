import io
import zipfile
from datetime import datetime
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import load_workbook
from rest_framework.exceptions import ValidationError
from apps.products.models import ProductSKU, ProductSPU
from apps.tenants.models import Tenant

from apps.sales_management.registration_import import SCHEMA, run_import, safe_zip, registration_template
from apps.sales_management.registration_models import OrderRegistration, PendingOrderDetail, RegistrationImportBatch
from tests.test_order_registrations import context, screenshot

pytestmark = pytest.mark.django_db


def xlsx(kind, rows):
    template = Path(__file__).resolve().parents[1] / f"apps/sales_management/templates/{kind}.xlsx"
    workbook = load_workbook(template)
    sheet = workbook["登记"]
    for number, data in enumerate(rows, 2):
        for column, (field, _) in enumerate(SCHEMA[kind], 1):
            sheet.cell(number, column).value = data.get(field)
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return SimpleUploadedFile("registration.xlsx", output.getvalue())


def attachments():
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("proof.png", screenshot().read())
    return SimpleUploadedFile("proofs.zip", output.getvalue())


@pytest.mark.parametrize("kind", ["exchange", "promotion", "gcash"])
def test_download_template_only_requires_screenshots_for_gcash(kind):
    with registration_template(kind) as source:
        workbook = load_workbook(source)
        expected = SCHEMA[kind] if kind == "gcash" else SCHEMA[kind][:-1]
        assert [cell.value for cell in workbook["登记"][1]] == [label for _, label in expected]
        workbook.close()


@pytest.mark.parametrize("kind", ["exchange", "promotion"])
@pytest.mark.parametrize("legacy", [False, True])
def test_import_without_screenshots_accepts_new_and_legacy_templates(context, kind, legacy):
    creator, _, store, order, sku = context
    row = {"store_code": store.code, "order_number": order.external_order_id, "group": "NO-PROOF",
           "action": "增加", "new_sku": sku.sku_code, "add_quantity": 1, "reason": "增加商品",
           "order_amount": 100, "store_currency": "PHP", "fee_amount": 10, "fee_currency": "PHP", "exchange_rate": 1}
    with registration_template(kind) as source:
        workbook = load_workbook(source)
    if legacy:
        workbook["登记"].cell(1, len(SCHEMA[kind]), SCHEMA[kind][-1][1])
    for column, (field, _) in enumerate(SCHEMA[kind][:-1], 1):
        workbook["登记"].cell(2, column, row.get(field))
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    upload = lambda: SimpleUploadedFile("registration.xlsx", output.getvalue())
    preview = run_import(creator, kind, upload(), None)
    assert preview["results"][0]["valid"]
    result = run_import(creator, kind, upload(), None, confirm=True, expected_hash=preview["file_hash"])
    assert result["results"][0]["status"] == "created"
    assert OrderRegistration.objects.get().evidence.count() == 0


def test_exchange_group_with_one_bad_line_is_not_imported(context):
    creator, _, store, order, sku = context
    base = {"store_code": store.code, "order_number": order.external_order_id, "group": "0001", "reason": "增加商品", "note": ""}
    rows = [{**base, "action": "增加", "new_sku": sku.sku_code, "add_quantity": 1},
            {**base, "action": "减少", "old_sku": sku.sku_code, "reduce_quantity": 50}]
    preview = run_import(creator, "exchange", xlsx("exchange", rows), None)
    assert preview["results"][0]["rows"] == [2, 3] and not preview["results"][0]["valid"]
    assert not OrderRegistration.objects.exists() and not PendingOrderDetail.objects.exists()
    with pytest.raises(ValidationError):
        run_import(creator, "exchange", xlsx("exchange", rows), None, confirm=True, expected_hash=preview["file_hash"])
    assert not OrderRegistration.objects.exists()


@pytest.mark.parametrize("old_legacy", [False, True])
@pytest.mark.parametrize("new_legacy", [False, True])
def test_exchange_import_resolves_current_and_legacy_codes(context, old_legacy, new_legacy):
    creator, _, store, order, sku = context
    sku.legacy_sku_code = "HISTORICAL-001"
    sku.save(update_fields=["legacy_sku_code"])
    row = {"store_code": store.code, "order_number": order.external_order_id, "group": "MIXED-CODES",
           "action": "替换", "old_sku": sku.legacy_sku_code if old_legacy else sku.sku_code,
           "new_sku": sku.legacy_sku_code if new_legacy else sku.sku_code,
           "reduce_quantity": 1, "add_quantity": 1, "reason": "调整商品"}
    content = xlsx("exchange", [row]).read()
    upload = lambda: SimpleUploadedFile("registration.xlsx", content)
    preview = run_import(creator, "exchange", upload(), None)
    assert preview["results"][0]["valid"]
    change = preview["results"][0]["payload"]["changes"][0]
    assert change["old_sku_id"] == change["new_sku_id"] == sku.pk
    result = run_import(creator, "exchange", upload(), None,
                        confirm=True, expected_hash=preview["file_hash"])
    assert result["results"][0]["status"] == "created"
    saved = OrderRegistration.objects.get()
    assert saved.status == "draft" and saved.approval_id is None
    assert order.items.get().quantity == 2
    assert not PendingOrderDetail.objects.get(order=order).adjusted


@pytest.mark.parametrize("collision", ["legacy", "current"])
def test_exchange_import_rejects_ambiguous_sku_codes(context, collision):
    creator, _, store, order, sku = context
    sku.legacy_sku_code = "DUPLICATE-CODE"
    sku.save(update_fields=["legacy_sku_code"])
    ProductSKU.objects.create(tenant=sku.tenant, spu=sku.spu,
        sku_code="DUPLICATE-CODE" if collision == "current" else "SECOND",
        legacy_sku_code="DUPLICATE-CODE" if collision == "legacy" else "")
    row = {"store_code": store.code, "order_number": order.external_order_id, "group": "AMBIGUOUS",
           "action": "增加", "new_sku": "DUPLICATE-CODE", "add_quantity": 1, "reason": "增加商品"}
    result = run_import(creator, "exchange", xlsx("exchange", [row]), None)
    assert not result["results"][0]["valid"] and "多个" in result["results"][0]["error"]
    assert not OrderRegistration.objects.exists() and not PendingOrderDetail.objects.exists()


@pytest.mark.parametrize("case", ["inactive", "foreign", "missing", "same_record"])
def test_exchange_import_legacy_code_scope_and_activity(context, case):
    creator, _, store, order, sku = context
    code = "OLD-CODE"
    if case == "foreign":
        tenant = Tenant.objects.create(name="Other tenant", code="other-sku-tenant")
        spu = ProductSPU.objects.create(tenant=tenant, spu_code="OTHER", product_name="Other")
        ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="OTHER", legacy_sku_code=code)
    elif case != "missing":
        sku.legacy_sku_code = sku.sku_code if case == "same_record" else code
        sku.is_active = case != "inactive"
        sku.save(update_fields=["legacy_sku_code", "is_active"])
        code = sku.legacy_sku_code
    row = {"store_code": store.code, "order_number": order.external_order_id, "group": "SCOPED-CODE",
           "action": "增加", "new_sku": code, "add_quantity": 1, "reason": "增加商品"}
    result = run_import(creator, "exchange", xlsx("exchange", [row]), None)
    assert result["results"][0]["valid"] is (case == "same_record")
    assert not OrderRegistration.objects.exists() and not PendingOrderDetail.objects.exists()


def test_promotion_preview_confirm_repeat_no_automatic_approval(context):
    creator, _, store, order, _ = context
    row = {"store_code": store.code, "order_number": order.external_order_id, "group": "PROMO001", "order_amount": 100,
           "store_currency": "PHP", "fee_amount": 10, "fee_currency": "CNY", "exchange_rate": 8,
           "rate_date": "2026-10-13", "rate_source": "人工", "note": "真实推广"}
    content = xlsx("promotion", [row]).read()
    upload = lambda: SimpleUploadedFile("registration.xlsx", content)
    preview = run_import(creator, "promotion", upload(), None)
    assert preview["results"][0]["payload"]["cost"] == "180.00"
    assert not OrderRegistration.objects.exists()
    first = run_import(creator, "promotion", upload(), None, confirm=True, expected_hash=preview["file_hash"])
    second = run_import(creator, "promotion", upload(), None, confirm=True, expected_hash=preview["file_hash"])
    assert first["batch_id"] == second["batch_id"]
    assert OrderRegistration.objects.count() == RegistrationImportBatch.objects.count() == 1
    saved = OrderRegistration.objects.get()
    assert saved.status == "draft" and saved.approval_id is None
    assert second["results"][0]["status"] == "existing"


@pytest.mark.parametrize("paid_at", ["2026-10-13", datetime(2026, 10, 13), "2026-10-13T10:00:00+08:00"])
def test_gcash_import_preserves_phone_and_currency_masks_preview(context, paid_at):
    creator, _, store, order, _ = context
    row = {"store_code": store.code, "order_number": order.external_order_id, "group": "GCASH001", "type": "退款",
           "amount": 10, "currency": "CNY", "paid_at": paid_at, "recipient": "测试",
           "phone": "09123456789", "payment_account": "test-account", "transaction_reference": "0001",
           "note": "人工已付退款", "attachments": "proof.png"}
    content, proof = xlsx("gcash", [row]).read(), attachments().read()
    preview = run_import(creator, "gcash", SimpleUploadedFile("registration.xlsx", content), SimpleUploadedFile("proofs.zip", proof))
    assert preview["results"][0]["valid"] and preview["results"][0]["payload"]["phone"] == "***6789"
    run_import(creator, "gcash", SimpleUploadedFile("registration.xlsx", content), SimpleUploadedFile("proofs.zip", proof), confirm=True, expected_hash=preview["file_hash"])
    saved = OrderRegistration.objects.get()
    assert saved.payload["phone"] == "09123456789" and saved.payload["currency"] == "CNY"
    assert saved.payload["paid_at"] == "2026-10-13"
    assert saved.payload["note"] == "人工已付退款" and "reason" not in saved.payload
    assert saved.status == "draft" and saved.evidence.count() == 1


def test_numeric_order_identifier_is_rejected(context):
    creator, _, store, _, _ = context
    row = {"store_code": store.code, "order_number": 123, "group": "0001"}
    result = run_import(creator, "promotion", xlsx("promotion", [row]), None)
    assert not result["results"][0]["valid"] and "文本" in result["results"][0]["error"]


@pytest.mark.parametrize("name", ["../proof.png", "sub/proof.png", "C:\\proof.png"])
def test_attachment_archive_paths_are_rejected(name):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(name, b"test")
    with pytest.raises(ValidationError):
        safe_zip(output.getvalue())


def test_missing_screenshot_whole_gcash_row_rejected(context):
    creator, _, store, _, _ = context
    row = {"store_code": store.code, "group": "0001", "type": "其他", "amount": 1, "currency": "PHP",
           "paid_at": "2026-10-13T10:00:00+08:00", "reason": "test", "note": "用途", "attachments": "missing.png"}
    result = run_import(creator, "gcash", xlsx("gcash", [row]), None)
    assert not result["results"][0]["valid"] and not OrderRegistration.objects.exists()
