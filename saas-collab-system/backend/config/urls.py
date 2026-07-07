"""Root URL configuration for the backend project."""
from django.urls import path


urlpatterns = [
    path("api/", lambda request: None, name="api-placeholder"),
]
