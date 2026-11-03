import pytest

from apps.sales_management.registration_models import OrderRegistration
from apps.sales_management.registration_services import create_registration
from apps.workflows.models import WorkflowAuditEvent
from apps.permissions.models import DataScope
from tests.test_order_registrations import context, exchange, screenshot
from tests.test_sales_management import client_for, user_for, grant, create_scope

pytestmark = pytest.mark.django_db


def create_row(context, kind="promotion", key="soft-delete"):
    user, _, store, order, _ = context
    if kind == "exchange":
        return exchange(context, key)
    payload = {"order_amount": "100", "fee_amount": "10", "fee_currency": "PHP", "exchange_rate": "1"} if kind == "promotion" else {
        "type": "refund", "amount": "10", "currency": "PHP", "paid_at": "2026-10-15", "note": "已付退款"}
    return create_registration(user, kind, store.pk, order.pk, payload, key)[0]


@pytest.mark.parametrize("kind", ["exchange", "promotion", "gcash"])
def test_delete_hides_record_keeps_evidence_and_audit_and_can_restore(context, kind):
    row = create_row(context, kind)
    client = client_for(context[0])
    base = f"/api/internal/commerce/registrations/{kind}/"
    assert client.post(f"{base}{row.pk}/evidence/", {"file": screenshot()}, format="multipart").status_code == 200
    row.refresh_from_db()
    deleted = client.post(f"{base}{row.pk}/delete/", {"version": row.version, "note": "重复草稿"}, format="json")
    assert deleted.status_code == 200
    data = deleted.data["data"]
    assert data["deleted_at"] and data["deleted_by_name"] == context[0].username and data["delete_reason"] == "重复草稿"
    assert client.get(base).data["data"]["count"] == 0
    assert client.get(base, {"deleted": "true"}).data["data"]["count"] == 1
    assert client.get(base + "export/").content.decode("utf-8-sig").count("\n") == 1
    assert OrderRegistration.objects.get(pk=row.pk).evidence.count() == 1
    assert client.patch(f"{base}{row.pk}/", {"payload": {}, "version": data["version"]}, format="json").status_code == 403
    assert client.delete(f"{base}{row.pk}/").status_code == 405
    restored = client.post(f"{base}{row.pk}/restore/", {"version": data["version"], "note": "继续核对"}, format="json")
    assert restored.status_code == 200 and restored.data["data"]["deleted_at"] is None
    assert client.get(base).data["data"]["count"] == 1
    assert client.get(base, {"deleted": "true"}).data["data"]["count"] == 0
    assert set(WorkflowAuditEvent.objects.filter(resource_type="order_registration", resource_id=str(row.pk)).values_list("action", flat=True)) >= {"delete", "restore"}


@pytest.mark.parametrize("status", ["pending", "registered", "completed", "approved", "update_failed", "cancelled", "void"])
def test_processed_or_pending_records_cannot_be_deleted(context, status):
    row = create_row(context)
    row.status = status
    row.save()
    response = client_for(context[0]).post(f"/api/internal/commerce/registrations/promotion/{row.pk}/delete/", {"version": row.version, "note": "不允许删除"}, format="json")
    assert response.status_code == 409
    row.refresh_from_db()
    assert row.deleted_at is None


@pytest.mark.parametrize("status", ["rejected", "withdrawn"])
def test_rejected_and_withdrawn_can_be_deleted(context, status):
    row = create_row(context)
    row.status = status
    row.save()
    assert client_for(context[0]).post(f"/api/internal/commerce/registrations/promotion/{row.pk}/delete/", {"version": row.version, "note": "已停止登记"}, format="json").status_code == 200


def test_delete_checks_reason_version_and_edit_permission(context):
    row = create_row(context)
    url = f"/api/internal/commerce/registrations/promotion/{row.pk}/delete/"
    client = client_for(context[0])
    assert client.post(url, {"version": row.version, "note": " "}, format="json").status_code == 400
    assert client.post(url, {"version": 99, "note": "旧版本"}, format="json").status_code == 409
    reader = user_for(context[0].tenant, "delete-reader")
    grant(reader, "sales_management.promotion.view")
    assert client_for(reader).post(url, {"version": row.version, "note": "无权限"}, format="json").status_code == 403


