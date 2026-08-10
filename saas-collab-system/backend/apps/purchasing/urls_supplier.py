from django.urls import path

from .views_supply import (
    supplier_supply_order_action,
    supplier_supply_order_collection,
    supplier_supply_order_detail,
)


urlpatterns = [
    path("", supplier_supply_order_collection, name="supplier-supply-order-collection"),
    path("<int:pk>/", supplier_supply_order_detail, name="supplier-supply-order-detail"),
    path(
        "<int:pk>/actions/<str:action_name>/",
        supplier_supply_order_action,
        name="supplier-supply-order-action",
    ),
]
