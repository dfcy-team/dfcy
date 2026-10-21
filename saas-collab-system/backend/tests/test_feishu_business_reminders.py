import uuid
from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import InternalUserProfile
from apps.integrations.feishu_delivery import execute_delivery
from apps.integrations.models import FeishuBusinessReminder, FeishuConnection, FeishuDelivery, FeishuIdentity
from apps.masterdata.models import StoreMaster
from apps.permissions.models import DataScope, OrgMembership
from apps.tenants.models import Department
from tests.test_sales_management import client_for, create_order, create_scope, grant, user_for
from tests.test_sales_refund_filter_pagination import add_refund

BASE = "/api/internal/integrations/feishu/business-reminders/"
pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("reminder_settings")]


@pytest.fixture
def reminder_settings():
    with override_settings(FEISHU_SYSTEM_BASE_URL="https://system.example.com"):
        yield


@pytest.fixture
def scene():
    tenant, platform, store, _ = create_scope("reminder")
    actor = user_for(tenant, "reminder-leader")
    member = user_for(tenant, "reminder-member")
    outsider = user_for(tenant, "reminder-other")
    for user in (actor, member, outsider):
        grant(user, "sales_management.orders.view")
        grant(user, "sales_management.returns.view")
    department = Department.objects.create(tenant=tenant, name="运营", leader=actor)
    InternalUserProfile.objects.create(user=member, tenant=tenant, department=department)
    FeishuIdentity.objects.create(tenant=tenant, user=member, open_id="ou_member")
    FeishuIdentity.objects.create(tenant=tenant, user=outsider, open_id="ou_outsider")
    FeishuConnection.objects.create(tenant=tenant, app_id="cli_test", app_secret_ref="cred", enabled=True, created_by=actor, updated_by=actor)
    order = create_order(tenant, store, "reminder-one")
    return {"tenant": tenant, "platform": platform, "store": store, "actor": actor, "member": member, "outsider": outsider, "department": department, "order": order}


def data_for(s, **updates):
    data = {"source": "orders", "mode": "selected", "record_ids": [s["order"].pk], "filters": {},
            "recipient_user_ids": [s["member"].pk], "title": "请核查", "message": "请在系统中跟进", "due_date": "2026-10-21"}
    return {**data, **updates}


def send(s, data=None, key=None):
    client = client_for(s["actor"])
    data = data or data_for(s)
    preview = client.post(BASE + "preview/", data, format="json")
    assert preview.status_code == 200, preview.content
    payload = {**data, "preview_token": preview.json()["data"]["preview_token"], "idempotency_key": key or str(uuid.uuid4())}
    return client.post(BASE + "send/", payload, format="json"), payload


def test_leader_only_sees_department_and_descendants_are_explicit(scene):
    s = scene
    child = Department.objects.create(tenant=s["tenant"], parent=s["department"], name="子部门")
    InternalUserProfile.objects.create(user=s["outsider"], tenant=s["tenant"], department=child)
    client = client_for(s["actor"])
    assert [u["id"] for u in client.get(BASE + "options/").json()["data"]["recipients"]] == [s["member"].pk]
    s["department"].leader_include_descendants = True
    s["department"].save()
    assert len(client.get(BASE + "options/").json()["data"]["recipients"]) == 2
    s["department"].status = "inactive"
    s["department"].save()
    assert client.get(BASE + "options/").json()["data"]["can_send"] is False


def test_ordinary_member_and_cross_department_posts_rejected(scene):
    assert client_for(scene["member"]).post(BASE + "preview/", data_for(scene), format="json").status_code == 403
    response = client_for(scene["actor"]).post(BASE + "preview/", data_for(scene, recipient_user_ids=[scene["outsider"].pk]), format="json")
    assert response.status_code == 403
    other, _, _, _ = create_scope("reminder-cross")
    foreign = user_for(other, "foreign")
    assert client_for(scene["actor"]).post(BASE + "preview/", data_for(scene, recipient_user_ids=[foreign.pk]), format="json").status_code == 403


