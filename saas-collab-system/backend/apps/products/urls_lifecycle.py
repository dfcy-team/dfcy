from django.urls import path

from . import lifecycle_views


urlpatterns = [
    path("reviews/", lifecycle_views.review_list, name="lifecycle-review-list"),
    path("reviews/<int:pk>/", lifecycle_views.review_detail, name="lifecycle-review-detail"),
    path("evaluate-mock/", lifecycle_views.evaluate_mock, name="lifecycle-evaluate-mock"),
    path("reviews/<int:pk>/confirm/", lifecycle_views.confirm_review, name="lifecycle-confirm"),
    path("reviews/<int:pk>/reject/", lifecycle_views.reject_review, name="lifecycle-reject"),
    path("decisions/", lifecycle_views.decision_list, name="lifecycle-decision-list"),
]
