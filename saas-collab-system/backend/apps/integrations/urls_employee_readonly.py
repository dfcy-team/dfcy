from django.urls import path
from . import employee_readonly as views

urlpatterns = [
    path("authorize/", views.authorize),
    path("exchange/", views.exchange),
    path("revoke/", views.revoke),
    path("revoke-all/", views.revoke_all),
    path("capabilities/", views.capabilities),
    path("resources/<str:resource>/", views.collection),
]
