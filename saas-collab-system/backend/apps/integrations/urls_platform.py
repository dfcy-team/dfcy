from django.urls import path

from .views import platform_health
from .shopee_order_push_views import receive
from .marketplace_order_push import receive as receive_marketplace_order


urlpatterns = [
    path('lazada/order-status/<int:config_id>/', receive_marketplace_order, {'platform': 'lazada'}, name='lazada-order-status-push'),
    path('tiktok/order-status/<int:config_id>/', receive_marketplace_order, {'platform': 'tiktok'}, name='tiktok-order-status-push'),
    path('shopee/order-status/<int:config_id>/', receive, name='shopee-order-status-push'),
    path("health/", platform_health, name="platform-health"),
]
