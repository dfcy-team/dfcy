from django.urls import path

from .views import (
    CommerceFiltersView,
    DataLinkageStatusView,
    InventoryCollectionView,
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
    path("filters/", CommerceFiltersView.as_view(), name="commerce-filters"),
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
    path("quality/", SalesDataQualityView.as_view(), name="commerce-quality"),
    path("exports/", SalesExportCollectionView.as_view(), name="sales-export-list"),
    path("data-quality/", SalesDataQualityView.as_view(), name="sales-data-quality"),
]
