from django.urls import path
from . import views

urlpatterns = [
    path("options/", views.options),
    path("environments/", views.environments),
    path("environments/<int:pk>/", views.environment_status),
    path("batches/", views.batches),
    path("batches/<uuid:pk>/", views.batch_detail),
    path("batches/<uuid:pk>/retry/", views.retry),
    path("batches/<uuid:pk>/download/", views.download),
]
