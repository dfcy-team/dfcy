from django.urls import path

from .views import (
    InfluencerCollectionView,
    InfluencerDetailView,
    InfluencerStatusView,
    OutreachTaskCollectionView,
    OutreachTaskStatusView,
    ProductPriceLookupView,
    SampleFulfillmentCollectionView,
    SampleFulfillmentStatusView,
)

urlpatterns = [
    path("", InfluencerCollectionView.as_view(), name="influencer-collection"),
    path("<int:pk>/", InfluencerDetailView.as_view(), name="influencer-detail"),
    path("<int:pk>/status/", InfluencerStatusView.as_view(), name="influencer-status"),
    path("outreach-tasks/", OutreachTaskCollectionView.as_view(), name="outreach-task-collection"),
    path("outreach-tasks/<int:pk>/status/", OutreachTaskStatusView.as_view(), name="outreach-task-status"),
    path("sample-fulfillments/", SampleFulfillmentCollectionView.as_view(), name="sample-fulfillment-collection"),
    path("sample-fulfillments/<int:pk>/status/", SampleFulfillmentStatusView.as_view(), name="sample-fulfillment-status"),
    path("product-price-lookup/", ProductPriceLookupView.as_view(), name="product-price-lookup"),
]
