from django.urls import path

from . import views


urlpatterns = [
    path("templates/", views.template_collection),
    path("profiles/", views.profile_collection),
    path("profiles/<int:pk>/", views.profile_detail),
    path("profiles/<int:pk>/submit/", views.profile_submit),
    path("profiles/<int:pk>/approve/", views.profile_approve),
    path("profiles/<int:pk>/publish/", views.profile_publish),
]
