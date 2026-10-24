from django.urls import path
from . import operating_api as oa
from . import operating_reference as orf
from . import decision_api as da
from .realtime_board import RealtimeBoardView
from .board_declines import BoardDeclinesView
from .sales_operations import SalesOperationsView

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


urlpatterns = [
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
