from django.urls import path

from . import views


urlpatterns = [
    path("recommendations/", views.recommendation_list, name="replenishment-list"),
    path("recommendations/<int:pk>/", views.recommendation_detail, name="replenishment-detail"),
    path("evaluate-mock/", views.evaluate_mock, name="replenishment-evaluate-mock"),
    path("recommendations/<int:pk>/accept/", views.accept_recommendation, name="replenishment-accept"),
    path("recommendations/<int:pk>/reject/", views.reject_recommendation, name="replenishment-reject"),
]
