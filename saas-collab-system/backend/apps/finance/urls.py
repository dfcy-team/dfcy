from django.urls import path

from .views import (
    bank_receipt_collection,
    confirm_reconciliation_match,
    health,
    import_demo_bank_receipt_view,
    import_demo_statement_view,
    import_demo_withdrawal_view,
    reconciliation_exception_collection,
    reconciliation_match_collection,
    reconciliation_match_detail,
    reject_reconciliation_match,
    resolve_reconciliation_exception,
    run_mock_reconciliation_view,
    statement_collection,
    withdrawal_collection,
    finance_analytics_exceptions,
    finance_analytics_overview,
    finance_analytics_reconciliation,
)


urlpatterns = [
    path("health/", health, name="finance-health"),
    path("analytics/overview/", finance_analytics_overview, name="finance-analytics-overview"),
    path("analytics/reconciliation/", finance_analytics_reconciliation, name="finance-analytics-reconciliation"),
    path("analytics/exceptions/", finance_analytics_exceptions, name="finance-analytics-exceptions"),
    path("statements/", statement_collection, name="finance-statement-collection"),
    path("statements/import-demo/", import_demo_statement_view, name="finance-statement-import-demo"),
    path("withdrawals/", withdrawal_collection, name="finance-withdrawal-collection"),
    path("withdrawals/import-demo/", import_demo_withdrawal_view, name="finance-withdrawal-import-demo"),
    path("bank-receipts/", bank_receipt_collection, name="finance-bank-receipt-collection"),
    path("bank-receipts/import-demo/", import_demo_bank_receipt_view, name="finance-bank-receipt-import-demo"),
    path("reconciliation/matches/", reconciliation_match_collection, name="finance-reconciliation-match-collection"),
    path(
        "reconciliation/matches/<int:pk>/",
        reconciliation_match_detail,
        name="finance-reconciliation-match-detail",
    ),
    path("reconciliation/run-mock/", run_mock_reconciliation_view, name="finance-reconciliation-run-mock"),
    path(
        "reconciliation/matches/<int:pk>/confirm/",
        confirm_reconciliation_match,
        name="finance-reconciliation-match-confirm",
    ),
    path(
        "reconciliation/matches/<int:pk>/reject/",
        reject_reconciliation_match,
        name="finance-reconciliation-match-reject",
    ),
    path(
        "reconciliation/exceptions/",
        reconciliation_exception_collection,
        name="finance-reconciliation-exception-collection",
    ),
    path(
        "reconciliation/exceptions/<int:pk>/resolve/",
        resolve_reconciliation_exception,
        name="finance-reconciliation-exception-resolve",
    ),
]
