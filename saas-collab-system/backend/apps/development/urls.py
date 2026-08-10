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
]
