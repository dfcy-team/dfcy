from django.urls import path
from .best_glink_callbacks import receive as receive_best_glink

from .views import platform_health


urlpatterns = [
    path('best/glink/<int:config_id>/', receive_best_glink, name='best-glink-callback'),
    path("health/", platform_health, name="platform-health"),
]
