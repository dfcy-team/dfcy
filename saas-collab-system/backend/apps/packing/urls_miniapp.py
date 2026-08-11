from django.urls import path

from . import views


urlpatterns = [
    path("batches/", views.miniapp_batch_collection),
    path("batches/<int:pk>/", views.miniapp_batch_detail),
    path("batches/<int:pk>/boxes/", views.miniapp_box_collection),
    path("batches/<int:pk>/boxes/<int:box_id>/", views.miniapp_box_detail),
    path("batches/<int:pk>/boxes/<int:box_id>/actions/remove/", views.miniapp_box_remove),
    path("batches/<int:pk>/actions/complete/", views.miniapp_batch_complete),
    path("batches/<int:pk>/change-requests/", views.miniapp_change_collection),
    path("batches/<int:pk>/actions/generate-label/", views.miniapp_batch_label),
    path("boxes/<int:box_id>/actions/generate-label/", views.miniapp_box_label),
    path("standards/current/", views.miniapp_standard),
]
