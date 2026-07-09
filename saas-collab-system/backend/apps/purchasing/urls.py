from django.urls import path

from .views import purchase_order_collection, purchase_order_detail


urlpatterns = [
    path("orders/", purchase_order_collection, name="purchase-order-collection"),
    path("orders/<int:pk>/", purchase_order_detail, name="purchase-order-detail"),
]
