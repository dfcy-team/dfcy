from django.urls import path

from .views import (
    freeze_product_spu_code,
    product_research_collection,
    product_research_detail,
    product_sku_collection,
    product_sku_detail,
    product_spu_collection,
    product_spu_detail,
)


urlpatterns = [
    path("research/", product_research_collection, name="product-research-collection"),
    path("research/<int:pk>/", product_research_detail, name="product-research-detail"),
    path("spus/", product_spu_collection, name="product-spu-collection"),
    path("spus/<int:pk>/", product_spu_detail, name="product-spu-detail"),
    path("spus/<int:pk>/freeze-code/", freeze_product_spu_code, name="product-spu-freeze-code"),
    path("skus/", product_sku_collection, name="product-sku-collection"),
    path("skus/<int:pk>/", product_sku_detail, name="product-sku-detail"),
]
