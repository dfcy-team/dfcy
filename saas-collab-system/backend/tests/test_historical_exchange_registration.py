from unittest.mock import patch

import pytest
from rest_framework.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.common.exceptions import StateConflict
from apps.products.models import ProductSKU
from apps.sales_management.registration_import import run_import
from apps.sales_management.registration_models import OrderRegistration, PendingOrderDetail
from apps.sales_management.registration_services import create_registration, registration_action, apply_exchange_detail, representation
from apps.workflows.models import ApprovalRequest, WorkflowAuditEvent
from tests.test_order_registrations import context
from tests.test_registration_import import xlsx

pytestmark = pytest.mark.django_db


def payload(sku, other, quantity=1):
    return {"changes": [{"action": "replace", "old_sku_id": sku.pk, "reduce_quantity": quantity,
                         "new_sku_id": other.pk, "add_quantity": quantity}], "reason": "历史换货补录"}


@pytest.mark.parametrize("status", ["completed", "cancelled", "confirmed"])
def test_historical_exchange_records_facts_without_execution(context, status):
    user, _, store, order, sku = context
    order.normalized_status = status
    order.save()
    other = ProductSKU.objects.create(tenant=user.tenant, spu=sku.spu, sku_code="HISTORY-NEW")
    original = list(order.items.values_list("pk", "internal_sku_id", "quantity"))
    with patch("apps.sales_management.registration_services.pending_detail", side_effect=AssertionError("No pending detail writes")):
        row, created = create_registration(user, "exchange", store.pk, order.pk, payload(sku, other), "history", historical=True)
    assert created and row.status == "historical_recorded"
    assert row.approval_id is None and row.active_exchange_order_id is None
    assert row.snapshot["historical"] and row.snapshot["detail_applied"] is False
    assert row.snapshot["order_status"] == status
    assert not PendingOrderDetail.objects.exists() and not ApprovalRequest.objects.exists()
    order.refresh_from_db()
    assert order.normalized_status == status
    assert list(order.items.values_list("pk", "internal_sku_id", "quantity")) == original
    assert WorkflowAuditEvent.objects.filter(resource_id=str(row.pk), action="historical_record", actor=user).exists()
    assert create_registration(user, "exchange", store.pk, order.pk, payload(sku, other), "history", historical=True)[1] is False
    with pytest.raises(StateConflict):
        create_registration(user, "exchange", store.pk, order.pk, payload(sku, other), "history")
    for action in ["submit", "approve", "apply", "cancel"]:
        with pytest.raises(StateConflict):
            registration_action(user, "exchange", row.pk, action)
    with pytest.raises(StateConflict):
        apply_exchange_detail(user, row.pk)


def test_history_still_checks_original_quantity_and_sku_tenant(context):
    user, _, store, order, sku = context
    other = ProductSKU.objects.create(tenant=user.tenant, spu=sku.spu, sku_code="HISTORY-NEW")
    for data in [payload(sku, other, 999), payload(other, sku), payload(sku, other)]:
        if data == payload(sku, other):
            other.is_active = False
            other.save()
        with pytest.raises(ValidationError):
            create_registration(user, "exchange", store.pk, order.pk, data, "invalid", historical=True)
    assert not OrderRegistration.objects.exists() and not PendingOrderDetail.objects.exists()


def test_history_import_requires_matching_mode_and_is_idempotent(context):
    user, _, store, order, sku = context
    order.normalized_status = "completed"
    order.save()
    data = [{"store_code": store.code, "order_number": order.external_order_id, "group": "DB_EX_TEST",
             "action": "增加", "new_sku": sku.sku_code, "add_quantity": 1, "reason": "历史补录"}]
    content = xlsx("exchange", data).read()
    upload = lambda: SimpleUploadedFile("registration.xlsx", content)
    preview = run_import(user, "exchange", upload(), None, historical=True)
    assert preview["results"][0]["valid"] and not OrderRegistration.objects.exists()
    with pytest.raises(ValidationError):
        run_import(user, "exchange", upload(), None, confirm=True, expected_hash=preview["file_hash"])
    for _ in range(2):
        result = run_import(user, "exchange", upload(), None, historical=True,
                            confirm=True, expected_hash=preview["file_hash"])
        assert result["results"][0]["valid"]
    row = OrderRegistration.objects.get()
    assert row.status == "historical_recorded" and row.snapshot["import_source"]["group"] == "DB_EX_TEST"
    assert not PendingOrderDetail.objects.exists()


def test_exchange_representation_resolves_new_and_inactive_snapshot_skus(context):
    user, _, store, order, sku = context
    other = ProductSKU.objects.create(tenant=user.tenant, spu=sku.spu, sku_code="HISTORY-NEW", legacy_sku_code="OLD-NEW")
    row, _ = create_registration(user, "exchange", store.pk, order.pk, payload(sku, other), "labels", historical=True)
    original = row.snapshot.copy()
    other.is_active = False
    other.save()
    data = representation(row, user)
    labels = {item["id"]: item["sku_code"] for item in data["sku_details"]}
    assert labels == {sku.pk: sku.sku_code, other.pk: "HISTORY-NEW"}
    row.refresh_from_db()
    assert row.snapshot == original
