from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.finance.models import (
    BankReceiptImport,
    FinanceAuditLog,
    PlatformStatement,
    ReconciliationException,
    ReconciliationMatch,
    WithdrawalRecord,
)
from apps.finance.services import import_demo_bank_receipt, import_demo_statement, import_demo_withdrawal
from apps.permissions.models import Permission, Role, UserRole
from apps.tenants.models import Tenant


def create_user(tenant, username, user_type=CustomUser.UserType.INTERNAL):
    return CustomUser.objects.create_user(username=username, tenant=tenant, user_type=user_type)


def grant_finance_access(user, permission_codes=None):
    role = Role.objects.create(tenant=user.tenant, name="Finance Viewer", code=f"finance-viewer-{user.id}")
    permission_codes = permission_codes or ("finance.view", "finance.import", "finance.reconcile")
    for permission_code in permission_codes:
        action = permission_code.rsplit(".", 1)[-1]
        permission, _created = Permission.objects.get_or_create(
            code=permission_code,
            defaults={
                "name": f"Finance {action}",
                "module": "finance",
                "action": action,
            },
        )
        role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)


def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def seed_demo_finance_data(tenant, receipt_amount=Decimal("975.00")):
    statement = import_demo_statement(tenant)
    withdrawal = import_demo_withdrawal(tenant)
    receipt = import_demo_bank_receipt(tenant, amount=receipt_amount, account_hint="demo-account-1234")
    return statement, withdrawal, receipt


@pytest.mark.django_db
def test_finance_user_can_import_and_list_demo_records():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "finance")
    grant_finance_access(user)
    client = authenticated_client(user)

    statement_response = client.post("/api/finance/statements/import-demo/", {}, format="json")
    withdrawal_response = client.post("/api/finance/withdrawals/import-demo/", {}, format="json")
    receipt_response = client.post(
        "/api/finance/bank-receipts/import-demo/",
        {"account_hint": "demo-account-1234"},
        format="json",
    )
    list_response = client.get("/api/finance/bank-receipts/")

    assert statement_response.status_code == 201
    assert withdrawal_response.status_code == 201
    assert receipt_response.status_code == 201
    assert receipt_response.json()["data"]["masked_account"] == "****1234"
    assert "demo-account-1234" not in str(receipt_response.json())
    assert list_response.status_code == 200
    assert len(list_response.json()["data"]) == 1


@pytest.mark.django_db
def test_finance_view_permission_cannot_import_or_reconcile():
    tenant = Tenant.objects.create(name="Tenant", code="finance-view-only")
    user = create_user(tenant, "finance-viewer")
    grant_finance_access(user, permission_codes=("finance.view",))
    seed_demo_finance_data(tenant)
    client = authenticated_client(user)

    assert client.get("/api/finance/statements/").status_code == 200
    assert client.get("/api/finance/reconciliation/matches/").status_code == 200
    assert client.post("/api/finance/statements/import-demo/", {}, format="json").status_code == 403
    assert client.post("/api/finance/withdrawals/import-demo/", {}, format="json").status_code == 403
    assert client.post("/api/finance/bank-receipts/import-demo/", {}, format="json").status_code == 403
    assert client.post("/api/finance/reconciliation/run-mock/", {}, format="json").status_code == 403
    assert client.post("/api/finance/reconciliation/matches/1/confirm/", {}, format="json").status_code == 403
    assert client.post("/api/finance/reconciliation/matches/1/reject/", {}, format="json").status_code == 403

    assert PlatformStatement.objects.filter(tenant=tenant).count() == 1
    assert ReconciliationMatch.objects.filter(tenant=tenant).count() == 0


@pytest.mark.django_db
def test_demo_import_endpoints_are_idempotent():
    tenant = Tenant.objects.create(name="Tenant", code="finance-idempotent-import")
    user = create_user(tenant, "finance-importer")
    grant_finance_access(user)
    client = authenticated_client(user)

    endpoints = (
        ("/api/finance/statements/import-demo/", {}),
        ("/api/finance/withdrawals/import-demo/", {}),
        ("/api/finance/bank-receipts/import-demo/", {"account_hint": "demo-account-1234"}),
    )
    for endpoint, payload in endpoints:
        first = client.post(endpoint, payload, format="json")
        second = client.post(endpoint, payload, format="json")
        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json()["data"]["id"] == second.json()["data"]["id"]

    assert PlatformStatement.objects.filter(tenant=tenant).count() == 1
    assert WithdrawalRecord.objects.filter(tenant=tenant).count() == 1
    assert BankReceiptImport.objects.filter(tenant=tenant).count() == 1


@pytest.mark.django_db
def test_non_finance_users_cannot_access_reconciliation_apis():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    users = [
        create_user(tenant, "plain-internal"),
        create_user(tenant, "external", CustomUser.UserType.EXTERNAL),
        create_user(tenant, "rpa", CustomUser.UserType.RPA),
    ]

    for user in users:
        response = authenticated_client(user).get("/api/finance/reconciliation/matches/")
        assert response.status_code == 403


