from django.urls import path

from . import views


urlpatterns = [
    path("metrics/", views.metric_definition_collection, name="analytics-metric-list"),
    path("metrics/<int:pk>/", views.metric_definition_detail, name="analytics-metric-detail"),
    path("aggregates/", views.metric_aggregate_collection, name="analytics-aggregate-list"),
    path("aggregates/<int:pk>/", views.metric_aggregate_detail, name="analytics-aggregate-detail"),
    path("aggregate-mock/", views.aggregate_mock, name="analytics-aggregate-mock"),
]
