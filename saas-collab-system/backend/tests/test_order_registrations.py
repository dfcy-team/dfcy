import io
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.common.exceptions import StateConflict
from apps.products.models import ProductSKU, ProductSPU
from apps.sales_management.registration_models import OrderRegistration, PendingOrderDetail
from apps.sales_management.registration_services import (create_registration, edit_registration, registration_action,
                                                        representation, upload_evidence)
from apps.workflows.services import review_approval
from tests.test_sales_management import create_scope, create_order, user_for, grant, client_for

pytestmark = pytest.mark.django_db


@pytest.fixture
def context():
    tenant, _, store, _ = create_scope("registrations")
    order = create_order(tenant, store, "register")
    order.normalized_status = "confirmed"
    order.save()
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="REGISTER", product_name="登记商品")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="001")
    item = order.items.get()
    item.internal_sku = sku
    item.internal_spu = spu
    item.save()
    creator, reviewer = user_for(tenant, "registrar"), user_for(tenant, "reviewer")
    for user in (creator, reviewer):
        for prefix in ("sales_management.exchange", "sales_management.promotion", "finance.gcash"):
            for action in ("view", "create", "edit", "submit", "approve", "import", "export"):
                grant(user, f"{prefix}.{action}")
    return creator, reviewer, store, order, sku


def exchange(context, key="exchange"):
    creator, _, store, order, sku = context
    return create_registration(creator, "exchange", store.id, order.id,
                               {"changes": [{"action": "add", "new_sku_id": sku.id, "add_quantity": 1}], "reason": "增加同款"}, key)[0]


def test_exchange_repeated_adjustment_preserves_platform_facts(context):
    creator, reviewer, _, order, sku = context
    original = order.items.get().quantity
    row = exchange(context)
    registration_action(creator, "exchange", row.pk, "submit")
    completed = registration_action(reviewer, "exchange", row.pk, "approve")
    assert completed.status == "completed"
    assert PendingOrderDetail.objects.get(order=order).lines == [{"sku_id": sku.pk, "quantity": original + 1}]
    assert order.items.get().quantity == original
    second = exchange(context, "second")
    assert second.snapshot["after"][0]["quantity"] == original + 2
    with pytest.raises(StateConflict):
        registration_action(reviewer, "exchange", row.pk, "approve")


def test_exchange_one_open_and_self_approval_forbidden(context):
    creator, _, _, _, _ = context
    row = exchange(context)
    with pytest.raises(StateConflict):
        exchange(context, "duplicate")
    row = registration_action(creator, "exchange", row.pk, "submit")
    with pytest.raises(PermissionDenied):
        review_approval(approval=row.approval, actor=creator, action="approve")
    with pytest.raises(StateConflict):
        edit_registration(creator, "exchange", row.pk, {"reason": "篡改"}, row.version)


def test_cancelled_order_cannot_be_approved_via_generic_approval(context):
    creator, reviewer, _, order, _ = context
    row = registration_action(creator, "exchange", exchange(context).pk, "submit")
    order.normalized_status = "cancelled"
    order.save()
    with pytest.raises(StateConflict):
        review_approval(approval=row.approval, actor=reviewer, action="approve")
    row.refresh_from_db()
    assert row.status == "pending"
    row.approval.refresh_from_db()
    assert row.approval.status == "pending"


def test_failed_update_keeps_approval_but_does_not_claim_detail_completed(context):
    creator, reviewer, _, order, _ = context
    row = registration_action(creator, "exchange", exchange(context).pk, "submit")
    with patch.object(PendingOrderDetail, "save", side_effect=RuntimeError("storage failure")):
        registration_action(reviewer, "exchange", row.pk, "approve")
    row.refresh_from_db()
    assert row.status == "update_failed" and row.approval.status == "approved"
    assert not PendingOrderDetail.objects.get(order=order).adjusted
    assert representation(row, reviewer)["detail_updated"] is False
    result = registration_action(reviewer, "exchange", row.pk, "apply", expected_version=row.version)
    assert result.status == "completed"
    assert PendingOrderDetail.objects.get(order=order).lines[0]["quantity"] == 3