def test_restore_exchange_cannot_steal_another_active_registration(context):
    row = create_row(context, "exchange")
    client = client_for(context[0])
    base = f"/api/internal/commerce/registrations/exchange/{row.pk}/"
    result = client.post(base + "delete/", {"version": row.version, "note": "先删除"}, format="json").data["data"]
    assert OrderRegistration.objects.get(pk=row.pk).active_exchange_order_id is None
    active = exchange(context, "new-active")
    response = client.post(base + "restore/", {"version": result["version"]}, format="json")
    assert response.status_code == 409
    row.refresh_from_db(); active.refresh_from_db()
    assert row.deleted_at is not None and active.active_exchange_order_id == context[3].pk


def test_batch_delete_checks_each_record_and_versions(context):
    first = create_row(context, key="batch-one")
    second = create_row(context, key="batch-two")
    second.status = "registered"; second.save()
    response = client_for(context[0]).post("/api/internal/commerce/registrations/promotion/batch-delete/", {
        "ids": [first.pk, second.pk], "versions": {str(first.pk): first.version, str(second.pk): second.version}, "note": "清理草稿"}, format="json")
    assert response.status_code == 200
    assert [row["success"] for row in response.data["data"]["results"]] == [True, False]
    assert OrderRegistration.objects.get(pk=first.pk).deleted_at is not None
    assert OrderRegistration.objects.get(pk=second.pk).deleted_at is None


def test_deleted_idempotent_request_cannot_silently_recreate_a_draft(context):
    row = create_row(context)
    client_for(context[0]).post(f"/api/internal/commerce/registrations/promotion/{row.pk}/delete/", {"version": row.version, "note": "删除重复"}, format="json")
    from apps.common.exceptions import StateConflict
    with pytest.raises(StateConflict, match="已删除"):
        create_row(context)
    assert OrderRegistration.objects.count() == 1


def test_restore_fails_for_order_that_is_no_longer_pending(context):
    row = create_row(context, "exchange")
    client = client_for(context[0]); base = f"/api/internal/commerce/registrations/exchange/{row.pk}/"
    deleted = client.post(base + "delete/", {"version": row.version, "note": "暂缓"}, format="json").data["data"]
    order = context[3]; order.normalized_status = "cancelled"; order.save()
    assert client.post(base + "restore/", {"version": deleted["version"]}, format="json").status_code == 409
    row.refresh_from_db()
    assert row.deleted_at is not None and row.active_exchange_order_id is None


def test_foreign_tenant_cannot_delete_or_restore_or_read_deleted_record(context):
    row = create_row(context)
    tenant, _, _, _ = create_scope("foreign-delete")
    user = user_for(tenant, "foreign-delete-actor")
    for action in ("view", "edit"):
        grant(user, f"sales_management.promotion.{action}")
    client = client_for(user); base = f"/api/internal/commerce/registrations/promotion/{row.pk}/"
    for action in ("delete", "restore"):
        assert client.post(base + action + "/", {"version": row.version, "note": "越权"}, format="json").status_code == 403
    assert client.get(base).status_code == 404
    assert client.get("/api/internal/commerce/registrations/promotion/", {"deleted": "true"}).data["data"]["count"] == 0


def test_restore_checks_edit_store_scope_even_if_record_is_visible(context):
    row = create_row(context)
    client_for(context[0]).post(f"/api/internal/commerce/registrations/promotion/{row.pk}/delete/", {"version": row.version, "note": "删除"}, format="json")
    row.refresh_from_db()
    user = user_for(context[0].tenant, "scoped-restore")
    grant(user, "sales_management.promotion.view")
    grant(user, "sales_management.promotion.edit", DataScope.ScopeType.CUSTOM, {"store_ids": [str(context[2].pk + 100000)]})
    client = client_for(user)
    assert client.get("/api/internal/commerce/registrations/promotion/", {"deleted": "true"}).data["data"]["count"] == 1
    assert client.post(f"/api/internal/commerce/registrations/promotion/{row.pk}/restore/", {"version": row.version}, format="json").status_code == 403
