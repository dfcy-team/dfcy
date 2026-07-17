from django.urls import path

from .views import health, report_catalog, report_export_collection, report_export_detail, report_export_download


urlpatterns = [
    path("health/", health, name="report-health"),
    path("catalog/", report_catalog, name="report-catalog"),
    path("exports/", report_export_collection, name="report-export-collection"),
    path("exports/<int:pk>/", report_export_detail, name="report-export-detail"),
    path("exports/<int:pk>/download/", report_export_download, name="report-export-download"),
]
