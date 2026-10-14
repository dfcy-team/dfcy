import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.finance.models import (
    BankReceiptImport,
    PlatformStatement,
    ReconciliationException,
    ReconciliationMatch,
    WithdrawalRecord,
)
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


def scoped_finance_client(tenant, username, config):
    user = CustomUser.objects.create_user(
        username=username,
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    role = Role.objects.create(tenant=tenant, name=username, code=f"{username}-role")
    permission, _ = Permission.objects.get_or_create(
        code="finance.view",
        defaults={"name": "Finance view", "module": "finance", "action": "view"},
    )
    role.permissions.add(permission)
    DataScope.objects.create(
        tenant=tenant,
        role=role,
        scope_type=DataScope.ScopeType.CUSTOM if config else DataScope.ScopeType.ALL,
        config=config,
    )
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def add_match(tenant, suffix, *, platform="shopee", withdrawal_platform=None,
              withdrawal_tenant=None, receipt_tenant=None, withdrawal_currency="USD",
              receipt_currency="USD", status=ReconciliationMatch.Status.SUGGESTED):
    statement = PlatformStatement.objects.create(
        tenant=tenant,
        platform=platform,
        statement_no=f"STMT-{suffix}",
        period_start="2026-01-01",
        period_end="2026-01-31",
        currency="USD",
        gross_amount="90.00",
        net_amount="90.00",
    )
    withdrawal = WithdrawalRecord.objects.create(
        tenant=withdrawal_tenant or tenant,
        platform=withdrawal_platform or platform,
        withdrawal_no=f"WD-{suffix}",
        currency=withdrawal_currency,
        requested_amount="90.00",
        expected_amount="90.00",
        requested_at="2026-01-15T00:00:00Z",
        status=WithdrawalRecord.Status.COMPLETED,
    )
    receipt = BankReceiptImport.objects.create(
        tenant=receipt_tenant or tenant,
        import_batch_no=f"BANK-{suffix}",
        masked_account="****1234",
        currency=receipt_currency,
        receipt_amount="85.00",
        receipt_date="2026-01-16",
        reference_no=f"REF-{suffix}",
    )
    match = ReconciliationMatch.objects.create(
        tenant=tenant,
        statement=statement,
        withdrawal=withdrawal,
        bank_receipt=receipt,
        matched_amount="85.00",
        difference_amount="-5.00",
        status=status,
    )
    exception = ReconciliationException.objects.create(
        tenant=tenant,
        reconciliation_match=match,
        exception_type=ReconciliationException.ExceptionType.AMOUNT_DIFFERENCE,
        difference_amount="-5.00",
    )
    return match, exception


@pytest.mark.django_db
def test_analytics_reconciliation_and_exceptions_match_source_scope_of_lists():
    tenant = Tenant.objects.create(name="Analytics scope", code="finance-analytics-source-scope")
    other_tenant = Tenant.objects.create(name="Other source tenant", code="finance-analytics-other-source")
    valid_match, valid_exception = add_match(tenant, "valid")
    add_match(tenant, "wrong-platform", withdrawal_platform="other-platform")
    add_match(tenant, "wrong-currency", withdrawal_currency="EUR")
    add_match(tenant, "wrong-receipt-currency", receipt_currency="EUR")
    add_match(tenant, "wrong-withdrawal-tenant", withdrawal_tenant=other_tenant)
    add_match(tenant, "wrong-receipt-tenant", receipt_tenant=other_tenant)

    restricted = scoped_finance_client(
        tenant,
        "finance-analytics-platform-restricted",
        {"platforms": ["shopee"], "currencies": ["USD"]},
    )
    scoped_reconciliation = restricted.get("/api/finance/reconciliation/matches/")
    scoped_exceptions = restricted.get("/api/finance/reconciliation/exceptions/")
    scoped_reconciliation_analytics = restricted.get(
        "/api/finance/analytics/reconciliation/?status=suggested&period_start=2026-01-01&period_end=2026-01-31"
    )
    scoped_exception_analytics = restricted.get(
        "/api/finance/analytics/exceptions/?status=open&period_start=2026-01-01&period_end=2026-01-31"
    )
    detail = restricted.get(f"/api/finance/reconciliation/matches/{valid_match.id}/")

    # Platform-scoped users cannot see bank-source data, matching existing list/detail semantics.
    assert scoped_reconciliation.json()["data"] == []
    assert scoped_exceptions.json()["data"] == []
    assert detail.status_code == 404
    assert scoped_reconciliation_analytics.status_code == 200
    assert scoped_reconciliation_analytics.json()["data"]["count"] == 0
    assert scoped_exception_analytics.status_code == 200
    assert scoped_exception_analytics.json()["data"]["count"] == 0

    # Currency-only access has no platform restriction and remains able to see consistent rows.
    currency_only = scoped_finance_client(
        tenant,
        "finance-analytics-currency-only",
        {"currencies": ["USD"]},
    )
    currency_reconciliation = currency_only.get("/api/finance/reconciliation/matches/")
    currency_exceptions = currency_only.get("/api/finance/reconciliation/exceptions/")
    currency_reconciliation_analytics = currency_only.get(
        "/api/finance/analytics/reconciliation/?status=suggested&period_start=2026-01-01&period_end=2026-01-31"
    )
    currency_exception_analytics = currency_only.get(
        "/api/finance/analytics/exceptions/?status=open&period_start=2026-01-01&period_end=2026-01-31"
    )
    assert [row["id"] for row in currency_reconciliation.json()["data"]] == [valid_match.id]
    assert [row["id"] for row in currency_exceptions.json()["data"]] == [valid_exception.id]
    reconciliation_data = currency_reconciliation_analytics.json()["data"]
    exception_data = currency_exception_analytics.json()["data"]
    assert currency_reconciliation_analytics.status_code == 200
    assert reconciliation_data["count"] == 1
    assert reconciliation_data["results"][0]["match_count"] == 1
    assert reconciliation_data["results"][0]["matched_amount"] == 85.0
    assert currency_exception_analytics.status_code == 200
    assert exception_data["count"] == 1
    assert exception_data["results"][0]["exception_count"] == 1
    assert exception_data["results"][0]["total_difference"] == -5.0

    full_access = scoped_finance_client(tenant, "finance-analytics-all", {})
    full_reconciliation = full_access.get(
        "/api/finance/analytics/reconciliation/?status=suggested&period_start=2026-01-01&period_end=2026-01-31"
    ).json()["data"]
    full_exceptions = full_access.get(
        "/api/finance/analytics/exceptions/?status=open&period_start=2026-01-01&period_end=2026-01-31"
    ).json()["data"]
    assert full_reconciliation["count"] == 1
    assert full_reconciliation["results"][0]["matched_amount"] == 85.0
    assert full_exceptions["count"] == 1
    assert full_exceptions["results"][0]["exception_count"] == 1
