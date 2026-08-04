from django.urls import path

from .views import oauth_callback, platform_health


urlpatterns = [
    path("health/", platform_health, name="platform-health"),
    path("oauth/<str:platform>/callback/", oauth_callback, name="marketplace-oauth-callback"),
]
