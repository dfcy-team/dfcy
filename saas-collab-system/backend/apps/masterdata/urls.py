from django.urls import path

from .views import MasterDataCollectionView, MasterDataDetailView, MasterDataStatusView


urlpatterns = [
    path("<str:resource>/", MasterDataCollectionView.as_view(), name="master-data-collection"),
    path("<str:resource>/<int:pk>/", MasterDataDetailView.as_view(), name="master-data-detail"),
    path("<str:resource>/<int:pk>/status/", MasterDataStatusView.as_view(), name="master-data-status"),
]
