from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.alerts.models import InventoryAlert, InventoryAlertEvent, InventoryAlertRule, InventoryAlertType
from apps.alerts.services import (
    assign_inventory_alert,
    close_inventory_alert,
    evaluate_inventory_alert,
    silence_inventory_alert,
)
from apps.audit.models import OperationLog
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.models import ProductSKU, ProductSPU
from apps.purchasing.models import PurchaseOrder
from apps.rpa.models import RPATask
from apps.tenants.models import Tenant


def create_sku(tenant, suffix):
    spu = ProductSPU.objects.create(tenant=tenant, spu_code=f"SPU-{suffix}", product_name="Demo product")
    return ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code=f"SKU-{suffix}")


def create_rule(tenant, code="STOCKOUT", alert_type=InventoryAlertType.STOCKOUT_RISK, threshold="7"):
    return InventoryAlertRule.objects.create(
        tenant=tenant,
        rule_code=code,
        alert_type=alert_type,
        threshold_config={"average_daily_sales" if alert_type == InventoryAlertType.SLOW_MOVING else "coverage_days": threshold},
        severity=InventoryAlertRule.Severity.HIGH,
        silence_minutes=60,
        version=1,
        effective_at=timezone.now() - timedelta(minutes=1),
    )


def create_user(tenant, username, user_type=CustomUser.UserType.INTERNAL):
    return CustomUser.objects.create_user(username=username, tenant=tenant, user_type=user_type)


def grant(user, permission_code, scope_type=DataScope.ScopeType.ALL, config=None):
    role = Role.objects.create(tenant=user.tenant, name=permission_code, code=f"{permission_code}-{user.id}")
    role.permissions.add(Permission.objects.get(code=permission_code))
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=scope_type, config=config or {})


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def evaluate(rule, sku, **overrides):
    values = {
        "tenant": rule.tenant,
        "rule": rule,
        "sku": sku,
        "warehouse_code": "DEMO-WH",
        "available_stock": 5,
        "in_transit_stock": 0,
        "average_daily_sales": 1,
    }
    values.update(overrides)
    return evaluate_inventory_alert(**values)


@pytest.mark.django_db
def test_inventory_alert_rule_versions_and_four_rule_types():
    tenant = Tenant.objects.create(name="Tenant", code="inventory-rules")
    sku = create_sku(tenant, "RULES")
    stockout = create_rule(tenant)
    overstock = create_rule(tenant, "OVER", InventoryAlertType.OVERSTOCK_RISK, "45")
    low = create_rule(tenant, "LOW", InventoryAlertType.LOW_COVERAGE, "10")
    slow = create_rule(tenant, "SLOW", InventoryAlertType.SLOW_MOVING, "0.2")
    latest_stockout = InventoryAlertRule.objects.create(
        tenant=tenant, rule_code=stockout.rule_code, alert_type=stockout.alert_type,
        threshold_config={"coverage_days": "8"}, severity="medium", silence_minutes=30,
        version=2, effective_at=timezone.now(),
    )

    with pytest.raises(ValidationError, match="not active"):
        evaluate(stockout, sku)
    assert evaluate(latest_stockout, sku)[0].alert_type == InventoryAlertType.STOCKOUT_RISK
    assert evaluate(overstock, sku, warehouse_code="OVER", available_stock=100)[0].alert_type == InventoryAlertType.OVERSTOCK_RISK
    assert evaluate(low, sku, warehouse_code="LOW")[0].alert_type == InventoryAlertType.LOW_COVERAGE
    assert evaluate(slow, sku, warehouse_code="SLOW", average_daily_sales="0.1")[0].alert_type == InventoryAlertType.SLOW_MOVING
    assert InventoryAlertRule.objects.filter(tenant=tenant, rule_code="STOCKOUT").count() == 2


@pytest.mark.django_db
def test_inventory_alert_dedup_and_silence_cycle():
    tenant = Tenant.objects.create(name="Tenant", code="inventory-dedup")
    sku = create_sku(tenant, "DEDUP")
    rule = create_rule(tenant)
    actor = create_user(tenant, "alert-manager")
    first, created = evaluate(rule, sku)
    silence_inventory_alert(alert=first, actor=actor, minutes=30)
    second, duplicate_created = evaluate(rule, sku, available_stock=4)

    assert created is True
    assert duplicate_created is False
    assert first.id == second.id
    assert second.status == InventoryAlert.Status.SILENCED
    assert second.silenced_until > timezone.now()
    assert InventoryAlert.objects.count() == 1
    assert second.events.filter(event_type=InventoryAlertEvent.EventType.DEDUPLICATED).exists()
    assert second.events.get(event_type=InventoryAlertEvent.EventType.DEDUPLICATED).detail["notification_suppressed"] is True


