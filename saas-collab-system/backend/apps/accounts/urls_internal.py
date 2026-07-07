from django.urls import path

from .views import internal_health


urlpatterns = [
    path("health/", internal_health, name="internal-health"),
]