def test_preview_send_queue_idempotency_and_exact_link(scene):
    response, payload = send(scene)
    assert response.status_code == 202, response.content
    replay = client_for(scene["actor"]).post(BASE + "send/", payload, format="json")
    assert replay.status_code == 202
    assert replay.json()["data"]["replayed"]
    assert FeishuBusinessReminder.objects.count() == FeishuDelivery.objects.count() == 1
    delivery = FeishuDelivery.objects.get()
    sender = Mock()
    sender.send.return_value = "om_test"
    assert execute_delivery(delivery.pk, service=sender) == "success"
    assert execute_delivery(delivery.pk, service=sender) == "success"
    sender.send.assert_called_once()
    content = str(sender.send.call_args)
    assert "1 条记录" in content
    assert "reminder_id=" in content
    assert scene["order"].external_order_id not in content
    second = create_order(scene["tenant"], scene["store"], "reminder-two")
    response = client_for(scene["member"]).get("/api/internal/sales-management/orders/", {"reminder_id": delivery.business_reminder_id, "include_summary": "false"})
    assert response.status_code == 200, response.content
    assert [row["id"] for row in response.json()["data"]["results"]] == [scene["order"].pk]
    assert second.pk != scene["order"].pk
    assert client_for(scene["outsider"]).get("/api/internal/sales-management/orders/", {"reminder_id": delivery.business_reminder_id}).status_code == 403


def test_preview_required_and_changed_contents_do_not_reuse_key(scene):
    client = client_for(scene["actor"])
    assert client.post(BASE + "send/", {**data_for(scene), "idempotency_key": str(uuid.uuid4())}, format="json").status_code == 400
    response, payload = send(scene)
    assert response.status_code == 202
    assert client.post(BASE + "send/", {**payload, "message": "changed"}, format="json").status_code == 400


@pytest.mark.parametrize("change", ["leader", "member", "binding", "permission", "actor_permission", "connection"])
def test_revocation_after_queue_blocks_delivery(scene, change):
    response, _ = send(scene)
    assert response.status_code == 202
    if change == "leader":
        scene["department"].leader = None
        scene["department"].save()
    elif change == "member":
        InternalUserProfile.objects.filter(user=scene["member"]).update(department=None)
    elif change == "binding":
        FeishuIdentity.objects.filter(user=scene["member"]).delete()
    elif change == "permission":
        scene["member"].user_roles.all().delete()
    elif change == "actor_permission":
        scene["actor"].user_roles.all().delete()
    elif change == "connection":
        FeishuConnection.objects.update(enabled=False)
    sender = Mock()
    assert execute_delivery(FeishuDelivery.objects.get().pk, service=sender) == "failed"
    sender.send.assert_not_called()


def test_unbound_preview_and_unauthorized_selection_fail_closed(scene):
    FeishuIdentity.objects.filter(user=scene["member"]).delete()
    result = client_for(scene["actor"]).post(BASE + "preview/", data_for(scene), format="json")
    assert not result.json()["data"]["can_send"]
    assert result.json()["data"]["recipients"][0]["reason"] == "尚未绑定飞书"
    other, _, store, _ = create_scope("hidden-reminder")
    order = create_order(other, store, "hidden-reminder")
    assert client_for(scene["actor"]).post(BASE + "preview/", data_for(scene, record_ids=[order.pk]), format="json").status_code == 400


def test_filters_match_list_and_refunds_are_independent(scene):
    s = scene
    refund = add_refund(s["tenant"], s["platform"], s["store"], s["order"], "reminder-refund", "completed")
    data = data_for(s, source="returns", record_ids=[refund.pk], filters={"refund_status": "completed"})
    result, _ = send(s, data)
    assert result.status_code == 202, result.content
    data["filters"]["refund_status"] = "accepted"
    assert client_for(s["actor"]).post(BASE + "preview/", data, format="json").status_code == 400


def test_filtered_scope_is_bounded_and_does_not_load_rows(scene):
    client = client_for(scene["actor"])
    data = data_for(scene, mode="filtered", record_ids=[], filters={"date_from": "2026-08-01", "date_to": "2026-08-31"})
    with CaptureQueriesContext(connection) as queries:
        result = client.post(BASE + "preview/", data, format="json")
    assert result.status_code == 200, result.content
    assert result.json()["data"]["recipients"][0]["count"] == 1
    facts = [q["sql"] for q in queries.captured_queries if '"sales_order"' in q["sql"] and q["sql"].lstrip().upper().startswith("SELECT")]
    assert len(facts) == 2  # one sender count, one recipient intersection count
    assert all("COUNT(" in sql.upper() for sql in facts)
    assert all("LIMIT 10001" in sql.upper() for sql in facts)
    data["filters"]["date_to"] = "2026-10-01"
    assert client.post(BASE + "preview/", data, format="json").status_code == 400
    data["filters"] = {}
    assert client.post(BASE + "preview/", data, format="json").status_code == 400


