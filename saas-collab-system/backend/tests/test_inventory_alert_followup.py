from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.alerts.models import InventoryAlert, InventoryAlertRule
from apps.alerts.services import evaluate_inventory_alert
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.models import ProductSKU, ProductSPU
from apps.tenants.models import Tenant


def user(tenant, name, user_type=CustomUser.UserType.INTERNAL):
    return CustomUser.objects.create_user(username=name, tenant=tenant, user_type=user_type)


def grant(person, code, scope=DataScope.ScopeType.ALL, config=None):
    role = Role.objects.create(tenant=person.tenant, name=code, code=f"{code}-{person.id}")
    permission, _ = Permission.objects.get_or_create(
        code=code, defaults={"name": code, "module": "alerts", "action": code.split(".")[-1]},
    )
    role.permissions.add(permission)
    UserRole.objects.create(tenant=person.tenant, user=person, role=role)
    DataScope.objects.create(tenant=person.tenant, role=role, scope_type=scope, config=config or {})


def make_alert(tenant, suffix="A"):
    spu = ProductSPU.objects.create(tenant=tenant, spu_code=f"SPU-{suffix}", product_name="Demo product")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code=f"SKU-{suffix}", legacy_sku_code=f"OLD-{suffix}")
    rule = InventoryAlertRule.objects.create(
        tenant=tenant, rule_code=f"RULE-{suffix}", alert_type="stockout_risk", threshold_config={"coverage_days": 7},
        severity="high", version=1, effective_at=timezone.now() - timedelta(minutes=1),
    )
    alert, _ = evaluate_inventory_alert(
        tenant=tenant, rule=rule, sku=sku, warehouse_code="WH-1", available_stock=5,
        in_transit_stock=0, average_daily_sales=1,
    )
    return alert


def client(person):
    result = APIClient()
    result.force_authenticate(person)
    return result


@pytest.mark.django_db
def test_followup_api_updates_audits_and_closes_with_result():
    tenant = Tenant.objects.create(name="Tenant", code="followup-success")
    alert = make_alert(tenant)
    manager, assignee = user(tenant, "manager"), user(tenant, "assignee")
    grant(manager, "alerts.manage")
    grant(manager, "alerts.view")
    api = client(manager)

    response = api.get("/api/internal/alerts/inventory/")
    item = response.json()["data"]["results"][0]
    assert item["sku_code"] == "SKU-A"
    assert item["legacy_sku_code"] == "OLD-A"
    assert item["product_name"] == "Demo product"
    updated = api.patch(f"/api/internal/alerts/inventory/{alert.id}/follow-up/", {
        "expected_version": 1, "assigned_to_id": assignee.id, "action_plan": "Check replenishment window",
        "due_date": "2026-10-20", "status": "in_progress",
    }, format="json")
    assert updated.status_code == 200
    data = updated.json()["data"]
    assert (data["version"], data["status"], data["assigned_to_name"]) == (2, "in_progress", "assignee")
    event = alert.events.get(event_type="follow_up_updated")
    assert event.detail["before"]["version"] == 1
    assert event.detail["after"]["action_plan"] == "Check replenishment window"

    closed = api.post(f"/api/internal/alerts/inventory/{alert.id}/close/", {
        "expected_version": 2, "reason": "Replenishment confirmed",
    }, format="json")
    assert closed.status_code == 200
    assert closed.json()["data"]["resolution"] == "Replenishment confirmed"
    assert closed.json()["data"]["version"] == 3
    blocked = api.patch(f"/api/internal/alerts/inventory/{alert.id}/follow-up/", {
        "expected_version": 3, "action_plan": "late update",
    }, format="json")
    assert blocked.status_code == 422


@pytest.mark.django_db
def test_followup_api_protects_tenant_scope_role_versions_and_assignees():
    tenant = Tenant.objects.create(name="Tenant", code="followup-guards")
    other = Tenant.objects.create(name="Other", code="followup-guards-other")
    alert = make_alert(tenant, "GUARD")
    hidden_alert = make_alert(tenant, "HIDDEN")
    other_alert = make_alert(other, "OTHER")
    manager = user(tenant, "scoped-manager")
    assignee = user(tenant, "assignee")
    external = user(tenant, "external", CustomUser.UserType.EXTERNAL)
    grant(manager, "alerts.manage", DataScope.ScopeType.CUSTOM, {"sku_ids": [alert.sku_id]})
    api = client(manager)
    url = f"/api/internal/alerts/inventory/{alert.id}/follow-up/"

    assert api.patch(url, {"expected_version": 1, "action_plan": "Plan"}, format="json").status_code == 200
    assert api.patch(url, {"expected_version": 1, "action_plan": "stale"}, format="json").status_code == 409
    assert api.patch(f"/api/internal/alerts/inventory/{hidden_alert.id}/follow-up/", {"expected_version": 1, "action_plan": "x"}, format="json").status_code == 404
    assert api.patch(f"/api/internal/alerts/inventory/{other_alert.id}/follow-up/", {"expected_version": 1, "action_plan": "x"}, format="json").status_code == 404
    invalid_assignee = api.patch(url, {"expected_version": 2, "assigned_to_id": external.id}, format="json")
    assert invalid_assignee.status_code == 404

    viewer = user(tenant, "readonly")
    grant(viewer, "alerts.view")
    assert client(viewer).patch(url, {"expected_version": 2, "action_plan": "blocked"}, format="json").status_code == 403
    guest = user(tenant, "supplier", CustomUser.UserType.EXTERNAL)
    grant(guest, "alerts.manage")
    assert client(guest).get("/api/internal/alerts/inventory/assignees/").status_code == 403

    unscoped_manager = user(tenant, "no-data")
    grant(unscoped_manager, "alerts.manage", DataScope.ScopeType.CUSTOM, {"sku_ids": []})
    options = client(unscoped_manager).get("/api/internal/alerts/inventory/assignees/")
    assert options.status_code == 200
    assert options.json()["data"] == []
