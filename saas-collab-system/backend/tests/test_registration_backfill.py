from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.sales_management.registration_import import run_import
from apps.sales_management.registration_models import OrderRegistration
from apps.sales_management.registration_services import registration_action
from tests.test_order_registrations import context
from tests.test_registration_import import xlsx

pytestmark = pytest.mark.django_db


def test_backfill_rounds_and_preserves_original_without_evidence(context):
    user, _, store, _, _ = context
    data = {"store_code": store.name, "group": "precision", "type": "其他",
            "amount": "12601.4041", "currency": "PHP", "paid_at": "2026-08-03"}
    content = xlsx("gcash", [data]).read()
    upload = lambda: SimpleUploadedFile("registration.xlsx", content)
    preview = run_import(user, "gcash", upload(), None, backfill=True)
    result = preview["results"][0]
    assert result["valid"]
    assert result["payload"]["amount"] == "12601.40"
    assert result["payload"]["note"] == "历史补录，退款原因可能已缺失"
    assert result["snapshot"]["import_adjustments"]["amount"]["original"] == "12601.4041"
    assert not OrderRegistration.objects.exists()
    saved = run_import(user, "gcash", upload(), None, backfill=True,
                       confirm=True, expected_hash=preview["file_hash"])
    row = OrderRegistration.objects.get(pk=saved["results"][0]["id"])
    row = registration_action(user, "gcash", row.pk, "register", expected_version=row.version)
    assert row.status == "registered" and not row.evidence.exists()
    data["store_code"] = store.code
    retry = run_import(user, "gcash", xlsx("gcash", [data]), None, backfill=True)
    assert retry["results"][0]["status"] == "existing"
    assert OrderRegistration.objects.count() == 1


def test_regular_import_still_requires_note_and_exact_precision(context):
    user, _, store, _, _ = context
    data = {"store_code": store.code, "group": "normal", "type": "其他",
            "amount": "1.005", "currency": "PHP", "paid_at": "2026-08-03"}
    assert not run_import(user, "gcash", xlsx("gcash", [data]), None)["results"][0]["valid"]
    data["note"] = "已有用途"
    content = xlsx("gcash", [data]).read()
    upload = lambda: SimpleUploadedFile("registration.xlsx", content)
    preview = run_import(user, "gcash", upload(), None, backfill=True)
    assert preview["results"][0]["payload"]["note"] == "已有用途"
    assert preview["results"][0]["payload"]["amount"] == "1.01"


def test_financial_preview_does_not_insert_registration(context):
    user, _, store, _, _ = context
    data = {"store_code": store.code, "group": "preview", "type": "其他",
            "amount": "1", "currency": "PHP", "paid_at": "2026-08-03", "note": "用途"}
    with patch.object(OrderRegistration.objects, "create", side_effect=AssertionError("preview wrote")):
        assert run_import(user, "gcash", xlsx("gcash", [data]), None)["results"][0]["valid"]


def test_paged_confirmation_preserves_batch_results_and_retry(context):
    from apps.sales_management.registration_models import RegistrationImportBatch
    user, _, store, _, _ = context
    rows = [{"store_code": store.code, "group": str(i), "type": "其他", "amount": "1",
             "currency": "PHP", "paid_at": "2026-08-03", "note": "用途"} for i in range(3)]
    content = xlsx("gcash", rows).read()
    upload = lambda: SimpleUploadedFile("registration.xlsx", content)
    first = run_import(user, "gcash", upload(), None, limit=2)
    assert first["next_offset"] == 2 and first["total"] == 3
    for offset in (0, 2, 0):
        result = run_import(user, "gcash", upload(), None, limit=2, offset=offset,
                            confirm=True, expected_hash=first["file_hash"])
        assert all(item["valid"] for item in result["results"])
    assert OrderRegistration.objects.count() == 3
    assert len(RegistrationImportBatch.objects.get().results) == 3


def test_backfill_changed_original_amount_is_not_hidden_by_rounding(context):
    user, _, store, _, _ = context
    data = {"store_code": store.code, "group": "raw", "type": "其他", "amount": "1.001",
            "currency": "PHP", "paid_at": "2026-08-03", "note": "用途"}
    content = xlsx("gcash", [data]).read()
    upload = lambda: SimpleUploadedFile("registration.xlsx", content)
    preview = run_import(user, "gcash", upload(), None, backfill=True)
    run_import(user, "gcash", upload(), None, backfill=True,
               confirm=True, expected_hash=preview["file_hash"])
    data["amount"] = "1.002"
    assert not run_import(user, "gcash", xlsx("gcash", [data]), None, backfill=True)["results"][0]["valid"]


def test_promotion_keeps_rounding_history_after_registration(context):
    user, _, store, order, _ = context
    data = {"store_code": store.code, "order_number": order.external_order_id, "group": "promo",
            "store_currency": "PHP", "order_amount": "10.005", "fee_amount": "1.005",
            "fee_currency": "PHP", "exchange_rate": "1"}
    content = xlsx("promotion", [data]).read()
    upload = lambda: SimpleUploadedFile("registration.xlsx", content)
    preview = run_import(user, "promotion", upload(), None, backfill=True)
    assert preview["results"][0]["payload"]["cost"] == "11.02"
    result = run_import(user, "promotion", upload(), None, backfill=True,
                        confirm=True, expected_hash=preview["file_hash"])
    row = OrderRegistration.objects.get(pk=result["results"][0]["id"])
    row = registration_action(user, "promotion", row.pk, "register", expected_version=row.version)
    assert row.snapshot["import_adjustments"]["order_amount"]["original"] == "10.005"


def test_ambiguous_store_name_is_rejected(context):
    user, _, store, _, _ = context
    data = {"store_code": store.name, "group": "ambiguous", "type": "其他", "amount": "1",
            "currency": "PHP", "paid_at": "2026-08-03", "note": "用途"}
    store.pk = None
    store.code = "OTHER-STORE"
    store.save()
    assert not run_import(user, "gcash", xlsx("gcash", [data]), None)["results"][0]["valid"]