def test_batch_preview_reuses_sender_count_and_never_fetches_fact_rows(scene):
    recipients = [scene["member"].pk]
    for i in range(9):
        user = user_for(scene["tenant"], f"batch-recipient-{i}")
        grant(user, "sales_management.orders.view")
        InternalUserProfile.objects.create(user=user, tenant=scene["tenant"], department=scene["department"])
        FeishuIdentity.objects.create(tenant=scene["tenant"], user=user, open_id=f"ou_batch_{i}")
        recipients.append(user.pk)
    with CaptureQueriesContext(connection) as queries:
        result = client_for(scene["actor"]).post(BASE + "preview/", data_for(scene, recipient_user_ids=recipients), format="json")
    assert result.status_code == 200, result.content
    assert len(result.json()["data"]["recipients"]) == 10
    facts = [q["sql"] for q in queries.captured_queries if '"sales_order"' in q["sql"] and q["sql"].lstrip().upper().startswith("SELECT")]
    assert len(facts) == 2  # sender once + one identical authorized recipient predicate
    assert all("COUNT(" in sql.upper() and "LIMIT 10001" in sql.upper() for sql in facts)


def test_failed_delivery_has_owned_status_and_retry(scene):
    response, _ = send(scene)
    reminder_id = response.json()["data"]["id"]
    sender = Mock()
    sender.send.side_effect = RuntimeError("temporary")
    delivery = FeishuDelivery.objects.get()
    assert execute_delivery(delivery.pk, service=sender) == "failed"
    client = client_for(scene["actor"])
    status = client.get(BASE + f"{reminder_id}/")
    assert status.json()["data"]["items"][0]["can_retry"]
    assert client.post(BASE + f"{reminder_id}/", {"operation_id": delivery.operation_id}, format="json").status_code == 202
    assert client_for(scene["outsider"]).get(BASE + f"{reminder_id}/").status_code == 403


def test_department_membership_authorization_is_kept_for_delivery_and_link(scene):
    member = scene["member"]
    membership = OrgMembership.objects.create(tenant=scene["tenant"], user=member, department=scene["department"])
    for binding in member.user_roles.all():
        binding.membership = membership
        binding.context_key = f"department:{scene['department'].pk}"
        binding.save()
    response, _ = send(scene)
    assert response.status_code == 202, response.content
    delivery = FeishuDelivery.objects.get()
    assert delivery.payload["recipient_membership_id"] == membership.pk
    sender = Mock()
    sender.send.return_value = "om_membership"
    assert execute_delivery(delivery.pk, service=sender) == "success"
    assert f"reminder_membership={membership.pk}" in str(sender.send.call_args)
    member._active_membership_id = membership.pk
    result = client_for(member).get("/api/internal/sales-management/orders/", {"reminder_id": delivery.business_reminder_id, "include_summary": "false"})
    assert result.status_code == 200, result.content
    assert result.json()["data"]["count"] == 1


def test_membership_revoked_after_preview_blocks_send(scene):
    membership = OrgMembership.objects.create(tenant=scene["tenant"], user=scene["member"], department=scene["department"])
    for binding in scene["member"].user_roles.all():
        binding.membership = membership
        binding.context_key = f"department:{scene['department'].pk}"
        binding.save()
    client = client_for(scene["actor"])
    data = data_for(scene)
    result = client.post(BASE + "preview/", data, format="json")
    assert result.json()["data"]["can_send"]
    membership.status = "inactive"
    membership.save()
    result = client.post(BASE + "send/", {**data, "idempotency_key": str(uuid.uuid4()), "preview_token": result.json()["data"]["preview_token"]}, format="json")
    assert result.status_code == 400
    assert not FeishuDelivery.objects.exists()


