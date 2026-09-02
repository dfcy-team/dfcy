from django.urls import path

from .views import MasterDataCollectionView, MasterDataDetailView, MasterDataStatusView, PlatformCatalogView, PlatformSiteMigrationView


urlpatterns = [
    path("platforms/catalog/", PlatformCatalogView.as_view(), name="platform-catalog"),
    path("platform-sites/migration-preview/", PlatformSiteMigrationView.as_view(), name="platform-site-migration"),
    path("<str:resource>/", MasterDataCollectionView.as_view(), name="master-data-collection"),
    path("<str:resource>/<int:pk>/", MasterDataDetailView.as_view(), name="master-data-detail"),
    path("<str:resource>/<int:pk>/status/", MasterDataStatusView.as_view(), name="master-data-status"),
]