def test_promotion_snapshot_and_idempotency(context):
    creator, reviewer, store, order, _ = context
    data = {"order_amount": "100", "fee_amount": "10", "fee_currency": "CNY", "exchange_rate": "8", "rate_date": "2026-10-13", "rate_source": "人工"}
    row, created = create_registration(creator, "promotion", store.id, order.id, data, "promotion")
    assert created and row.payload["cost"] == "180.00"
    assert create_registration(creator, "promotion", store.id, order.id, data, "promotion")[1] is False
    with patch("socket.create_connection", side_effect=AssertionError("External request forbidden")), patch("urllib.request.urlopen", side_effect=AssertionError("External request forbidden")):
        row = registration_action(creator, "promotion", row.id, "register")
    assert row.status == "registered" and row.snapshot["cost"] == "180.00" and row.approval_id is None
    with pytest.raises(StateConflict):
        registration_action(creator, "promotion", row.id, "register")


@pytest.mark.parametrize("action", ["submit", "approve", "reject"])
def test_promotion_approval_actions_are_disabled(context, action):
    creator, _, store, order, _ = context
    row, _ = create_registration(creator, "promotion", store.id, order.id,
                                 {"order_amount": "100", "fee_amount": "10", "fee_currency": "PHP", "exchange_rate": "1"}, "no-approval")
    with pytest.raises(ValidationError):
        registration_action(creator, "promotion", row.pk, action)
    row.refresh_from_db()
    assert row.status == "draft" and row.approval_id is None


def test_registered_promotion_correction_and_void_are_audited(context):
    creator, _, store, order, _ = context
    row, _ = create_registration(creator, "promotion", store.id, order.id,
                                 {"order_amount": "100", "fee_amount": "10", "fee_currency": "PHP", "exchange_rate": "1"}, "promotion-correction")
    row = registration_action(creator, "promotion", row.pk, "register")
    with pytest.raises(StateConflict):
        edit_registration(creator, "promotion", row.pk, {"fee_amount": "20"}, row.version)
    row = edit_registration(creator, "promotion", row.pk, {"fee_amount": "20"}, row.version, "更正实际服务费")
    assert row.payload["cost"] == row.snapshot["cost"] == "120.00"
    assert representation(row, creator)["audit"][-1]["masked_detail"]["before"]["cost"] == "110.00"
    with pytest.raises(StateConflict):
        registration_action(creator, "promotion", row.pk, "void")
    row = registration_action(creator, "promotion", row.pk, "void", "重复记录作废")
    assert row.status == "void" and row.approval_id is None


def test_promotion_legacy_pending_approval_must_be_withdrawn(context):
    from apps.workflows.models import ApprovalRequest
    creator, reviewer, store, order, _ = context
    row, _ = create_registration(creator, "promotion", store.id, order.id,
                                 {"order_amount": "100", "fee_amount": "10", "fee_currency": "PHP", "exchange_rate": "1"}, "legacy-promotion")
    approval = ApprovalRequest.objects.create(tenant=store.tenant, approval_type="finance", title="旧推广审批",
                                              business_type="order_registration", business_id=str(row.pk), requested_by=creator)
    row.approval, row.status = approval, "pending"
    row.save()
    with pytest.raises(StateConflict):
        registration_action(creator, "promotion", row.pk, "register")
    with pytest.raises(ValidationError):
        review_approval(approval=approval, actor=reviewer, action="approve")
    with pytest.raises(PermissionDenied):
        registration_action(reviewer, "promotion", row.pk, "withdraw")
    row = registration_action(creator, "promotion", row.pk, "withdraw")
    approval.refresh_from_db()
    assert approval.status == "withdrawn"
    row = registration_action(creator, "promotion", row.pk, "register")
    assert row.status == "registered" and row.approval_id == approval.pk


