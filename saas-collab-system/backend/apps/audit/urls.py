from django.urls import path

from .views import OperationLogCollectionView, OperationLogDetailView, OperationLogExportView


urlpatterns = [
    path("operation-logs/", OperationLogCollectionView.as_view(), name="operation-log-collection"),
    # Keep the export route ahead of the integer detail route so the public
    # contract remains unambiguous.
    path("operation-logs/export/", OperationLogExportView.as_view(), name="operation-log-export"),
    path("operation-logs/<int:pk>/", OperationLogDetailView.as_view(), name="operation-log-detail"),
]
