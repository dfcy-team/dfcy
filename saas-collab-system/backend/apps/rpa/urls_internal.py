from django.urls import path

from apps.rpa.internal_views import (
    AccountLockCollectionView,
    AssignManualView,
    DeviceCollectionView,
    DeviceDetailView,
    DeviceDryRunView,
    ManualQueueView,
    PageSignatureCollectionView,
    RetryMockView,
    RunCollectionView,
    RunDetailView,
    StabilityDashboardView,
    TaskCollectionView,
    TaskDetailView,
)


urlpatterns = [
    path("tasks/", TaskCollectionView.as_view(), name="internal-rpa-task-list"),
    path("tasks/<int:task_id>/", TaskDetailView.as_view(), name="internal-rpa-task-detail"),
    path("tasks/<int:task_id>/assign-manual/", AssignManualView.as_view(), name="internal-rpa-assign-manual"),
    path("tasks/<int:task_id>/retry-mock/", RetryMockView.as_view(), name="internal-rpa-retry-mock"),
    path("runs/", RunCollectionView.as_view(), name="internal-rpa-run-list"),
    path("runs/<int:run_id>/", RunDetailView.as_view(), name="internal-rpa-run-detail"),
    path("devices/", DeviceCollectionView.as_view(), name="internal-rpa-device-list"),
    path("devices/<int:device_id>/", DeviceDetailView.as_view(), name="internal-rpa-device-detail"),
    path("devices/<int:device_id>/dry-run/", DeviceDryRunView.as_view(), name="internal-rpa-device-dry-run"),
    path("manual-queue/", ManualQueueView.as_view(), name="internal-rpa-manual-queue"),
    path("account-locks/", AccountLockCollectionView.as_view(), name="internal-rpa-account-locks"),
    path("page-signatures/", PageSignatureCollectionView.as_view(), name="internal-rpa-page-signatures"),
    path("stability/", StabilityDashboardView.as_view(), name="internal-rpa-stability"),
]
