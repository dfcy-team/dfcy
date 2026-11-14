from django.urls import path
from .registration_services import PREFIX
from .registration_views import RegistrationView
from . import operating_api as oa
from . import operating_reference as orf
from . import decision_api as da
from . import aftersales_api as aa
from .realtime_board import RealtimeBoardView
from .board_declines import BoardDeclinesView
from .sales_operations import SalesOperationsView
from .nine_snapshot_api import SalesNineSnapshotView

from .views import (
    CommerceFiltersView,
    DashboardMonthlySalesView,
    DataLinkageStatusView,
    InventoryCollectionView,
    InventoryWorkbenchView,
    SalesDataQualityView,
    SalesExportCollectionView,
    SalesOrderCollectionView,
    SalesOrderDetailView,
    SalesOverviewView,
    SalesTrendView,
    SalesReturnCollectionView,
    SKUSalesCollectionView,
    StoreSalesCollectionView,
)


from .warehouse_order_api import OrderWarehouseView

urlpatterns = [
    path("orders/<int:pk>/warehouse/", OrderWarehouseView.as_view(), name="sales-order-warehouse"),
    path('aftersales/', aa.AftersalesCollection.as_view(), name='order-aftersales'),
    path('aftersales/options/', aa.AftersalesOptions.as_view(), name='order-aftersales-options'),
    path('aftersales/matching-orders/', aa.MatchingOrders.as_view(), name='order-aftersales-matching-orders'),
    path('aftersales/settings/', aa.AftersalesSettings.as_view(), name='order-aftersales-settings'),
    path('aftersales/sync/', aa.AftersalesSync.as_view(), name='order-aftersales-sync'),
    path('aftersales/receipts/', aa.ReceiptCollection.as_view(), name='order-aftersales-receipts'),
    path('aftersales/import/', aa.ReceiptImport.as_view(), name='order-aftersales-import'),
    path('aftersales/template/', aa.ReceiptTemplate.as_view(), name='order-aftersales-template'),
    path('aftersales/receipts/<int:pk>/allocate/', aa.ReceiptAllocation.as_view(), name='order-aftersales-allocate'),
    path('aftersales/allocations/<int:pk>/unlink/', aa.ReceiptUnlink.as_view(), name='order-aftersales-unlink'),
    path('aftersales/cases/<str:source_key>/', aa.AftersalesDetail.as_view(), name='order-aftersales-detail'),
    path("sales-nine-snapshots/", SalesNineSnapshotView.as_view(), name="commerce-sales-nine-snapshots"),
    path('inventory/country-decisions/', da.CountryDecisions.as_view(), name='inventory-country-decisions'),
    path('inventory/country-decisions/evaluate-alerts/', da.CountryDecisionAlerts.as_view(), name='inventory-country-decision-alerts'),
    path('inventory/country-decisions/<int:country_id>/skus/<int:sku_id>/image/', da.CountryDecisionImage.as_view(), name='inventory-country-decision-image'),
    path('operating-options/', oa.OperatingOptions.as_view(), name='operating-options'),
    path('operating-options/skus/<int:sku_id>/image/', oa.OperatingSKUImage.as_view(), name='operating-sku-image'),
    path('operating-orders/', oa.OperatingOrders.as_view(), name='operating-orders'),
    path('operating-orders/preview/', oa.OperatingPreview.as_view(), name='operating-preview'),
    path('operating-orders/references/', orf.OperatingReferences.as_view(), name='operating-references'),
    path('operating-orders/<int:pk>/', oa.OperatingDetail.as_view(), name='operating-detail'),
    path('operating-orders/<int:pk>/submit/', oa.OperatingSubmit.as_view(), name='operating-submit'),
    path('operating-orders/<int:pk>/cancel/', oa.OperatingCancel.as_view(), name='operating-cancel'),
    path("filters/", CommerceFiltersView.as_view(), name="commerce-filters"),
    path("dashboard/monthly-sales/", DashboardMonthlySalesView.as_view(), name="commerce-dashboard-monthly-sales"),
    path("realtime-board/", RealtimeBoardView.as_view(), name="commerce-realtime-board"),
    path("board-declines/", BoardDeclinesView.as_view(), name="commerce-board-declines"),
    path("sales-operations/", SalesOperationsView.as_view(), name="commerce-sales-operations"),
    path("linkage-status/", DataLinkageStatusView.as_view(), name="commerce-linkage-status"),
    path("overview/", SalesOverviewView.as_view(), name="sales-overview"),
    path("sales/trend/", SalesTrendView.as_view(), name="sales-trend"),
    path("sales/stores/", StoreSalesCollectionView.as_view(), name="commerce-store-sales"),
    path("sales/skus/", SKUSalesCollectionView.as_view(), name="commerce-sku-sales"),
    path("orders/", SalesOrderCollectionView.as_view(), name="sales-order-list"),
    path("orders/<int:pk>/", SalesOrderDetailView.as_view(), name="sales-order-detail"),
    path("refunds/", SalesReturnCollectionView.as_view(), name="sales-refund-list"),
    path("returns/", SalesReturnCollectionView.as_view(), name="legacy-sales-return-list"),
    path("stores/", StoreSalesCollectionView.as_view(), name="store-sales-list"),
    path("skus/", SKUSalesCollectionView.as_view(), name="sku-sales-list"),
    path("inventory/", InventoryCollectionView.as_view(), name="commerce-inventory"),
    path("inventory/workbench/", InventoryWorkbenchView.as_view(), name="inventory-workbench"),
    path("quality/", SalesDataQualityView.as_view(), name="commerce-quality"),
    path("exports/", SalesExportCollectionView.as_view(), name="sales-export-list"),
    path("data-quality/", SalesDataQualityView.as_view(), name="sales-data-quality"),
]

