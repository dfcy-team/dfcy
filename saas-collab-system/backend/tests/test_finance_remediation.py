from decimal import Decimal
from unittest.mock import patch

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
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


def user_with_scopes(tenant, username, scopes):
    user = CustomUser.objects.create_user(username=username, tenant=tenant, user_type=CustomUser.UserType.INTERNAL)
    for code, config in scopes.items():
        role = Role.objects.create(tenant=tenant, name=f"{username} {code}", code=f"{username}-{code.replace('.', '-')}-role")
        permission, _ = Permission.objects.get_or_create(
            code=code,
            defaults={"name": code, "module": "finance", "action": code.rsplit(".", 1)[-1]},
        )
        role.permissions.add(permission)
        DataScope.objects.create(
            tenant=tenant, role=role,
            scope_type=DataScope.ScopeType.ALL if not config else DataScope.ScopeType.CUSTOM,
            config=config,
        )
        UserRole.objects.create(tenant=tenant, user=user, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    return user, client


def finance_rows(tenant, *, platform="mock", currency="USD", receipt_amount="975.00", status="completed",
                 net_amount="975.00", expected_amount="975.00"):
    statement = PlatformStatement.objects.create(
        tenant=tenant, platform=platform, statement_no=f"STMT-{platform}-{currency}",
        period_start="2026-01-01", period_end="2026-01-31", currency=currency,
        gross_amount="1000.00", net_amount=net_amount,
    )
    withdrawal = WithdrawalRecord.objects.create(
        tenant=tenant, platform=platform, withdrawal_no=f"WD-{platform}-{currency}",
        currency=currency, requested_amount=expected_amount, expected_amount=expected_amount,
        requested_at="2026-01-15T00:00:00Z", status=status,
    )
    receipt = BankReceiptImport.objects.create(
        tenant=tenant, import_batch_no=f"BANK-{platform}-{currency}", masked_account="****1234",
        currency=currency, receipt_amount=receipt_amount, receipt_date="2026-01-16",
        reference_no=f"REF-{platform}-{currency}",
    )
    return statement, withdrawal, receipt


def all_scopes():
    return {
        "finance.view": {},
        "finance.reconcile": {},
        "finance.exception.handle": {},
    }


@pytest.mark.django_db
def test_legacy_lists_apply_tenant_platform_currency_status_and_bank_dimensions():
    tenant = Tenant.objects.create(name="Scoped", code="finance-scope-lists")
    outsider = Tenant.objects.create(name="Other", code="finance-scope-lists-other")
    visible = finance_rows(tenant, platform="shopify", currency="USD")
    hidden_platform = finance_rows(tenant, platform="mock", currency="USD")
    hidden_currency = finance_rows(tenant, platform="shopify", currency="EUR")
    finance_rows(outsider, platform="shopify", currency="USD")
    _user, client = user_with_scopes(tenant, "finance-scope-lists", {
        "finance.view": {"platforms": ["shopify"], "currencies": ["USD"]},
    })

    statements = client.get("/api/finance/statements/?platform=shopify&currency=usd&status=imported")
    receipts = client.get("/api/finance/bank-receipts/?currency=USD&status=imported")
    rejected_platform = client.get("/api/finance/bank-receipts/?platform=shopify")

    assert statements.status_code == 200
    assert [row["id"] for row in statements.json()["data"]] == [visible[0].id]
    assert receipts.json()["data"] == []
    assert rejected_platform.status_code == 400
    assert hidden_platform[0].id not in {row["id"] for row in statements.json()["data"]}
    assert hidden_currency[2].id not in {row["id"] for row in receipts.json()["data"]}
    _bank_user, bank_client = user_with_scopes(tenant, "finance-currency-only", {
        "finance.view": {"currencies": ["USD"]},
    })
    currency_receipts = bank_client.get("/api/finance/bank-receipts/?currency=USD&status=imported")
    assert {row["id"] for row in currency_receipts.json()["data"]} == {visible[2].id, hidden_platform[2].id}


@pytest.mark.django_db
def test_platform_only_scope_fails_closed_for_bank_receipts_and_cross_tenant_detail():
    tenant = Tenant.objects.create(name="Scoped", code="finance-scope-receipt")
    other = Tenant.objects.create(name="Other", code="finance-scope-receipt-other")
    own = finance_rows(tenant)
    foreign = finance_rows(other)
    _user, client = user_with_scopes(tenant, "finance-platform-only", {
        "finance.view": {"platforms": ["mock"]},
    })

    assert client.get("/api/finance/bank-receipts/").json()["data"] == []
    # A match ID is hidden as not found outside the caller's tenant.
    foreign_match = ReconciliationMatch.objects.create(
        tenant=other, statement=foreign[0], withdrawal=foreign[1], bank_receipt=foreign[2],
        matched_amount="975.00", difference_amount="0.00",
    )
    assert client.get(f"/api/finance/reconciliation/matches/{foreign_match.id}/").status_code == 404
    assert own[0].tenant_id == tenant.id


@pytest.mark.django_db
def test_mock_reconciliation_only_uses_exact_demo_source_keys():
    tenant = Tenant.objects.create(name="Mock", code="finance-mock-source")
    _user, client = user_with_scopes(tenant, "finance-mock-source", all_scopes())
    demo_statement = import_demo_statement(tenant)
    demo_withdrawal = import_demo_withdrawal(tenant)
    demo_receipt = import_demo_bank_receipt(tenant)
    real_statement, real_withdrawal, real_receipt = finance_rows(tenant)
    real_statement.source_type = PlatformStatement.SourceType.MANUAL_IMPORT
    real_statement.save(update_fields=["source_type"])

    response = client.post("/api/finance/reconciliation/run-mock/", {}, format="json")

    assert response.status_code == 201
    match = ReconciliationMatch.objects.get()
    assert match.statement_id == demo_statement.id
    assert match.withdrawal_id == demo_withdrawal.id
    assert match.bank_receipt_id == demo_receipt.id
    assert match.statement_id != real_statement.id
    assert match.withdrawal_id != real_withdrawal.id
    assert match.bank_receipt_id != real_receipt.id


@pytest.mark.django_db
def test_manual_match_creates_real_detail_exception_and_prevents_reuse():
    tenant = Tenant.objects.create(name="Manual", code="finance-manual-match")
    user, client = user_with_scopes(tenant, "finance-manual", all_scopes())
    statement, withdrawal, receipt = finance_rows(tenant, receipt_amount="970.00")

    created = client.post("/api/finance/reconciliation/matches/", {
        "statement_id": statement.id, "withdrawal_id": withdrawal.id, "bank_receipt_id": receipt.id,
    }, format="json")
    detail = client.get(f"/api/finance/reconciliation/matches/{created.json()['data']['id']}/")
    repeated = client.post("/api/finance/reconciliation/matches/", {
        "statement_id": statement.id, "withdrawal_id": withdrawal.id, "bank_receipt_id": receipt.id,
    }, format="json")

    assert created.status_code == 201
    assert created.json()["data"]["match_type"] == ReconciliationMatch.MatchType.MANUAL
    assert created.json()["data"]["difference_amount"] == "-5.00"
    assert ReconciliationException.objects.get().difference_amount == Decimal("-5.00")
    assert detail.status_code == 200
    assert detail.json()["data"]["statement"]["id"] == statement.id
    assert detail.json()["data"]["withdrawal"]["id"] == withdrawal.id
    assert detail.json()["data"]["bank_receipt"]["id"] == receipt.id
    assert detail.json()["data"]["statement_no"] == statement.statement_no
    assert detail.json()["data"]["withdrawal_no"] == withdrawal.withdrawal_no
    assert detail.json()["data"]["receipt_reference"] == receipt.reference_no
    assert detail.json()["data"]["platform"] == statement.platform
    assert detail.json()["data"]["currency"] == statement.currency
    assert detail.json()["data"]["statement_net_amount"] == "975.00"
    assert detail.json()["data"]["withdrawal_expected_amount"] == "975.00"
    assert detail.json()["data"]["receipt_amount"] == "970.00"
    assert repeated.status_code == 400
    statement.refresh_from_db()
    withdrawal.refresh_from_db()
    receipt.refresh_from_db()
    assert statement.status == PlatformStatement.Status.IMPORTED
    assert withdrawal.expected_amount == Decimal("975.00")
    assert receipt.receipt_amount == Decimal("970.00")
    assert FinanceAuditLog.objects.filter(actor=user, action="create_manual_reconciliation_match").count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("case", ["foreign_tenant", "wrong_platform", "wrong_currency", "incomplete_withdrawal", "scope"])
def test_manual_match_rejects_invalid_entity_combinations(case):
    tenant = Tenant.objects.create(name="Manual", code=f"finance-invalid-{case}")
    user, client = user_with_scopes(tenant, f"finance-invalid-{case}", all_scopes())
    statement, withdrawal, receipt = finance_rows(tenant)
    if case == "foreign_tenant":
        other = Tenant.objects.create(name="Foreign", code=f"finance-invalid-foreign-{case}")
        _, withdrawal, _ = finance_rows(other)
    elif case == "wrong_platform":
        withdrawal.platform = "different"
        withdrawal.save(update_fields=["platform"])
    elif case == "wrong_currency":
        receipt.currency = "EUR"
        receipt.save(update_fields=["currency"])
    elif case == "incomplete_withdrawal":
        withdrawal.status = WithdrawalRecord.Status.REQUESTED
        withdrawal.save(update_fields=["status"])
    elif case == "scope":
        role = Role.objects.filter(user_roles__user=user, permissions__code="finance.reconcile").first()
        DataScope.objects.filter(role=role).update(
            scope_type=DataScope.ScopeType.CUSTOM,
            config={"platforms": ["other"], "currencies": ["USD"]}
        )

    response = client.post("/api/finance/reconciliation/matches/", {
        "statement_id": statement.id, "withdrawal_id": withdrawal.id, "bank_receipt_id": receipt.id,
    }, format="json")
    assert response.status_code == 400
    assert ReconciliationMatch.objects.filter(tenant=tenant).count() == 0


@pytest.mark.django_db
def test_review_state_transitions_reason_and_confirm_difference_rules():
    tenant = Tenant.objects.create(name="Review", code="finance-review-state")
    _user, client = user_with_scopes(tenant, "finance-review", all_scopes())
    statement, withdrawal, receipt = finance_rows(tenant, receipt_amount="970.00")
    match = ReconciliationMatch.objects.create(
        tenant=tenant, statement=statement, withdrawal=withdrawal, bank_receipt=receipt,
        matched_amount="970.00", difference_amount="-5.00",
    )
    no_reason = client.post(f"/api/finance/reconciliation/matches/{match.id}/reject/", {"reason": "  "}, format="json")
    cannot_confirm = client.post(f"/api/finance/reconciliation/matches/{match.id}/confirm/", {}, format="json")
    rejected = client.post(f"/api/finance/reconciliation/matches/{match.id}/reject/", {"reason": "mismatch"}, format="json")
    duplicate = client.post(f"/api/finance/reconciliation/matches/{match.id}/reject/", {"reason": "again"}, format="json")

    assert no_reason.status_code == 400
    assert cannot_confirm.status_code == 400
    assert rejected.status_code == 200
    assert duplicate.status_code == 400
    statement.refresh_from_db()
    receipt.refresh_from_db()
    assert statement.status == PlatformStatement.Status.IMPORTED
    assert receipt.status == BankReceiptImport.Status.IMPORTED


@pytest.mark.django_db
def test_exception_resolve_requires_rejected_match_and_audits_reason():
    tenant = Tenant.objects.create(name="Exception", code="finance-exception-resolve")
    _user, client = user_with_scopes(tenant, "finance-exception", all_scopes())
    statement, withdrawal, receipt = finance_rows(tenant, receipt_amount="970.00")
    match = ReconciliationMatch.objects.create(
        tenant=tenant, statement=statement, withdrawal=withdrawal, bank_receipt=receipt,
        matched_amount="970.00", difference_amount="-5.00",
    )
    exception = ReconciliationException.objects.create(
        tenant=tenant, reconciliation_match=match,
        exception_type=ReconciliationException.ExceptionType.AMOUNT_DIFFERENCE,
        difference_amount="-5.00",
    )

    early = client.post(f"/api/finance/reconciliation/exceptions/{exception.id}/resolve/", {"reason": "fixed"}, format="json")
    client.post(f"/api/finance/reconciliation/matches/{match.id}/reject/", {"reason": "rejected"}, format="json")
    blank = client.post(f"/api/finance/reconciliation/exceptions/{exception.id}/resolve/", {"reason": " "}, format="json")
    resolved = client.post(f"/api/finance/reconciliation/exceptions/{exception.id}/resolve/", {"reason": "Re-match with corrected receipt"}, format="json")

    assert early.status_code == 400
    assert blank.status_code == 400
    assert resolved.status_code == 200
    assert resolved.json()["data"]["resolution_note"] == "Re-match with corrected receipt"
    assert FinanceAuditLog.objects.filter(action="resolve_reconciliation_exception").exists()


@pytest.mark.django_db
def test_manual_match_audit_failure_rolls_back_match_and_exception():
    tenant = Tenant.objects.create(name="Rollback", code="finance-manual-rollback")
    user, _client = user_with_scopes(tenant, "finance-rollback", all_scopes())
    statement, withdrawal, receipt = finance_rows(tenant, receipt_amount="970.00")

    with patch("apps.finance.services.write_finance_audit_log", side_effect=RuntimeError("audit failed")):
        with pytest.raises(RuntimeError):
            from apps.finance.services import create_manual_match
            create_manual_match(tenant, user, statement.id, withdrawal.id, receipt.id)

    assert ReconciliationMatch.objects.filter(tenant=tenant).count() == 0
    assert ReconciliationException.objects.filter(tenant=tenant).count() == 0


@pytest.mark.django_db
def test_manual_match_rejects_active_withdrawals_over_statement_net_amount():
    tenant = Tenant.objects.create(name="Capacity", code="finance-statement-capacity")
    user, client = user_with_scopes(tenant, "finance-capacity", all_scopes())
    statement, withdrawal, receipt = finance_rows(
        tenant, net_amount="100.00", expected_amount="101.00", receipt_amount="101.00"
    )

    response = client.post("/api/finance/reconciliation/matches/", {
        "statement_id": statement.id, "withdrawal_id": withdrawal.id, "bank_receipt_id": receipt.id,
    }, format="json")

    assert response.status_code == 400
    assert ReconciliationMatch.objects.filter(tenant=tenant).count() == 0
    assert FinanceAuditLog.objects.filter(actor=user, action="create_manual_reconciliation_match").count() == 0


@pytest.mark.django_db
def test_statement_is_matching_after_partial_confirmation_and_matched_at_exact_total():
    tenant = Tenant.objects.create(name="Partial", code="finance-partial-confirm")
    _user, client = user_with_scopes(tenant, "finance-partial", all_scopes())
    statement, withdrawal_a, receipt_a = finance_rows(
        tenant, net_amount="1000.00", expected_amount="400.00", receipt_amount="400.00"
    )
    withdrawal_b = WithdrawalRecord.objects.create(
        tenant=tenant, platform="mock", withdrawal_no="WD-second", currency="USD",
        requested_amount="600.00", expected_amount="600.00", requested_at="2026-01-17T00:00:00Z",
        status=WithdrawalRecord.Status.COMPLETED,
    )
    receipt_b = BankReceiptImport.objects.create(
        tenant=tenant, import_batch_no="BANK-second", masked_account="****2345", currency="USD",
        receipt_amount="600.00", receipt_date="2026-01-18", reference_no="REF-second",
    )

    created_a = client.post("/api/finance/reconciliation/matches/", {
        "statement_id": statement.id, "withdrawal_id": withdrawal_a.id, "bank_receipt_id": receipt_a.id,
    }, format="json")
    first_confirm = client.post(f"/api/finance/reconciliation/matches/{created_a.json()['data']['id']}/confirm/", {}, format="json")
    statement.refresh_from_db()
    first_statement_status = statement.status
    created_b = client.post("/api/finance/reconciliation/matches/", {
        "statement_id": statement.id, "withdrawal_id": withdrawal_b.id, "bank_receipt_id": receipt_b.id,
    }, format="json")
    second_confirm = client.post(f"/api/finance/reconciliation/matches/{created_b.json()['data']['id']}/confirm/", {}, format="json")
    statement.refresh_from_db()

    assert created_a.status_code == 201
    assert first_confirm.status_code == 200
    assert first_statement_status == PlatformStatement.Status.MATCHING
    assert created_b.status_code == 201
    assert second_confirm.status_code == 200
    assert statement.status == PlatformStatement.Status.MATCHED
