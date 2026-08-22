from django.urls import path

from . import views


urlpatterns = [
    path("requirements/duplicate-check/", views.duplicate_check),
    path("projects/", views.project_collection),
    path("projects/<int:pk>/", views.project_detail),
    path("projects/<int:pk>/finalize/", views.project_finalize),
    path("projects/<int:pk>/advance/", views.project_advance),
    path("costs/<int:pk>/calculate/", views.cost_calculate),
    path("costs/<int:pk>/approve/", views.cost_approve),
    path("sales/import/", views.sales_import),
    path("sales/summary/", views.sales_summary),
    path("reviews/reminders/", views.review_reminders),
    path("competitor-reports/", views.competitor_report_collection),
    path("competitor-reports/<str:report_id>/", views.competitor_report_detail),
    path("competitor-reports/<str:report_id>/evidence/", views.competitor_report_evidence),
    path("requirements/<int:requirement_id>/competitors/", views.requirement_competitor_collection),
    path(
        "requirements/<int:requirement_id>/competitors/<int:link_id>/",
        views.requirement_competitor_detail,
    ),
    # Compatibility alias used by clients that call the relation a link.
    path("requirements/<int:requirement_id>/competitor-links/", views.requirement_competitor_collection),
    path(
        "requirements/<int:requirement_id>/competitor-links/<int:link_id>/",
        views.requirement_competitor_detail,
    ),
]
