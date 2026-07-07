from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import InternalLoginView, current_user, internal_health


urlpatterns = [
    path("health/", internal_health, name="internal-health"),
    path("auth/login/", InternalLoginView.as_view(), name="internal-auth-login"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="internal-auth-refresh"),
    path("auth/me/", current_user, name="internal-auth-me"),
]
