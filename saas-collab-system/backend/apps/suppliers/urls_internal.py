from django.urls import path

from .views import (
    internal_performance_calculate_mock,
    internal_performance_collection,
    internal_performance_detail,
)


urlpatterns = [
    path("performance/", internal_performance_collection, name="supplier-performance-collection"),
    path(
        "performance/calculate-mock/",
        internal_performance_calculate_mock,
        name="supplier-performance-calculate-mock",
    ),
    path(
        "performance/<int:supplier_id>/",
        internal_performance_detail,
        name="supplier-performance-detail",
    ),
]
