from django.urls import path

from .views_miniapp import MiniAppReleaseContractDetailView, MiniAppReleaseWorkbenchView


urlpatterns = [
    path("workbench/", MiniAppReleaseWorkbenchView.as_view(), name="miniapp-release-workbench"),
    path(
        "contracts/<int:pk>/",
        MiniAppReleaseContractDetailView.as_view(),
        name="miniapp-release-contract-detail",
    ),
]