def test_recipient_scope_intersection_and_current_filters(scene):
    s = scene
    other_store = StoreMaster.objects.create(tenant=s["tenant"], platform=s["platform"], name="Other", code="other-local", country_code="PH", currency="PHP", timezone="Asia/Manila")
    hidden = create_order(s["tenant"], other_store, "other-store")
    for scope in DataScope.objects.filter(role__user_roles__user=s["member"]):
        scope.scope_type = "custom"
        scope.config = {"store_ids": [s["store"].pk]}
        scope.save()
    client = client_for(s["actor"])
    selected = data_for(s, record_ids=[s["order"].pk, hidden.pk])
    response = client.post(BASE + "preview/", selected, format="json")
    assert not response.json()["data"]["can_send"]
    filtered = data_for(s, mode="filtered", record_ids=[], filters={"date_from": "2026-08-01", "date_to": "2026-08-31"})
    response = client.post(BASE + "preview/", filtered, format="json")
    assert response.json()["data"]["recipients"][0]["count"] == 1
    filtered["filters"]["status"] = "cancelled"
    assert client.post(BASE + "preview/", filtered, format="json").status_code == 400


@pytest.mark.parametrize("source", ["orders", "returns"])
def test_reminder_detail_default_never_computes_unselected_summary(scene, source):
    create_order(scene["tenant"], scene["store"], "not-selected")
    payload = data_for(scene)
    route = "/api/internal/sales-management/orders/"
    if source == "returns":
        selected = add_refund(scene["tenant"], scene["platform"], scene["store"], scene["order"], "selected-refund", "completed")
        add_refund(scene["tenant"], scene["platform"], scene["store"], scene["order"], "other-refund", "completed")
        payload = data_for(scene, source="returns", record_ids=[selected.pk])
        route = "/api/internal/sales-management/refunds/"
    response, _ = send(scene, payload)
    assert response.status_code == 202, response.content
    reminder_id = response.json()["data"]["id"]
    with patch("apps.sales_management.views._sales_page_context", side_effect=AssertionError("unselected summary must not run")):
        result = client_for(scene["member"]).get(route, {"reminder_id": reminder_id})
    assert result.status_code == 200, result.content
    assert result.json()["data"]["count"] == 1
    assert "summary_metrics" not in result.json()["data"]
    assert "quality" not in result.json()["data"]


def test_retry_after_safe_window_is_rejected_and_explained(scene):
    response, _ = send(scene)
    reminder_id = response.json()["data"]["id"]
    delivery = FeishuDelivery.objects.get()
    sender = Mock()
    sender.send.side_effect = RuntimeError("temporary")
    assert execute_delivery(delivery.pk, service=sender) == "failed"
    FeishuDelivery.objects.filter(pk=delivery.pk).update(created_at=timezone.now() - timedelta(minutes=46))
    client = client_for(scene["actor"])
    status = client.get(BASE + f"{reminder_id}/").json()["data"]["items"][0]
    assert not status["can_retry"]
    assert "45分钟" in status["retry_blocked_reason"]
    retry = client.post(BASE + f"{reminder_id}/", {"operation_id": delivery.operation_id}, format="json")
    assert retry.status_code == 400
    sender.send.assert_called_once()


def test_view_permission_without_data_scope_is_ineligible_not_server_error(scene):
    DataScope.objects.filter(role__user_roles__user=scene["member"]).delete()
    result = client_for(scene["actor"]).post(BASE + "preview/", data_for(scene), format="json")
    assert result.status_code == 200, result.content
    assert not result.json()["data"]["can_send"]
    assert not result.json()["data"]["recipients"][0]["eligible"]


def test_count_cache_never_merges_different_recipient_scopes(scene):
    s = scene
    other = StoreMaster.objects.create(tenant=s["tenant"], platform=s["platform"], name="Cache other", code="cache-other", country_code="PH", currency="PHP", timezone="Asia/Manila")
    create_order(s["tenant"], other, "cache-other")
    InternalUserProfile.objects.create(user=s["outsider"], tenant=s["tenant"], department=s["department"])
    DataScope.objects.filter(role__user_roles__user=s["member"]).update(scope_type="custom", config={"store_ids": [s["store"].pk]})
    data = data_for(s, mode="filtered", record_ids=[], recipient_user_ids=[s["member"].pk, s["outsider"].pk], filters={"date_from": "2026-08-01", "date_to": "2026-08-31"})
    with CaptureQueriesContext(connection) as queries:
        result = client_for(s["actor"]).post(BASE + "preview/", data, format="json")
    assert result.status_code == 200, result.content
    items = {item["user_id"]: item for item in result.json()["data"]["recipients"]}
    assert items[s["member"].pk]["count"] == 1
    assert items[s["outsider"].pk]["count"] == 2
    facts = [q for q in queries.captured_queries if '"sales_order"' in q["sql"] and q["sql"].lstrip().upper().startswith("SELECT")]
    assert len(facts) == 3
