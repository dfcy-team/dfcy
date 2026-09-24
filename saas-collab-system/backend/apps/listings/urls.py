from django.urls import path

from . import views
from . import warehouse_sku_views


urlpatterns = [
    path("warehouse-skus/", warehouse_sku_views.warehouse_skus),
    path("warehouse-skus/export/", warehouse_sku_views.export_warehouse_skus),
    path("warehouse-skus/<int:pk>/mapping/", warehouse_sku_views.warehouse_sku_mapping),
    path("templates/", views.template_collection),
    path("profiles/", views.profile_collection),
    path("profiles/<int:pk>/", views.profile_detail),
    path("profiles/<int:pk>/submit/", views.profile_submit),
    path("profiles/<int:pk>/approve/", views.profile_approve),
    path("profiles/<int:pk>/publish/", views.profile_publish),
    path("product-details/", views.PlatformProductDetailCollectionView.as_view()),
    path("product-details/<int:pk>/", views.PlatformProductDetailView.as_view()),
    path("product-details/bulk-update/", views.platform_product_detail_bulk_update),
    path("product-details/import/", views.PlatformProductDetailImportView.as_view()),
    path(
        "product-details/import-platform-product-ids/",
        views.PlatformProductDetailProductIdImportView.as_view(),
    ),
]
