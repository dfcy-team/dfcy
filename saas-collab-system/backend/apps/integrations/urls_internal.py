from django.urls import path

from . import views


urlpatterns = [
    path("configs/", views.integration_config_collection, name="integration-config-collection"),
    path("configs/<int:pk>/", views.integration_config_detail, name="integration-config-detail"),
    path("configs/<int:pk>/rotate/", views.rotate_integration_credentials, name="integration-config-rotate"),
    path("configs/<int:pk>/disable/", views.disable_integration_config, name="integration-config-disable"),
    path("configs/<int:pk>/verify/", views.verify_integration_config, name="integration-config-verify"),
]
