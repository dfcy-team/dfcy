from django.urls import path

from .views_internal import (
    ReleaseActionView,
    ReleaseApprovalDecisionView,
    ReleaseBuildConfirmView,
    ReleaseContractCollectionView,
    ReleaseContractDetailView,
    ReleaseGateRecordView,
)


urlpatterns = [
    path("contracts/", ReleaseContractCollectionView.as_view(), name="release-contracts"),
    path("contracts/<int:pk>/", ReleaseContractDetailView.as_view(), name="release-contract-detail"),
    path("contracts/<int:pk>/gates/", ReleaseGateRecordView.as_view(), name="release-contract-gates"),
    path(
        "contracts/<int:pk>/approvals/",
        ReleaseApprovalDecisionView.as_view(),
        name="release-contract-approvals",
    ),
    path(
        "contracts/<int:pk>/build/",
        ReleaseBuildConfirmView.as_view(),
        name="release-contract-build",
    ),
    path(
        "contracts/<int:pk>/actions/<slug:action>/",
        ReleaseActionView.as_view(),
        name="release-contract-action",
    ),
]