def test_promotion_registration_routes_use_edit_permission(context):
    from django.urls import resolve, Resolver404
    creator, _, store, order, _ = context
    for base in ("/api/internal/commerce/", "/api/internal/sales-management/"):
        for action in ("submit", "approve", "reject"):
            with pytest.raises(Resolver404):
                resolve(f"{base}registrations/promotion/1/{action}/")
        with pytest.raises(Resolver404):
            resolve(f"{base}registrations/promotion/batch-submit/")
        assert resolve(f"{base}registrations/promotion/1/register/").func.view_class.write_permission_code == "sales_management.promotion.edit"
    row, _ = create_registration(creator, "promotion", store.id, order.id,
                                 {"order_amount": "100", "fee_amount": "10", "fee_currency": "PHP", "exchange_rate": "1"}, "api-promotion")
    readonly = user_for(store.tenant, "promotion-readonly")
    grant(readonly, "sales_management.promotion.view")
    url = f"/api/internal/commerce/registrations/promotion/{row.pk}/register/"
    assert client_for(readonly).post(url, {"version": row.version}, format="json").status_code == 403
    assert client_for(creator).post(url, {"version": row.version}, format="json").status_code == 200


def test_old_approved_promotion_can_be_explicitly_registered(context):
    from apps.workflows.models import ApprovalRequest
    creator, _, store, order, _ = context
    row, _ = create_registration(creator, "promotion", store.id, order.id,
                                 {"order_amount": "100", "fee_amount": "10", "fee_currency": "PHP", "exchange_rate": "1"}, "old-approved-promotion")
    approval = ApprovalRequest.objects.create(tenant=store.tenant, approval_type="finance", title="旧已通过审批", status="approved",
                                              business_type="order_registration", business_id=str(row.pk), requested_by=creator)
    row.approval, row.status = approval, "approved"
    row.save()
    row = registration_action(creator, "promotion", row.pk, "register", expected_version=row.version)
    approval.refresh_from_db()
    assert row.status == "registered" and row.approval_id == approval.pk and approval.status == "approved"


def gcash(context, key="refund", kind="refund"):
    creator, _, store, order, _ = context
    return create_registration(creator, "gcash", store.id, order.id if kind == "refund" else None,
                               {"type": kind, "amount": "10", "currency": "CNY", "paid_at": "2026-10-13T10:00:00+08:00",
                                "reason": "人工退款记录", "note": "用途", "phone": "09123456789", "recipient": "测试收款人",
                                "payment_account": "account-test", "transaction_reference": "reference-test"}, key)[0]


def screenshot():
    content = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(content, format="PNG")
    return SimpleUploadedFile("proof.png", content.getvalue(), content_type="image/png")


def test_gcash_evidence_currency_duplicate_and_masking(context):
    creator, _, _, _, _ = context
    row = gcash(context)
    assert row.payload["currency"] == "CNY"
    with pytest.raises(StateConflict):
        registration_action(creator, "gcash", row.id, "register")
    upload_evidence(creator, "gcash", row.id, screenshot())
    row = registration_action(creator, "gcash", row.id, "register")
    assert row.approval_id is None
    result = representation(row, creator)
    assert result["payload"]["phone"] == "***6789" and result["evidence"] == []
    assert "09123456789" not in str(result["audit"])
    duplicate = gcash(context, "another")
    upload_evidence(creator, "gcash", duplicate.id, screenshot())
    with pytest.raises(StateConflict):
        registration_action(creator, "gcash", duplicate.id, "register")


@pytest.mark.parametrize("fields", [{}, {"payment_account": "account-test"}, {"transaction_reference": "reference-test"}])
def test_gcash_account_and_reference_are_optional_but_evidence_is_required(context, fields):
    creator, _, _, _, _ = context
    for number in range(2):
        row = gcash(context, key=f"optional-{number}", kind="other")
        row.payload.pop("payment_account")
        row.payload.pop("transaction_reference")
        row.payload.update(fields)
        row.save(update_fields=["payload"])
        with pytest.raises(StateConflict):
            registration_action(creator, "gcash", row.pk, "register")
        upload_evidence(creator, "gcash", row.pk, screenshot())
        row = registration_action(creator, "gcash", row.pk, "register", expected_version=row.version)
        assert row.status == "registered" and row.transaction_key is None and row.approval_id is None
        with pytest.raises(StateConflict):
            registration_action(creator, "gcash", row.pk, "register", expected_version=row.version)


