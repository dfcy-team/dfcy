from django.urls import path

from .views import SupplierWebLoginView, SupplierWebRefreshView, external_health


urlpatterns = [
    path("health/", external_health, name="external-health"),
    path("auth/login/", SupplierWebLoginView.as_view(), name="supplier-web-auth-login"),
    path("auth/refresh/", SupplierWebRefreshView.as_view(), name="supplier-web-auth-refresh"),
]
