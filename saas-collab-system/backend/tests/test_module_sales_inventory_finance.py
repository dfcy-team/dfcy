from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.finance.models import FinanceAuditLog, ReconciliationException, ReconciliationMatch
from apps.finance.services import import_demo_bank_receipt, import_demo_statement, import_demo_withdrawal
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


def grant(user, code, *, scope_type=DataScope.ScopeType.ALL, config=None):
    role = Role.objects.create(tenant=user.tenant, name=code, code=f"{code}-{user.id}")
    role.permissions.add(Permission.objects.get(code=code))
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=scope_type, config=config or {})


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def seed_sources(tenant, *, platform="demo-platform-a", currency="USD", receipt_amount="975.00"):
    import_demo_statement(tenant, platform=platform, currency=currency)
    import_demo_withdrawal(tenant, platform=platform, currency=currency)
    import_demo_bank_receipt(
        tenant,
        amount=Decimal(receipt_amount),
        platform=platform,
        currency=currency,
    )


@pytest.mark.django_db
def test_finance_collections_are_paginated_and_permission_scoped():
    tenant = Tenant.objects.create(name="Finance Tenant", code="module-finance-scope")
    user = CustomUser.objects.create_user(username="scoped-finance", tenant=tenant, user_type="internal")
    grant(
        user,
        "finance.view",
        scope_type=DataScope.ScopeType.CUSTOM,
        config={"platforms": ["demo-platform-a"], "currencies": ["USD"]},
    )
    seed_sources(tenant, platform="demo-platform-a", currency="USD")
    seed_sources(tenant, platform="demo-platform-b", currency="EUR")

    response = client_for(user).get("/api/finance/statements/?page=1&page_size=10")

    assert response.status_code == 200
    assert response.json()["data"]["count"] == 1
    assert response.json()["data"]["results"][0]["platform"] == "demo-platform-a"
    assert response.json()["data"]["next"] is None


@pytest.mark.django_db
def test_finance_contract_errors_and_empty_collection():
    tenant = Tenant.objects.create(name="Finance Tenant", code="module-finance-errors")
    user = CustomUser.objects.create_user(username="finance-errors", tenant=tenant, user_type="internal")
    grant(user, "finance.view")
    grant(user, "finance.reconcile")
    client = client_for(user)

    empty = client.get("/api/finance/statements/")
    missing = client.get("/api/finance/reconciliation/matches/99999/")
    invalid = client.post(
        "/api/finance/reconciliation/run-mock/",
        {"platform": "real-platform", "currency": "USD"},
        format="json",
    )

    assert APIClient().get("/api/finance/statements/").status_code == 401
    assert empty.status_code == 200
    assert empty.json()["data"]["results"] == []
    assert missing.status_code == 404
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "BUSINESS_RULE_VIOLATION"


@pytest.mark.django_db
def test_reconciliation_action_uses_its_own_scope_and_idempotency_key():
    tenant = Tenant.objects.create(name="Finance Tenant", code="module-finance-action-scope")
    user = CustomUser.objects.create_user(username="finance-reviewer", tenant=tenant, user_type="internal")
    grant(user, "finance.view")
    grant(
        user,
        "finance.reconcile",
        scope_type=DataScope.ScopeType.CUSTOM,
        config={"platforms": ["demo-platform-a"], "currencies": ["USD"]},
    )
    seed_sources(tenant, platform="demo-platform-a", currency="USD")
    seed_sources(tenant, platform="demo-platform-b", currency="EUR")
    client = client_for(user)

    denied = client.post(
        "/api/finance/reconciliation/run-mock/",
        {"platform": "demo-platform-b", "currency": "EUR"},
        format="json",
    )
    first = client.post(
        "/api/finance/reconciliation/run-mock/",
        {"platform": "demo-platform-a", "currency": "USD"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="module-demo-key",
    )
    second = client.post(
        "/api/finance/reconciliation/run-mock/",
        {"platform": "demo-platform-a", "currency": "USD"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="module-demo-key",
    )

    assert denied.status_code == 403
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["data"]["id"] == second.json()["data"]["id"]
    assert ReconciliationMatch.objects.count() == 1


@pytest.mark.django_db
def test_exception_resolution_requires_independent_permission_and_conflicts_on_repeat():
    tenant = Tenant.objects.create(name="Finance Tenant", code="module-finance-exception")
    reconciler = CustomUser.objects.create_user(username="reconciler", tenant=tenant, user_type="internal")
    handler = CustomUser.objects.create_user(username="handler", tenant=tenant, user_type="internal")
    for user in (reconciler, handler):
        grant(user, "finance.view")
    grant(reconciler, "finance.reconcile")
    grant(handler, "finance.exception.handle")
    seed_sources(tenant, receipt_amount="970.00")
    run = client_for(reconciler).post(
        "/api/finance/reconciliation/run-mock/",
        {"platform": "demo-platform-a", "currency": "USD"},
        format="json",
    )
    exception = ReconciliationException.objects.get(reconciliation_match_id=run.json()["data"]["id"])

    denied = client_for(reconciler).post(
        f"/api/finance/reconciliation/exceptions/{exception.id}/resolve/",
        {"resolution_note": "synthetic difference reviewed"},
        format="json",
    )
    resolved = client_for(handler).post(
        f"/api/finance/reconciliation/exceptions/{exception.id}/resolve/",
        {"resolution_note": "synthetic difference reviewed"},
        format="json",
    )
    repeated = client_for(handler).post(
        f"/api/finance/reconciliation/exceptions/{exception.id}/resolve/",
        {"resolution_note": "repeat"},
        format="json",
    )

    assert denied.status_code == 403
    assert resolved.status_code == 200
    assert resolved.json()["data"]["status"] == "resolved"
    assert repeated.status_code == 409
    assert FinanceAuditLog.objects.filter(action="resolve_reconciliation_exception").count() == 1


@pytest.mark.django_db
def test_finance_state_and_audit_cannot_bypass_services():
    tenant = Tenant.objects.create(name="Finance Tenant", code="module-finance-guards")
    user = CustomUser.objects.create_user(username="guard-user", tenant=tenant, user_type="internal")
    grant(user, "finance.reconcile")
    seed_sources(tenant)
    match_id = client_for(user).post(
        "/api/finance/reconciliation/run-mock/",
        {"platform": "demo-platform-a", "currency": "USD"},
        format="json",
    ).json()["data"]["id"]
    match = ReconciliationMatch.objects.get(pk=match_id)
    match.status = ReconciliationMatch.Status.CONFIRMED

    with pytest.raises(ValidationError, match="audited service"):
        match.save()
    with pytest.raises(ValidationError, match="audited service"):
        ReconciliationMatch.objects.filter(pk=match_id).update(status=ReconciliationMatch.Status.CONFIRMED)
    forged = ReconciliationMatch(
        tenant=tenant,
        statement=match.statement,
        withdrawal=match.withdrawal,
        bank_receipt=match.bank_receipt,
        matched_amount=match.matched_amount,
        difference_amount=match.difference_amount,
        status=ReconciliationMatch.Status.CONFIRMED,
    )
    with pytest.raises(ValidationError, match="audited service"):
        ReconciliationMatch.objects.bulk_create([forged])

    audit = FinanceAuditLog.objects.create(
        tenant=tenant,
        actor=user,
        action="guard-test",
        object_type="ReconciliationMatch",
        object_id=str(match_id),
    )
    audit.action = "tampered"
    with pytest.raises(ValidationError, match="immutable"):
        audit.save()
