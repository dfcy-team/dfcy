from django.urls import path

from .views import (
    InfluencerCollectionView,
    InfluencerDetailView,
    InfluencerStatusView,
    OutreachTargetCollectionView,
    OutreachTargetDetailView,
    OutreachTaskDetailView,
    OutreachTaskCollectionView,
    OutreachTaskProgressView,
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
    path("outreach-tasks/<int:pk>/", OutreachTaskDetailView.as_view(), name="outreach-task-detail"),
    path("outreach-tasks/<int:pk>/progress/", OutreachTaskProgressView.as_view(), name="outreach-task-progress"),
    path("outreach-tasks/<int:pk>/targets/", OutreachTargetCollectionView.as_view(), name="outreach-target-collection"),
    path("outreach-tasks/<int:task_pk>/targets/<int:target_pk>/", OutreachTargetDetailView.as_view(), name="outreach-target-detail"),
    path("outreach-tasks/<int:pk>/influencers/", OutreachTargetCollectionView.as_view(), name="outreach-influencer-collection"),
    path("outreach-tasks/<int:task_pk>/influencers/<int:target_pk>/", OutreachTargetDetailView.as_view(), name="outreach-influencer-detail"),
    path("outreach-tasks/<int:pk>/status/", OutreachTaskStatusView.as_view(), name="outreach-task-status"),
    path("sample-fulfillments/", SampleFulfillmentCollectionView.as_view(), name="sample-fulfillment-collection"),
    path("sample-fulfillments/<int:pk>/status/", SampleFulfillmentStatusView.as_view(), name="sample-fulfillment-status"),
    path("product-price-lookup/", ProductPriceLookupView.as_view(), name="product-price-lookup"),
]
