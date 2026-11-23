from django.urls import path
from . import views

urlpatterns = [
    path("workspace/", views.Workspace.as_view()),
    path("configs/<int:store_id>/", views.ConfigDetail.as_view()),
    path("batches/", views.Batches.as_view()),
    path("batches/<uuid:pk>/", views.BatchDetail.as_view()),
    path("activities/<int:pk>/source/", views.CopySource.as_view()),
    path("activities/<int:pk>/", views.ActivityDetail.as_view()),
    path("previews/", views.Previews.as_view()),
    path("plans/", views.Plans.as_view()),
    path("plans/<int:pk>/", views.Plans.as_view()),
    path("notifications/", views.NotificationSettings.as_view()),
]
