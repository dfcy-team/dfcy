from django.urls import path

from . import views


urlpatterns = [
    path("requirements/duplicate-check/", views.duplicate_check),
    path("projects/", views.project_collection),
    path("projects/<int:pk>/", views.project_detail),
    path("product-archives/", views.product_archive_collection),
    path("product-archives/<int:pk>/", views.product_archive_detail),
    path("product-archives/<int:pk>/confirm/", views.product_archive_confirm),
    path("product-archives/<int:pk>/confirm-trial/", views.product_archive_confirm),
    path("product-archives/<int:pk>/trial-confirm/", views.product_archive_confirm),
    path("product-archives/<int:pk>/generate-trial/", views.product_archive_generate_trial),
    path("product-archives/<int:pk>/formalize/", views.product_archive_formalize),
    path("product-archives/<int:pk>/convert/", views.product_archive_formalize),
    path("product-archives/<int:pk>/promote/", views.product_archive_formalize),
    # Short aliases keep the endpoint convenient for existing development
    # workspace clients without adding another top-level menu.
    path("archives/", views.product_archive_collection),
    path("archives/<int:pk>/", views.product_archive_detail),
    path("archives/<int:pk>/confirm/", views.product_archive_confirm),
    path("archives/<int:pk>/confirm-trial/", views.product_archive_confirm),
    path("archives/<int:pk>/trial-confirm/", views.product_archive_confirm),
    path("archives/<int:pk>/formalize/", views.product_archive_formalize),
    path("archives/<int:pk>/convert/", views.product_archive_formalize),
    path("archives/<int:pk>/promote/", views.product_archive_formalize),
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
