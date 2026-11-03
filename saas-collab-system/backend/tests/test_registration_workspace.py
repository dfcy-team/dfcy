from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.sales_management.registration_import import run_import
from apps.sales_management.registration_models import OrderRegistration
from apps.sales_management.registration_services import create_registration
from tests.test_order_registrations import context
from tests.test_registration_import import xlsx
from tests.test_sales_management import client_for

pytestmark = pytest.mark.django_db
BASE = "/api/internal/commerce/registrations/promotion/"


def promotion(context, key):
    user, _, store, order, _ = context
    return create_registration(user, "promotion", store.pk, order.pk,
        {"order_amount": "100", "fee_amount": "10", "fee_currency": "PHP", "exchange_rate": "1"}, key)[0]


def test_list_summary_covers_filtered_results_not_only_page(context):
    first = promotion(context, "workspace-1")
    second = promotion(context, "workspace-2")
    second.status = "registered"
    second.save()
    response = client_for(context[0]).get(BASE, {"page_size": 1})
    assert response.status_code == 200
    data = response.data["data"]
    assert len(data["results"]) == 1 and data["summary"] == {"draft": 1, "registered": 1}
    filtered = client_for(context[0]).get(BASE, {"status": "draft"}).data["data"]
    assert filtered["count"] == 1 and filtered["results"][0]["id"] == first.pk
    assert filtered["summary"] == {"draft": 1}


def test_date_filter_and_export_use_same_china_calendar_bounds(context):
    included = promotion(context, "inside")
    excluded = promotion(context, "outside")
    tz = ZoneInfo("Asia/Shanghai")
    OrderRegistration.objects.filter(pk=included.pk).update(created_at=datetime(2026, 10, 15, 23, 59, tzinfo=tz))
    OrderRegistration.objects.filter(pk=excluded.pk).update(created_at=datetime(2026, 10, 16, 0, 0, tzinfo=tz))
    client = client_for(context[0])
    params = {"created_from": "2026-10-15", "created_to": "2026-10-15", "store_id": context[2].pk}
    data = client.get(BASE, params).data["data"]
    assert data["count"] == 1 and data["results"][0]["id"] == included.pk
    exported = client.get(BASE + "export/", params).content.decode("utf-8-sig")
    assert "推广服务费" in exported and "汇率来源" in exported
    assert len(exported.splitlines()) == 2
    assert client.get(BASE, {"created_from": "invalid"}).status_code == 400
    assert client.get(BASE, {"created_from": "2026-10-16", "created_to": "2026-10-15"}).status_code == 400


def test_own_import_history_and_batch_filter_are_scoped(context):
    user, other, store, order, _ = context
    row = {"store_code": store.code, "order_number": order.external_order_id, "group": "WORKSPACE",
           "order_amount": 100, "store_currency": "PHP", "fee_amount": 10, "fee_currency": "PHP", "exchange_rate": 1}
    content = xlsx("promotion", [row]).read()
    upload = lambda: SimpleUploadedFile("registration.xlsx", content)
    preview = run_import(user, "promotion", upload(), None)
    result = run_import(user, "promotion", upload(), None, confirm=True, expected_hash=preview["file_hash"])
    client = client_for(user)
    history = client.get(BASE + "imports/")
    assert history.status_code == 200
    batch = history.data["data"]["results"][0]
    assert batch["file_name"] == "registration.xlsx" and batch["results"][0]["store_code"] == store.code
    assert "payload" not in batch["results"][0] and "file_hash" not in batch
    assert client.get(BASE, {"batch_id": batch["id"]}).data["data"]["count"] == 1
    assert client_for(other).get(BASE + "imports/").data["data"]["count"] == 0
    assert client_for(other).get(BASE, {"batch_id": batch["id"]}).status_code == 404
    again = run_import(user, "promotion", upload(), None)
    assert again["results"][0]["status"] == "existing"
    assert result["results"][0]["id"] == batch["results"][0]["id"]
    other_preview = run_import(other, "promotion", upload(), None)
    other_batch = run_import(other, "promotion", upload(), None, confirm=True, expected_hash=other_preview["file_hash"])
    assert other_batch["batch_id"] != batch["id"]
    assert OrderRegistration.objects.count() == 1
    assert client_for(other).get(BASE + "imports/").data["data"]["count"] == 1


def test_request_key_recovery_is_limited_to_creator(context):
    row = promotion(context, "recovery-key")
    assert client_for(context[0]).get(BASE, {"request_key": "recovery-key"}).data["data"]["results"][0]["id"] == row.pk
    assert client_for(context[1]).get(BASE, {"request_key": "recovery-key"}).data["data"]["count"] == 0


def test_bad_filter_identifiers_are_validation_errors_not_server_errors(context):
    client = client_for(context[0])
    for key in ("store_id", "batch_id"):
        assert client.get(BASE, {key: "invalid"}).status_code == 400


def test_lookup_reports_original_product_labels_and_readiness_without_writes(context):
    user, _, store, order, sku = context
    response = client_for(user).get("/api/internal/commerce/registrations/exchange/options/",
                                    {"store_id": store.pk, "order_number": order.external_order_id})
    data = response.data["data"]["order"]
    assert data["pending"][0]["sku_code"] == sku.sku_code
    assert data["adjustment_blockers"] == []
    assert not OrderRegistration.objects.exists()
    order.normalized_status = "cancelled"
    order.save()
    blocked = client_for(user).get("/api/internal/commerce/registrations/exchange/options/",
                                  {"store_id": store.pk, "order_number": order.external_order_id})
    assert blocked.data["data"]["order"]["adjustment_blockers"]
