from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.finance.models import FinanceAuditLog, PlatformStatement
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.models import ProductSKU, ProductSPU
from apps.replenishment.services import evaluate_replenishment
from apps.reports.export_services import create_export_request
from apps.reports.models import ReportExportAuditLog, ReportExportRequest
from apps.tenants.models import Tenant


def create_user(tenant, username, user_type=CustomUser.UserType.INTERNAL):
    return CustomUser.objects.create_user(username=username, tenant=tenant, user_type=user_type)


def grant(user, code, scope_type=DataScope.ScopeType.ALL, config=None):
    role = Role.objects.create(tenant=user.tenant, name=code, code=f"{code}-{user.id}")
    role.permissions.add(Permission.objects.get(code=code))
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=scope_type, config=config or {})


def create_sku(tenant, suffix):
    spu = ProductSPU.objects.create(tenant=tenant, spu_code=f"SPU-{suffix}", product_name="Demo")
    return ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code=f"SKU-{suffix}")


def create_recommendation(tenant, sku, stock=1):
    return evaluate_replenishment(
        tenant=tenant, sku=sku, available_stock=stock, in_transit_stock=0,
        average_daily_sales=1, safety_stock_days=7, supplier_lead_days=10,
        replenishment_cycle_days=14,
    )


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_report_export_uses_tenant_data_scope_placeholder_and_audit():
    tenant = Tenant.objects.create(name="Tenant", code="report-export")
    other = Tenant.objects.create(name="Other", code="report-export-other")
    visible_sku = create_sku(tenant, "VISIBLE")
    hidden_sku = create_sku(tenant, "HIDDEN")
    other_sku = create_sku(other, "OTHER")
    create_recommendation(tenant, visible_sku)
    create_recommendation(tenant, hidden_sku)
    create_recommendation(other, other_sku)
    exporter = create_user(tenant, "exporter")
    grant(
        exporter,
        "reports.view",
        DataScope.ScopeType.CUSTOM,
        {"report_types": ["replenishment"]},
    )
    grant(
        exporter,
        "reports.export",
        DataScope.ScopeType.CUSTOM,
        {"report_types": ["replenishment"]},
    )
    grant(exporter, "replenishment.view", DataScope.ScopeType.CUSTOM, {"sku_ids": [visible_sku.id]})

    export = create_export_request(
        user=exporter,
        report_type=ReportExportRequest.ReportType.REPLENISHMENT,
        filters={"sku_id": visible_sku.id},
    )

    assert export.row_count == 1
    assert export.status == ReportExportRequest.Status.COMPLETED
    assert export.masked_file_reference == f"placeholder://report-export/{export.id}"
    assert export.audit_logs.get().result == "placeholder_completed"
    assert export.data_scope


@pytest.mark.django_db
def test_report_export_large_result_is_rejected_without_file():
    tenant = Tenant.objects.create(name="Tenant", code="report-limit")
    first_sku = create_sku(tenant, "ONE")
    second_sku = create_sku(tenant, "TWO")
    create_recommendation(tenant, first_sku)
    create_recommendation(tenant, second_sku)
    exporter = create_user(tenant, "limit-exporter")
    grant(exporter, "reports.view")
    grant(exporter, "reports.export")
    grant(exporter, "replenishment.view")

    with patch("apps.reports.export_services.MAX_EXPORT_ROWS", 1):
        export = create_export_request(
            user=exporter,
            report_type=ReportExportRequest.ReportType.REPLENISHMENT,
            filters={},
        )

    assert export.status == ReportExportRequest.Status.REJECTED
    assert export.rejection_reason == "row_limit_exceeded"
    assert export.masked_file_reference == ""
    assert export.audit_logs.get().result == "rejected_row_limit"


@pytest.mark.django_db
def test_report_export_detail_is_owner_scoped_and_view_is_audited():
    tenant = Tenant.objects.create(name="Tenant", code="report-owner")
    sku = create_sku(tenant, "OWNER")
    create_recommendation(tenant, sku)
    owner = create_user(tenant, "owner")
    other_user = create_user(tenant, "other-user")
    for user in (owner, other_user):
        grant(user, "reports.view")
    grant(owner, "reports.export")
    grant(owner, "replenishment.view")
    export = create_export_request(
        user=owner,
        report_type=ReportExportRequest.ReportType.REPLENISHMENT,
        filters={},
    )

    assert client_for(other_user).get(f"/api/report/exports/{export.id}/").status_code == 404
    response = client_for(owner).get(f"/api/report/exports/{export.id}/")
    assert response.status_code == 200
    assert response.json()["data"]["masked_file_reference"].startswith("placeholder://")
    assert export.audit_logs.filter(action=ReportExportAuditLog.Action.VIEW).count() == 1


@pytest.mark.django_db
def test_report_filters_reject_sensitive_values_and_direct_persistence():
    tenant = Tenant.objects.create(name="Tenant", code="report-guard")
    exporter = create_user(tenant, "guard-exporter")
    grant(exporter, "reports.view")
    grant(exporter, "reports.export")
    grant(exporter, "replenishment.view")
    with pytest.raises(ValidationError, match="Sensitive credentials"):
        create_export_request(
            user=exporter,
            report_type=ReportExportRequest.ReportType.REPLENISHMENT,
            filters={"token": "not-a-real-secret"},
        )
    with pytest.raises(ValidationError, match="Unsupported report filters"):
        create_export_request(
            user=exporter,
            report_type=ReportExportRequest.ReportType.REPLENISHMENT,
            filters={"unknown_filter": "demo"},
        )
    forged = ReportExportRequest(
        tenant=tenant,
        report_type=ReportExportRequest.ReportType.REPLENISHMENT,
        requested_by=exporter,
        status=ReportExportRequest.Status.COMPLETED,
        masked_file_reference="C:/real/file.csv",
    )
    with pytest.raises(ValidationError, match="export service"):
        forged.save()


