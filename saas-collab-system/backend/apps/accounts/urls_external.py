from django.urls import path

from .views import external_health


urlpatterns = [
    path("health/", external_health, name="external-health"),
]
