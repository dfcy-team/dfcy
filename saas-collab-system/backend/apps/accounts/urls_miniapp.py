from django.urls import path

from .miniapp_views import (
    MiniAppCurrentUserView,
    MiniAppHealthView,
    MiniAppLoginView,
    MiniAppRefreshView,
)


urlpatterns = [
    path("health/", MiniAppHealthView.as_view(), name="miniapp-health"),
    path("auth/login/", MiniAppLoginView.as_view(), name="miniapp-auth-login"),
    path("auth/refresh/", MiniAppRefreshView.as_view(), name="miniapp-auth-refresh"),
    path("auth/me/", MiniAppCurrentUserView.as_view(), name="miniapp-auth-me"),
]
