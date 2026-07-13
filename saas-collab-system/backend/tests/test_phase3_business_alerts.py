from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.alerts.business_services import (
    assign_business_alert,
    close_business_alert,
    evaluate_business_alert,
    silence_business_alert,
)
from apps.alerts.models import (
    BusinessAlert,
    BusinessAlertActionLog,
    BusinessAlertRule,
    BusinessAlertType,
    InventoryAlertRule,
)
from apps.audit.models import OperationLog
from apps.finance.models import ReconciliationMatch
from apps.integrations.models import SyncRun
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.models import ProductLifecycleDecision
from apps.purchasing.models import PurchaseOrder
from apps.rpa.models import RPATask
from apps.tenants.models import Tenant


def create_user(tenant, username, user_type=CustomUser.UserType.INTERNAL):
    return CustomUser.objects.create_user(username=username, tenant=tenant, user_type=user_type)


def grant(user, code, scope_type=DataScope.ScopeType.ALL, config=None):
    role = Role.objects.create(tenant=user.tenant, name=code, code=f"{code}-{user.id}")
    role.permissions.add(Permission.objects.get(code=code))
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=scope_type, config=config or {})


def create_rule(tenant, alert_type=BusinessAlertType.SALES_DROP, code="SALES", version=1, threshold="2"):
    return BusinessAlertRule.objects.create(
        tenant=tenant,
        rule_code=code,
        alert_type=alert_type,
        severity=InventoryAlertRule.Severity.HIGH,
        condition_config={"operator": "gte", "threshold": threshold},
        silence_minutes=60,
        version=version,
        effective_at=timezone.now() - timedelta(minutes=1),
    )


def evaluate(rule, business_id="demo-1", **overrides):
    values = {
        "tenant": rule.tenant,
        "rule": rule,
        "business_type": "demo_product",
        "business_id": business_id,
        "metric_value": 3,
        "title": "Demo business alert",
        "detail": {"mode": "mock"},
    }
    values.update(overrides)
    return evaluate_business_alert(**values)


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
@pytest.mark.parametrize("alert_type", list(BusinessAlertType.values))
def test_business_alert_supports_all_frozen_types(alert_type):
    tenant = Tenant.objects.create(name="Tenant", code=f"business-type-{alert_type}")
    rule = create_rule(tenant, alert_type=alert_type, code=f"RULE-{alert_type}")
    alert, created = evaluate(rule)
    assert created is True
    assert alert.rule.alert_type == alert_type
    assert alert.action_logs.get().action == BusinessAlertActionLog.Action.TRIGGERED


@pytest.mark.django_db
def test_business_alert_dedup_silence_and_closed_retrigger():
    tenant = Tenant.objects.create(name="Tenant", code="business-dedup")
    rule = create_rule(tenant)
    manager = create_user(tenant, "manager")
    grant(manager, "alerts.manage")
    first, _ = evaluate(rule)
    silence_business_alert(alert=first, actor=manager, minutes=30)
    second, created = evaluate(rule, metric_value=4)
    assert created is False
    assert second.id == first.id
    assert second.status == BusinessAlert.Status.SILENCED
    assert second.action_logs.filter(action=BusinessAlertActionLog.Action.DEDUPLICATED).exists()
    close_business_alert(alert=second, actor=manager, note="Demo close.")
    reopened, created = evaluate(rule, metric_value=5)
    assert created is False
    assert reopened.status == BusinessAlert.Status.OPEN
    assert reopened.closed_at is None


@pytest.mark.django_db
def test_business_alert_rule_version_and_condition_validation():
    tenant = Tenant.objects.create(name="Tenant", code="business-rule-version")
    old = create_rule(tenant)
    latest = create_rule(tenant, version=2, threshold="5")
    with pytest.raises(ValidationError, match="not active"):
        evaluate(old)
    alert, created = evaluate(latest, metric_value=4)
    assert alert is None
    assert created is False
    latest.condition_config = {"operator": "python", "threshold": 1}
    with pytest.raises(ValidationError, match="new business alert rule version"):
        latest.save(update_fields=["condition_config", "updated_at"])
    invalid = create_rule(tenant, code="INVALID")
    BusinessAlertRule.objects.filter(pk=invalid.pk).update(is_enabled=False)
    invalid_rule = BusinessAlertRule.objects.create(
        tenant=tenant,
        rule_code="INVALID-OPERATOR",
        alert_type=BusinessAlertType.SALES_DROP,
        severity=InventoryAlertRule.Severity.HIGH,
        condition_config={"operator": "python", "threshold": 1},
        version=1,
        effective_at=timezone.now() - timedelta(minutes=1),
    )
    with pytest.raises(ValidationError, match="gt/gte"):
        evaluate(invalid_rule)


