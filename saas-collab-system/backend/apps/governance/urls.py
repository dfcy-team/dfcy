from django.urls import path

from .views import (
    ApiContractCheckMockView,
    ApiContractCollectionView,
    ApiContractDetailView,
    AssistantCollectionView,
    AssistantDetailView,
    AssistantEvaluateMockView,
)


urlpatterns = [
    path("api-contracts/", ApiContractCollectionView.as_view(), name="governance-contracts"),
    path("api-contracts/check-mock/", ApiContractCheckMockView.as_view(), name="governance-contract-check-mock"),
    path("api-contracts/<int:pk>/", ApiContractDetailView.as_view(), name="governance-contract-detail"),
    path("assistants/", AssistantCollectionView.as_view(), name="governance-assistants"),
    path("assistants/<int:pk>/", AssistantDetailView.as_view(), name="governance-assistant-detail"),
    path("assistants/<int:pk>/evaluate-mock/", AssistantEvaluateMockView.as_view(), name="governance-assistant-evaluate-mock"),
]
