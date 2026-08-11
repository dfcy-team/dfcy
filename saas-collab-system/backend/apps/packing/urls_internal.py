from django.urls import path

from . import views


urlpatterns = [
    path("batches/", views.internal_batch_collection),
    path("batches/<int:pk>/", views.internal_batch_detail),
    path("batches/<int:pk>/boxes/", views.internal_box_collection),
    path("batches/<int:pk>/boxes/<int:box_id>/", views.internal_box_detail),
    path("batches/<int:pk>/boxes/<int:box_id>/actions/remove/", views.internal_box_remove),
    path("batches/<int:pk>/actions/complete/", views.internal_batch_complete),
    path("batches/<int:pk>/actions/cancel/", views.internal_batch_cancel),
    path("batches/<int:pk>/change-requests/", views.internal_change_collection),
    path("change-requests/", views.internal_review_collection),
    path("change-requests/<int:change_id>/", views.internal_review_detail),
    path("change-requests/<int:change_id>/actions/approve/", views.internal_review_approve),
    path("change-requests/<int:change_id>/actions/reject/", views.internal_review_reject),
    path("batches/<int:pk>/actions/generate-label/", views.internal_batch_label),
    path("boxes/<int:box_id>/actions/generate-label/", views.internal_box_label),
    path("standards/current/", views.internal_standard),
]