def test_gcash_correction_requires_reason_retains_history(context):
    creator, _, _, _, _ = context
    row = gcash(context, kind="other")
    upload_evidence(creator, "gcash", row.id, screenshot())
    row = registration_action(creator, "gcash", row.id, "register")
    with pytest.raises(StateConflict):
        edit_registration(creator, "gcash", row.pk, {"amount": "11"}, row.version)
    row = edit_registration(creator, "gcash", row.pk, {"amount": "11"}, row.version, "修正录入金额")
    assert row.payload["amount"] == "11.00"
    assert representation(row, creator)["audit"][-1]["masked_detail"]["before"]["amount"] == "10.00"


def test_gcash_legacy_remark_can_be_displayed_and_replaced(context):
    creator, _, _, _, _ = context
    row = gcash(context, kind="other")
    row.payload.update(reason="原原因", note="原用途")
    row.save(update_fields=["payload"])
    displayed = representation(row, creator)
    assert displayed["payload"]["note"] == "原因：原原因；用途：原用途"
    assert "reason" not in displayed["payload"]
    row.refresh_from_db()
    assert row.payload["reason"] == "原原因"
    row = edit_registration(creator, "gcash", row.pk, {"note": "更正后的备注"}, row.version)
    assert row.payload["note"] == "更正后的备注" and "reason" not in row.payload


def test_api_cross_tenant_and_sensitive_evidence(context):
    creator, _, _, _, _ = context
    row = gcash(context)
    evidence = upload_evidence(creator, "gcash", row.id, screenshot())
    api = client_for(creator)
    assert api.get(f"/api/internal/commerce/registrations/gcash/{row.pk}/evidence/{evidence.pk}/").status_code == 403
    grant(creator, "finance.gcash.sensitive")
    assert api.get(f"/api/internal/commerce/registrations/gcash/{row.pk}/evidence/{evidence.pk}/").status_code == 200
    foreign, _, _, _ = create_scope("foreign-registration")
    user = user_for(foreign, "foreign-reader")
    grant(user, "finance.gcash.view")
    assert client_for(user).get(f"/api/internal/commerce/registrations/gcash/{row.pk}/").status_code == 404


def test_api_approval_rejects_stale_registration_version(context):
    creator, reviewer, _, _, _ = context
    row = registration_action(creator, "exchange", exchange(context).pk, "submit")
    api = client_for(reviewer)
    response = api.post(f"/api/internal/commerce/registrations/exchange/{row.id}/approve/", {"version": row.version - 1}, format="json")
    assert response.status_code == 409
    row.refresh_from_db()
    assert row.status == "pending"


def test_generic_old_approval_cannot_approve_resubmitted_content(context):
    creator, reviewer, _, _, _ = context
    row = registration_action(creator, "exchange", exchange(context).pk, "submit")
    old_approval = row.approval
    row = registration_action(creator, "exchange", row.pk, "withdraw")
    row = registration_action(creator, "exchange", row.pk, "submit")
    assert row.approval_id != old_approval.pk
    with pytest.raises(StateConflict):
        review_approval(approval=old_approval, actor=reviewer, action="approve")


def test_approved_internal_detail_survives_platform_fact_updates(context):
    creator, reviewer, _, order, _ = context
    row = registration_action(creator, "exchange", exchange(context).pk, "submit")
    registration_action(reviewer, "exchange", row.id, "approve")
    detail = PendingOrderDetail.objects.get(order=order)
    expected = detail.lines
    item = order.items.get()
    item.quantity = 10
    item.save()
    second = exchange(context, "after-sync")
    assert second.snapshot["before"] == expected


def test_read_permission_does_not_allow_create_or_other_store(context):
    creator, _, store, order, _ = context
    reader = user_for(store.tenant, "read-only-registration")
    grant(reader, "finance.gcash.view")
    row = gcash(context)
    assert client_for(reader).get(f"/api/internal/commerce/registrations/gcash/{row.id}/").status_code == 200
    assert client_for(reader).post("/api/internal/commerce/registrations/gcash/", {"store_id": store.id}, format="json").status_code == 403


def test_no_external_requests_from_internal_approval(context):
    creator, reviewer, _, _, _ = context
    with patch("socket.create_connection", side_effect=AssertionError("External request forbidden")), patch("urllib.request.urlopen", side_effect=AssertionError("External request forbidden")):
        row = registration_action(creator, "exchange", exchange(context).pk, "submit")
        registration_action(reviewer, "exchange", row.id, "approve")
