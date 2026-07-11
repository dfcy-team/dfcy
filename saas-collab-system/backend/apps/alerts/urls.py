from django.urls import path

from . import views


urlpatterns = [
    path("inventory/", views.inventory_alert_list, name="inventory-alert-list"),
    path("inventory/evaluate-mock/", views.inventory_alert_evaluate_mock, name="inventory-alert-evaluate-mock"),
    path("inventory/<int:pk>/", views.inventory_alert_detail, name="inventory-alert-detail"),
    path("inventory/<int:pk>/assign/", views.inventory_alert_assign, name="inventory-alert-assign"),
    path("inventory/<int:pk>/silence/", views.inventory_alert_silence, name="inventory-alert-silence"),
    path("inventory/<int:pk>/close/", views.inventory_alert_close, name="inventory-alert-close"),
]
