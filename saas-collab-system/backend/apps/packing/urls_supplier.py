from django.urls import path

from . import views


urlpatterns = [
    path("batches/", views.supplier_batch_collection),
    path("batches/<int:pk>/", views.supplier_batch_detail),
    path("batches/<int:pk>/boxes/", views.supplier_box_collection),
    path("batches/<int:pk>/boxes/<int:box_id>/", views.supplier_box_detail),
    path("batches/<int:pk>/boxes/<int:box_id>/actions/remove/", views.supplier_box_remove),
    path("batches/<int:pk>/actions/complete/", views.supplier_batch_complete),
    path("batches/<int:pk>/change-requests/", views.supplier_change_collection),
    path("batches/<int:pk>/actions/generate-label/", views.supplier_batch_label),
    path("boxes/<int:box_id>/actions/generate-label/", views.supplier_box_label),
    path("standards/current/", views.supplier_standard),
]