@pytest.mark.django_db
def test_business_alert_assign_close_audit_and_no_side_effects():
    tenant = Tenant.objects.create(name="Tenant", code="business-actions")
    rule = create_rule(tenant)
    manager = create_user(tenant, "manager")
    assignee = create_user(tenant, "assignee")
    grant(manager, "alerts.manage")
    alert, _ = evaluate(rule)
    alert = assign_business_alert(alert=alert, actor=manager, assignee=assignee, note="Assign demo.")
    assert alert.status == BusinessAlert.Status.ASSIGNED
    alert = close_business_alert(alert=alert, actor=manager, note="Resolved in demo.")
    assert alert.status == BusinessAlert.Status.CLOSED
    with pytest.raises(ValidationError, match="already closed"):
        close_business_alert(alert=alert, actor=manager, note="Again.")
    assert OperationLog.objects.filter(tenant=tenant, module="alerts").count() == 2
    assert RPATask.objects.count() == 0
    assert PurchaseOrder.objects.count() == 0
    assert ProductLifecycleDecision.objects.count() == 0
    assert ReconciliationMatch.objects.count() == 0
    assert SyncRun.objects.count() == 0


@pytest.mark.django_db
def test_business_alert_state_and_logs_cannot_bypass_services():
    tenant = Tenant.objects.create(name="Tenant", code="business-guard")
    rule = create_rule(tenant)
    alert, _ = evaluate(rule)
    unauthorized = create_user(tenant, "unauthorized")
    assignee = create_user(tenant, "assignee")
    with pytest.raises(PermissionDenied):
        assign_business_alert(alert=alert, actor=unauthorized, assignee=assignee)
    with pytest.raises(ValidationError, match="audited action service"):
        BusinessAlert.objects.filter(pk=alert.pk).update(status=BusinessAlert.Status.CLOSED)
    alert.status = BusinessAlert.Status.CLOSED
    with pytest.raises(ValidationError, match="audited action service"):
        alert.save()
    forged = BusinessAlertActionLog(
        tenant=tenant,
        alert=alert,
        action=BusinessAlertActionLog.Action.CLOSED,
        actor=unauthorized,
        note="forged",
    )
    with pytest.raises(ValidationError, match="audited action service"):
        forged.save()
    forged_alert = BusinessAlert(
        tenant=tenant,
        rule=rule,
        business_type="demo",
        business_id="forged",
        severity="high",
        title="Forged",
        metric_value=3,
        threshold_value=2,
        dedup_key="forged",
        triggered_at=timezone.now(),
    )
    with pytest.raises(ValidationError, match="evaluation service"):
        forged_alert.save()


@pytest.mark.django_db
def test_business_alert_api_tenant_scope_permissions_and_masking():
    tenant = Tenant.objects.create(name="Tenant", code="business-api")
    other = Tenant.objects.create(name="Other", code="business-api-other")
    rule = create_rule(tenant)
    other_rule = create_rule(other)
    visible, _ = evaluate(rule, business_id="visible", detail={"token": "not-a-real-secret", "mode": "mock"})
    evaluate(rule, business_id="hidden")
    evaluate(other_rule, business_id="other")
    viewer = create_user(tenant, "viewer")
    evaluator = create_user(tenant, "evaluator")
    manager = create_user(tenant, "manager-api")
    grant(viewer, "alerts.view", DataScope.ScopeType.CUSTOM, {"business_ids": ["visible"]})
    grant(
        evaluator,
        "alerts.evaluate",
        DataScope.ScopeType.CUSTOM,
        {"business_types": ["demo_product"], "business_ids": ["api"]},
    )
    grant(manager, "alerts.manage")

    response = client_for(viewer).get("/api/internal/alerts/business/")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]["items"]] == [visible.id]
    assert response.json()["data"]["items"][0]["detail"]["token"] == "***"
    payload = {
        "rule_id": rule.id, "business_type": "demo_product", "business_id": "api",
        "metric_value": "3.0000", "title": "Demo", "detail": {"mode": "mock"},
    }
    assert client_for(viewer).post("/api/internal/alerts/business/evaluate-mock/", payload, format="json").status_code == 403
    assert client_for(evaluator).post("/api/internal/alerts/business/evaluate-mock/", payload, format="json").status_code == 201
    before_count = BusinessAlert.objects.count()
    assert client_for(evaluator).post(
        "/api/internal/alerts/business/evaluate-mock/",
        {**payload, "business_id": "hidden"},
        format="json",
    ).status_code == 403
    assert BusinessAlert.objects.count() == before_count
    assert client_for(manager).post(
        f"/api/internal/alerts/business/{visible.id}/close/", {"note": "Reviewed"}, format="json"
    ).status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("user_type", [CustomUser.UserType.EXTERNAL, CustomUser.UserType.RPA])
def test_business_alert_api_rejects_external_and_rpa(user_type):
    tenant = Tenant.objects.create(name="Tenant", code=f"business-deny-{user_type}")
    user = create_user(tenant, f"deny-{user_type}", user_type)
    grant(user, "alerts.view")
    assert client_for(user).get("/api/internal/alerts/business/").status_code == 403