@pytest.mark.django_db
def test_finance_analytics_are_tenant_scoped_masked_and_read_only():
    tenant = Tenant.objects.create(name="Tenant", code="finance-analytics")
    other = Tenant.objects.create(name="Other", code="finance-analytics-other")
    finance_user = create_user(tenant, "finance-user")
    grant(finance_user, "finance.view")
    PlatformStatement.objects.create(
        tenant=tenant, platform="mock", statement_no="DEMO-1",
        period_start="2026-01-01", period_end="2026-01-31", currency="USD",
        gross_amount=Decimal("100.00"), fee_amount=Decimal("5.00"), net_amount=Decimal("95.00"),
    )
    PlatformStatement.objects.create(
        tenant=other, platform="mock", statement_no="HIDDEN",
        period_start="2026-01-01", period_end="2026-01-31", currency="USD",
        gross_amount=Decimal("9999.00"), fee_amount=Decimal("0.00"), net_amount=Decimal("9999.00"),
    )
    before = list(PlatformStatement.objects.values_list("id", "status"))

    overview = client_for(finance_user).get("/api/finance/analytics/overview/")
    reconciliation = client_for(finance_user).get("/api/finance/analytics/reconciliation/")
    exceptions = client_for(finance_user).get("/api/finance/analytics/exceptions/")

    assert overview.status_code == 200
    assert overview.json()["data"]["results"][0]["statement_amount"] == 100.0
    assert overview.json()["data"]["results"][0]["account_mask"] == "***"
    assert overview.json()["data"]["read_only"] is True
    assert reconciliation.json()["data"]["fund_action_available"] is False
    assert exceptions.json()["data"]["fund_action_available"] is False
    assert list(PlatformStatement.objects.values_list("id", "status")) == before
    assert FinanceAuditLog.objects.filter(tenant=tenant, object_type="FinanceAnalytics").count() == 3


@pytest.mark.django_db
def test_finance_analytics_applies_exact_platform_and_currency_scope():
    tenant = Tenant.objects.create(name="Tenant", code="finance-exact-scope")
    finance_user = create_user(tenant, "finance-scoped-user")
    grant(
        finance_user,
        "finance.view",
        DataScope.ScopeType.CUSTOM,
        {"platforms": ["mock"], "currencies": ["USD"]},
    )
    for currency, amount in (("USD", "100.00"), ("EUR", "900.00")):
        PlatformStatement.objects.create(
            tenant=tenant,
            platform="mock",
            statement_no=f"DEMO-{currency}",
            period_start="2026-01-01",
            period_end="2026-01-31",
            currency=currency,
            gross_amount=Decimal(amount),
            fee_amount=Decimal("0.00"),
            net_amount=Decimal(amount),
        )
    response = client_for(finance_user).get("/api/finance/analytics/overview/")
    assert response.status_code == 200
    assert response.json()["data"]["count"] == 1
    assert response.json()["data"]["results"][0]["currency"] == "USD"


@pytest.mark.django_db
def test_report_view_export_and_download_scopes_are_independent():
    tenant = Tenant.objects.create(name="Tenant", code="report-exact-actions")
    sku = create_sku(tenant, "REPORT-ACTION")
    create_recommendation(tenant, sku)
    user = create_user(tenant, "report-action-user")
    grant(user, "reports.view", DataScope.ScopeType.CUSTOM, {"report_types": ["replenishment"]})
    grant(user, "reports.export", DataScope.ScopeType.CUSTOM, {"report_types": ["finance_summary"]})
    grant(user, "reports.download", DataScope.ScopeType.CUSTOM, {"report_types": ["finance_summary"]})
    grant(user, "replenishment.view", DataScope.ScopeType.CUSTOM, {"sku_ids": [sku.id]})
    catalog = client_for(user).get("/api/report/catalog/")
    assert [item["report_type"] for item in catalog.json()["data"]] == ["replenishment"]
    denied = client_for(user).post(
        "/api/report/exports/",
        {"report_type": "replenishment", "filters": {}},
        format="json",
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "DATA_SCOPE_FORBIDDEN"


@pytest.mark.django_db
def test_finance_report_export_requires_separate_finance_export_permission():
    tenant = Tenant.objects.create(name="Tenant", code="finance-export-permission")
    exporter = create_user(tenant, "finance-exporter")
    grant(exporter, "reports.export")
    grant(exporter, "reports.view")
    from rest_framework.exceptions import PermissionDenied

    with pytest.raises(PermissionDenied):
        create_export_request(
            user=exporter,
            report_type=ReportExportRequest.ReportType.FINANCE_SUMMARY,
            filters={},
        )
    grant(exporter, "finance.export")
    export = create_export_request(
        user=exporter,
        report_type=ReportExportRequest.ReportType.FINANCE_SUMMARY,
        filters={},
    )
    assert export.status == ReportExportRequest.Status.COMPLETED


@pytest.mark.django_db
@pytest.mark.parametrize("user_type", [CustomUser.UserType.EXTERNAL, CustomUser.UserType.RPA])
def test_report_and_finance_analytics_reject_external_and_rpa(user_type):
    tenant = Tenant.objects.create(name="Tenant", code=f"report-deny-{user_type}")
    user = create_user(tenant, f"deny-{user_type}", user_type)
    grant(user, "reports.view")
    grant(user, "finance.view")
    assert client_for(user).get("/api/report/catalog/").status_code == 403
    assert client_for(user).get("/api/finance/analytics/overview/").status_code == 403
