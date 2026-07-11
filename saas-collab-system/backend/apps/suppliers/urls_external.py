from django.urls import path

from .views import (
    external_supplier_performance,
    external_supplier_performance_history,
    supplier_shipment_collection,
    supplier_shipment_detail,
    supplier_task_collection,
    supplier_task_detail,
    supplier_task_feedback,
)


urlpatterns = [
    path("performance/", external_supplier_performance, name="supplier-performance"),
    path("performance/history/", external_supplier_performance_history, name="supplier-performance-history"),
    path("tasks/", supplier_task_collection, name="supplier-task-collection"),
    path("tasks/<int:pk>/", supplier_task_detail, name="supplier-task-detail"),
    path("tasks/<int:pk>/feedback/", supplier_task_feedback, name="supplier-task-feedback"),
    path("shipments/", supplier_shipment_collection, name="supplier-shipment-collection"),
    path("shipments/<int:pk>/", supplier_shipment_detail, name="supplier-shipment-detail"),
]
