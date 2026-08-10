from django.urls import path

from .views import InfluencerCollectionView, InfluencerDetailView, InfluencerStatusView

urlpatterns = [
    path("", InfluencerCollectionView.as_view(), name="influencer-collection"),
    path("<int:pk>/", InfluencerDetailView.as_view(), name="influencer-detail"),
    path("<int:pk>/status/", InfluencerStatusView.as_view(), name="influencer-status"),
]