@pytest.mark.django_db
def test_inventory_alert_assignment_close_and_audit_state_transitions():
    tenant = Tenant.objects.create(name="Tenant", code="inventory-actions")
    sku = create_sku(tenant, "ACTIONS")
    rule = create_rule(tenant)
    actor = create_user(tenant, "actor")
    assignee = create_user(tenant, "assignee")
    alert, _ = evaluate(rule, sku)

    alert = assign_inventory_alert(alert=alert, actor=actor, assignee=assignee)
    assert alert.status == InventoryAlert.Status.ASSIGNED
    assert alert.assigned_to == assignee
    alert = close_inventory_alert(alert=alert, actor=actor, reason="Demo risk reviewed.")
    assert alert.status == InventoryAlert.Status.CLOSED
    assert alert.closed_at is not None
    with pytest.raises(ValidationError):
        close_inventory_alert(alert=alert, actor=actor, reason="Again")
    reopened, created = evaluate(rule, sku)
    assert created is False
    assert reopened.status == InventoryAlert.Status.OPEN
    assert reopened.closed_at is None
    assert reopened.assigned_to is None
    assert alert.events.filter(event_type=InventoryAlertEvent.EventType.ASSIGNED).exists()
    assert alert.events.filter(event_type=InventoryAlertEvent.EventType.CLOSED).exists()
    assert OperationLog.objects.filter(tenant=tenant, module="alerts").count() == 2


@pytest.mark.django_db
def test_inventory_alert_tenant_validation_and_no_business_side_effects():
    tenant = Tenant.objects.create(name="Tenant", code="inventory-tenant")
    other = Tenant.objects.create(name="Other", code="inventory-tenant-other")
    rule = create_rule(tenant)
    other_sku = create_sku(other, "OTHER")
    with pytest.raises(ValidationError):
        evaluate(rule, other_sku)
    assert PurchaseOrder.objects.count() == 0
    assert RPATask.objects.count() == 0


@pytest.mark.django_db
def test_inventory_alert_api_tenant_data_scope_and_action_permissions():
    tenant = Tenant.objects.create(name="Tenant", code="inventory-api")
    other = Tenant.objects.create(name="Other", code="inventory-api-other")
    sku = create_sku(tenant, "VISIBLE")
    hidden_sku = create_sku(tenant, "HIDDEN")
    other_sku = create_sku(other, "OTHER")
    rule = create_rule(tenant)
    other_rule = create_rule(other)
    visible, _ = evaluate(rule, sku)
    evaluate(rule, hidden_sku, warehouse_code="HIDDEN")
    evaluate(other_rule, other_sku)
    viewer = create_user(tenant, "viewer")
    evaluator = create_user(tenant, "evaluator")
    manager = create_user(tenant, "manager")
    grant(
        viewer,
        "alerts.view",
        DataScope.ScopeType.CUSTOM,
        {"sku_ids": [sku.id], "warehouse_codes": ["DEMO-WH"]},
    )
    grant(viewer, "analytics.view")
    grant(
        evaluator,
        "alerts.evaluate",
        DataScope.ScopeType.CUSTOM,
        {"sku_ids": [sku.id], "warehouse_codes": ["DEMO-WH"]},
    )
    grant(manager, "alerts.manage")
    payload = {
        "rule_id": rule.id, "sku_id": sku.id, "warehouse_code": "DEMO-WH",
        "available_stock": "3.0000", "in_transit_stock": "0.0000", "average_daily_sales": "1.0000",
    }

    response = client_for(viewer).get("/api/internal/alerts/inventory/")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]["results"]] == [visible.id]
    assert response.json()["data"]["count"] == 1
    assert client_for(viewer).post("/api/internal/alerts/inventory/evaluate-mock/", payload, format="json").status_code == 403
    assert client_for(evaluator).post("/api/internal/alerts/inventory/evaluate-mock/", payload, format="json").status_code == 200
    before_count = InventoryAlert.objects.count()
    blocked_payload = {**payload, "sku_id": hidden_sku.id, "warehouse_code": "HIDDEN"}
    assert client_for(evaluator).post(
        "/api/internal/alerts/inventory/evaluate-mock/", blocked_payload, format="json"
    ).status_code == 403
    assert InventoryAlert.objects.count() == before_count
    assert client_for(manager).post(
        f"/api/internal/alerts/inventory/{visible.id}/close/", {"reason": "Reviewed"}, format="json"
    ).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("user_type", [CustomUser.UserType.EXTERNAL, CustomUser.UserType.RPA])
def test_inventory_alert_api_rejects_external_and_rpa(user_type):
    tenant = Tenant.objects.create(name="Tenant", code=f"inventory-deny-{user_type}")
    user = create_user(tenant, f"deny-{user_type}", user_type)
    grant(user, "alerts.view")
    assert client_for(user).get("/api/internal/alerts/inventory/").status_code == 403


@pytest.mark.django_db
def test_inventory_alert_api_rejects_unauthenticated():
    assert APIClient().get("/api/internal/alerts/inventory/").status_code == 401