def registration_view(**attributes):
    # Fixed server-owned classes expose exact operation permissions to the manifest.
    return type("RegistrationEndpoint", (RegistrationView,), {"__module__": "apps.sales_management.registration_views", **attributes}).as_view()


for kind, prefix in PREFIX.items():
    declarations = {"kind": kind, "read_permission_code": f"{prefix}.view", "write_permission_code": f"{prefix}.create"}
    for operation in ("template", "export", "imports"):
        read_action = "import" if operation in {"template", "imports"} else "export"
        urlpatterns.append(path(f"registrations/{kind}/{operation}/", registration_view(**{**declarations, "read_permission_code": f"{prefix}.{read_action}"}, operation=operation, http_method_names=["get", "head", "options"])))
    for operation in ("import-preview", "import-confirm"):
        urlpatterns.append(path(f"registrations/{kind}/{operation}/", registration_view(**{**declarations, "write_permission_code": f"{prefix}.import"}, operation=operation, http_method_names=["post", "options"])))
    if kind == "exchange":
        urlpatterns.append(path(f"registrations/{kind}/batch-submit/", registration_view(**{**declarations, "write_permission_code": f"{prefix}.submit"}, operation="batch-submit", http_method_names=["post", "options"])))
    urlpatterns.append(path(f"registrations/{kind}/batch-delete/", registration_view(**{**declarations, "write_permission_code": f"{prefix}.edit"}, operation="batch-delete", http_method_names=["post", "options"])))
    urlpatterns.append(path(f"registrations/{kind}/options/", registration_view(**declarations, operation="options", http_method_names=["get", "head", "options"])))
    urlpatterns.append(path(f"registrations/{kind}/", registration_view(**declarations, http_method_names=["get", "head", "post", "options"])))
    urlpatterns.append(path(f"registrations/{kind}/<int:pk>/", registration_view(**{**declarations, "write_permission_code": f"{prefix}.edit"}, http_method_names=["get", "head", "patch", "options"])))
    urlpatterns.append(path(f"registrations/{kind}/<int:pk>/evidence/<int:evidence_id>/", registration_view(**{**declarations, "read_permission_code": f"{prefix}.sensitive" if kind == "gcash" else f"{prefix}.view"}, http_method_names=["get", "head", "options"])))
    actions = {"evidence": "edit", "delete": "edit", "restore": "edit", **({"submit": "submit", "approve": "approve", "reject": "approve", "withdraw": "submit", "cancel": "edit"} if kind == "exchange" else {"register": "edit", "void": "edit"})}
    if kind == "promotion":
        actions.update({"cancel": "edit", "withdraw": "edit"})
    if kind == "exchange":
        actions["apply"] = "approve"
    for operation, action in actions.items():
        urlpatterns.append(path(f"registrations/{kind}/<int:pk>/{operation}/", registration_view(**{**declarations, "operation": operation, "write_permission_code": f"{prefix}.{action}"}, http_method_names=["post", "options"])))
