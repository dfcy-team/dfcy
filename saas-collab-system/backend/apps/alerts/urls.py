from django.urls import path

from . import views


urlpatterns = [
    path("inventory/", views.inventory_alert_list, name="inventory-alert-list"),
    path("inventory/evaluate-mock/", views.inventory_alert_evaluate_mock, name="inventory-alert-evaluate-mock"),
    path("inventory/<int:pk>/", views.inventory_alert_detail, name="inventory-alert-detail"),
    path("inventory/<int:pk>/assign/", views.inventory_alert_assign, name="inventory-alert-assign"),
    path("inventory/<int:pk>/silence/", views.inventory_alert_silence, name="inventory-alert-silence"),
    path("inventory/<int:pk>/close/", views.inventory_alert_close, name="inventory-alert-close"),
    path("business/", views.business_alert_list, name="business-alert-list"),
    path("business/evaluate-mock/", views.business_alert_evaluate_mock, name="business-alert-evaluate-mock"),
    path("business/<int:pk>/", views.business_alert_detail, name="business-alert-detail"),
    path("business/<int:pk>/assign/", views.business_alert_assign, name="business-alert-assign"),
    path("business/<int:pk>/silence/", views.business_alert_silence, name="business-alert-silence"),
    path("business/<int:pk>/close/", views.business_alert_close, name="business-alert-close"),
]