@pytest.mark.django_db
def test_finance_queries_are_tenant_scoped():
    tenant_a = Tenant.objects.create(name="Tenant A", code="tenant-a")
    tenant_b = Tenant.objects.create(name="Tenant B", code="tenant-b")
    user_a = create_user(tenant_a, "finance-a")
    grant_finance_access(user_a)
    seed_demo_finance_data(tenant_b)

    response = authenticated_client(user_a).get("/api/finance/statements/")

    assert response.status_code == 200
    assert response.json()["data"] == []


@pytest.mark.django_db
def test_mock_reconciliation_creates_suggestion_not_final_confirmation():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "finance")
    grant_finance_access(user)
    seed_demo_finance_data(tenant)

    response = authenticated_client(user).post("/api/finance/reconciliation/run-mock/", {}, format="json")

    assert response.status_code == 201
    assert response.json()["data"]["status"] == ReconciliationMatch.Status.SUGGESTED
    assert response.json()["data"]["difference_amount"] == "0.00"
    assert ReconciliationMatch.objects.get().reviewed_by is None


@pytest.mark.django_db
def test_confirm_requires_finance_permission_and_rejects_duplicate_confirmation():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    finance_user = create_user(tenant, "finance")
    plain_user = create_user(tenant, "plain")
    grant_finance_access(finance_user)
    seed_demo_finance_data(tenant)
    match = ReconciliationMatch.objects.create(
        tenant=tenant,
        statement=PlatformStatement.objects.get(tenant=tenant),
        withdrawal=WithdrawalRecord.objects.get(tenant=tenant),
        bank_receipt=BankReceiptImport.objects.get(tenant=tenant),
        matched_amount=Decimal("975.00"),
        difference_amount=Decimal("0.00"),
        confidence=Decimal("0.9500"),
    )

    plain_response = authenticated_client(plain_user).post(
        f"/api/finance/reconciliation/matches/{match.id}/confirm/",
        {},
        format="json",
    )
    finance_response = authenticated_client(finance_user).post(
        f"/api/finance/reconciliation/matches/{match.id}/confirm/",
        {},
        format="json",
    )
    duplicate_response = authenticated_client(finance_user).post(
        f"/api/finance/reconciliation/matches/{match.id}/confirm/",
        {},
        format="json",
    )

    assert plain_response.status_code == 403
    assert finance_response.status_code == 200
    assert finance_response.json()["data"]["status"] == ReconciliationMatch.Status.CONFIRMED
    assert duplicate_response.status_code == 400
    assert FinanceAuditLog.objects.filter(action="confirm_reconciliation_match").exists()


@pytest.mark.django_db
def test_difference_amount_creates_exception_and_audit_log():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    user = create_user(tenant, "finance")
    grant_finance_access(user)
    seed_demo_finance_data(tenant, receipt_amount=Decimal("970.00"))

    response = authenticated_client(user).post("/api/finance/reconciliation/run-mock/", {}, format="json")
    exception_response = authenticated_client(user).get("/api/finance/reconciliation/exceptions/")

    assert response.status_code == 201
    assert response.json()["data"]["difference_amount"] == "-5.00"
    assert ReconciliationException.objects.count() == 1
    assert exception_response.status_code == 200
    assert exception_response.json()["data"][0]["difference_amount"] == "-5.00"
    assert FinanceAuditLog.objects.filter(action="run_mock_reconciliation").exists()


@pytest.mark.django_db
def test_reject_match_records_audit_and_blocks_repeat_handling():
    tenant = Tenant.objects.create(name="Tenant", code="tenant")
    finance_user = create_user(tenant, "finance")
    grant_finance_access(finance_user)
    seed_demo_finance_data(tenant)
    client = authenticated_client(finance_user)
    run_response = client.post("/api/finance/reconciliation/run-mock/", {}, format="json")
    match_id = run_response.json()["data"]["id"]

    reject_response = client.post(
        f"/api/finance/reconciliation/matches/{match_id}/reject/",
        {"reason": "demo mismatch"},
        format="json",
    )
    repeat_response = client.post(
        f"/api/finance/reconciliation/matches/{match_id}/reject/",
        {"reason": "repeat"},
        format="json",
    )

    assert reject_response.status_code == 200
    assert reject_response.json()["data"]["status"] == ReconciliationMatch.Status.REJECTED
    assert repeat_response.status_code == 400
    assert FinanceAuditLog.objects.filter(action="reject_reconciliation_match").exists()


@pytest.mark.django_db
def test_finance_audit_masks_credential_like_rejection_reason():
    tenant = Tenant.objects.create(name="Tenant", code="finance-audit-mask")
    finance_user = create_user(tenant, "finance-audit-mask")
    grant_finance_access(finance_user)
    seed_demo_finance_data(tenant)
    client = authenticated_client(finance_user)
    match_id = client.post("/api/finance/reconciliation/run-mock/", {}, format="json").json()["data"]["id"]

    response = client.post(
        f"/api/finance/reconciliation/matches/{match_id}/reject/",
        {"reason": "token=demo-credential-value"},
        format="json",
    )

    audit = FinanceAuditLog.objects.get(action="reject_reconciliation_match")
    assert response.status_code == 200
    assert "demo-credential-value" not in str(audit.masked_detail)
    assert audit.masked_detail["reason"] == "token=***"
