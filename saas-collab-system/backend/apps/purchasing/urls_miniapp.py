from django.urls import path

from .views_supply import (
    miniapp_supply_order_action,
    miniapp_supply_order_collection,
    miniapp_supply_order_detail,
)


urlpatterns = [
    path("orders/", miniapp_supply_order_collection, name="miniapp-supply-order-collection"),
    path("orders/<int:pk>/", miniapp_supply_order_detail, name="miniapp-supply-order-detail"),
    path(
        "orders/<int:pk>/actions/<str:action_name>/",
        miniapp_supply_order_action,
        name="miniapp-supply-order-action",
    ),
]
