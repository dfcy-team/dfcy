from django.urls import path

from . import views


urlpatterns = [
    path("definitions/", views.definition_list, name="config-definition-list"),
    path("values/", views.config_values, name="config-values"),
    path("values/<int:pk>/approve/", views.approve_value, name="config-value-approve"),
    path("values/<int:pk>/rollback/", views.rollback_value, name="config-value-rollback"),
    path("change-logs/", views.change_log_list, name="config-change-log-list"),
]
