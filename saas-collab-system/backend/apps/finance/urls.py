from django.urls import path

from .views import (
    bank_receipt_collection,
    confirm_reconciliation_match,
    health,
    import_demo_bank_receipt_view,
    import_demo_statement_view,
    import_demo_withdrawal_view,
    reconciliation_exception_collection,
    reconciliation_match_detail,
    reconciliation_match_collection,
    resolve_reconciliation_exception,
    reject_reconciliation_match,
    run_mock_reconciliation_view,
    statement_collection,
    withdrawal_collection,
    finance_analytics_exceptions,
    finance_analytics_overview,
    finance_analytics_reconciliation,
    finance_transaction_collection,
    lazada_finance_wide_collection,
)
from .import_views import finance_imports
from .warehouse_fee_views import fee_endpoint
from .warehouse_bill_views import bill_endpoint, WarehouseFormatRuleView
from .ledger_views import finance_ledger
from .platform_wallet_api import WalletOverview, WalletWithdrawals, WalletSchedule, WalletManualSync


from .summary_views import summary_bootstrap, summary_document, summary_save, summary_report
from .summary_views import summary_table, summary_table_detail, summary_fee, summary_history, summary_rebuild, summary_job


urlpatterns = [
    path('summary/', summary_bootstrap, name='finance-summary-bootstrap'),
    path('summary/jobs/<int:pk>/', summary_job, name='finance-summary-job'),
    path('summary/<int:pk>/rebuild/', summary_rebuild, name='finance-summary-rebuild'),
    path('summary/<int:pk>/table/', summary_table, name='finance-summary-table'),
    path('summary/<int:pk>/table-detail/', summary_table_detail, name='finance-summary-table-detail'),
    path('summary/<int:pk>/fee/', summary_fee, name='finance-summary-fee'),
    path('summary/<int:pk>/history/', summary_history, name='finance-summary-history'),
    path('summary/<int:pk>/document/', summary_document, name='finance-summary-document'),
    path('summary/<int:pk>/settings/', summary_save, name='finance-summary-settings'),
    path('summary/<int:pk>/report/', summary_report, name='finance-summary-report'),
    path('platform-wallet/overview/', WalletOverview.as_view(), name='platform-wallet-overview'),
    path('platform-wallet/withdrawals/', WalletWithdrawals.as_view(), name='platform-wallet-withdrawals'),
    path('platform-wallet/schedule/', WalletSchedule.as_view(), name='platform-wallet-schedule'),
    path('platform-wallet/sync/', WalletManualSync.as_view(), name='platform-wallet-sync'),
    path('ledger/', finance_ledger, name='finance-ledger'),
    path('warehouse-fees/original-bills/', bill_endpoint()),
    path('warehouse-fees/format-rules/', WarehouseFormatRuleView.as_view()),
    path('warehouse-fees/original-bills/<uuid:pk>/format-preview/', bill_endpoint('format-preview')),
    path('warehouse-fees/original-bills/<uuid:pk>/', bill_endpoint()),
    path('warehouse-fees/original-bills/<uuid:pk>/errors/', bill_endpoint('errors', methods=['get', 'head', 'options'])),
    path('warehouse-fees/', fee_endpoint()),
    path('warehouse-fees/options/', fee_endpoint('options', methods=['get', 'head', 'options'])),
    path('warehouse-fees/template/', fee_endpoint('template', read='import', methods=['get', 'head', 'options'])),
    path('warehouse-fees/import/', fee_endpoint('import', write='import', methods=['post', 'options'])),
    path('warehouse-fees/imports/', fee_endpoint('imports', read='import', methods=['get', 'head', 'options'])),
    path('warehouse-fees/export/', fee_endpoint('export', read='export', methods=['get', 'head', 'options'])),
    path('warehouse-fees/batch-register/', fee_endpoint('batch-register', write='register', methods=['post', 'options'])),
    path('warehouse-fees/<int:pk>/', fee_endpoint(methods=['get', 'head', 'options'])),
    *[path(f'warehouse-fees/<int:pk>/{operation}/', fee_endpoint(operation, write=permission, methods=['post', 'options']))
      for operation, permission in [('register', 'register'), ('void', 'void'), ('correct', 'edit'), ('edit', 'edit'), ('link', 'edit')]],
    path("health/", health, name="finance-health"),
    path("analytics/overview/", finance_analytics_overview, name="finance-analytics-overview"),
    path("analytics/reconciliation/", finance_analytics_reconciliation, name="finance-analytics-reconciliation"),
    path("analytics/exceptions/", finance_analytics_exceptions, name="finance-analytics-exceptions"),
    path("statements/", statement_collection, name="finance-statement-collection"),
    path("imports/", finance_imports, name="finance-imports"),
    path("transactions/", finance_transaction_collection, name="finance-transaction-collection"),
    path("lazada-income-wide/", lazada_finance_wide_collection, name="lazada-finance-wide-collection"),
    path("statements/import-demo/", import_demo_statement_view, name="finance-statement-import-demo"),
    path("withdrawals/", withdrawal_collection, name="finance-withdrawal-collection"),
    path("withdrawals/import-demo/", import_demo_withdrawal_view, name="finance-withdrawal-import-demo"),
    path("bank-receipts/", bank_receipt_collection, name="finance-bank-receipt-collection"),
    path("bank-receipts/import-demo/", import_demo_bank_receipt_view, name="finance-bank-receipt-import-demo"),
    path("reconciliation/matches/", reconciliation_match_collection, name="finance-reconciliation-match-collection"),
    path("reconciliation/matches/<int:pk>/", reconciliation_match_detail, name="finance-reconciliation-match-detail"),
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
