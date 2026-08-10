from django.urls import path

from .views import purchase_order_collection, purchase_order_detail
from .views_supply import (
    internal_supply_order_action,
    internal_supply_order_collection,
    internal_supply_order_detail,
)


urlpatterns = [
    path("orders/", purchase_order_collection, name="purchase-order-collection"),
    path("orders/<int:pk>/", purchase_order_detail, name="purchase-order-detail"),
    path("supply-orders/", internal_supply_order_collection, name="internal-supply-order-collection"),
    path("supply-orders/<int:pk>/", internal_supply_order_detail, name="internal-supply-order-detail"),
    path(
        "supply-orders/<int:pk>/actions/<str:action_name>/",
        internal_supply_order_action,
        name="internal-supply-order-action",
    ),
]
