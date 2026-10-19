from django.urls import path
from . import dataset_views
from .analysis_jobs import analysis_collection, analysis_detail
from .async_exports import export_job_collection, export_job_detail
from .collaboration_views import report_exception_create, report_exception_source

from .views import (
    health,
    report_catalog,
    report_export_collection,
    report_export_detail,
    report_export_download,
    report_export_file,
)


urlpatterns = [
    path("export-jobs/", export_job_collection, name="report-export-jobs"),
    path("export-jobs/<int:pk>/", export_job_detail, name="report-export-job-detail"),
    path("analysis-jobs/", analysis_collection, name="report-analysis-jobs"),
    path("analysis-jobs/<int:pk>/", analysis_detail, name="report-analysis-detail"),
    path("datasets/", dataset_views.report_datasets, name="report-datasets"),
    path("query/", dataset_views.report_query, name="report-query"),
    path("filter-options/", dataset_views.report_filter_options, name="report-filter-options"),
    path("exceptions/", report_exception_create, name="report-exception-create"),
    path("exceptions/<int:pk>/source/", report_exception_source, name="report-exception-source"),
    path("views/", dataset_views.report_view_collection, name="report-view-list"),
    path("views/<int:pk>/", dataset_views.report_view_detail, name="report-view-detail"),
    path("views/<int:pk>/history/", dataset_views.report_view_history, name="report-view-history"),
    path("health/", health, name="report-health"),
    path("catalog/", report_catalog, name="report-catalog"),
    path("exports/", report_export_collection, name="report-export-collection"),
    path("exports/<int:pk>/", report_export_detail, name="report-export-detail"),
    path("exports/<int:pk>/download/", report_export_download, name="report-export-download"),
    path("exports/<int:pk>/file/", report_export_file, name="report-export-file"),
]
