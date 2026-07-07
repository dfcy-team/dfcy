from django.urls import path

from .views import platform_health


urlpatterns = [
    path("health/", platform_health, name="platform-health"),
]
