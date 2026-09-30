from django.urls import path
from . import dataset_views

from .views import (
    health,
    report_catalog,
    report_export_collection,
    report_export_detail,
    report_export_download,
    report_export_file,
)


urlpatterns = [
    path("datasets/", dataset_views.report_datasets, name="report-datasets"),
    path("query/", dataset_views.report_query, name="report-query"),
    path("views/", dataset_views.report_view_collection, name="report-view-list"),
    path("views/<int:pk>/", dataset_views.report_view_detail, name="report-view-detail"),
    path("health/", health, name="report-health"),
    path("catalog/", report_catalog, name="report-catalog"),
    path("exports/", report_export_collection, name="report-export-collection"),
    path("exports/<int:pk>/", report_export_detail, name="report-export-detail"),
    path("exports/<int:pk>/download/", report_export_download, name="report-export-download"),
    path("exports/<int:pk>/file/", report_export_file, name="report-export-file"),
]
