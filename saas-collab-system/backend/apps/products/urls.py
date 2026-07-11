from django.urls import path

from .views import (
    freeze_product_spu_code,
    confirm_status_recommendation,
    evaluate_mock_status_view,
    product_research_collection,
    product_research_detail,
    product_sku_collection,
    product_sku_detail,
    product_spu_collection,
    product_spu_detail,
    reject_status_recommendation,
    status_recommendation_collection,
    status_recommendation_detail,
    status_transition_collection,
)


urlpatterns = [
    path("research/", product_research_collection, name="product-research-collection"),
    path("research/<int:pk>/", product_research_detail, name="product-research-detail"),
    path("spus/", product_spu_collection, name="product-spu-collection"),
    path("spus/<int:pk>/", product_spu_detail, name="product-spu-detail"),
    path("spus/<int:pk>/freeze-code/", freeze_product_spu_code, name="product-spu-freeze-code"),
    path("skus/", product_sku_collection, name="product-sku-collection"),
    path("skus/<int:pk>/", product_sku_detail, name="product-sku-detail"),
    path("status-recommendations/", status_recommendation_collection, name="product-status-recommendation-collection"),
    path(
        "status-recommendations/<int:pk>/",
        status_recommendation_detail,
        name="product-status-recommendation-detail",
    ),
    path(
        "status-recommendations/<int:pk>/confirm/",
        confirm_status_recommendation,
        name="product-status-recommendation-confirm",
    ),
    path(
        "status-recommendations/<int:pk>/reject/",
        reject_status_recommendation,
        name="product-status-recommendation-reject",
    ),
    path("status-transitions/", status_transition_collection, name="product-status-transition-collection"),
    path("status/evaluate-mock/", evaluate_mock_status_view, name="product-status-evaluate-mock"),
]
