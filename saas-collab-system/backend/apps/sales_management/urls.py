from django.urls import path

from .views import (
    SalesDataQualityView,
    SalesExportCollectionView,
    SalesOrderCollectionView,
    SalesOrderDetailView,
    SalesOverviewView,
    SalesReturnCollectionView,
    SKUSalesCollectionView,
    StoreSalesCollectionView,
    SyncRerunCollectionView,
)


urlpatterns = [
    path("overview/", SalesOverviewView.as_view(), name="sales-overview"),
    path("orders/", SalesOrderCollectionView.as_view(), name="sales-order-list"),
    path("orders/<int:pk>/", SalesOrderDetailView.as_view(), name="sales-order-detail"),
    path("returns/", SalesReturnCollectionView.as_view(), name="sales-return-list"),
    path("stores/", StoreSalesCollectionView.as_view(), name="store-sales-list"),
    path("skus/", SKUSalesCollectionView.as_view(), name="sku-sales-list"),
    path("exports/", SalesExportCollectionView.as_view(), name="sales-export-list"),
    path("data-quality/", SalesDataQualityView.as_view(), name="sales-data-quality"),
    path("sync-reruns/", SyncRerunCollectionView.as_view(), name="sales-sync-rerun-list"),
]
