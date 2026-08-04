from django.urls import path

from . import views


urlpatterns = [
    path("configs/", views.integration_config_collection, name="integration-config-collection"),
    path("configs/<int:pk>/", views.integration_config_detail, name="integration-config-detail"),
    path("configs/<int:pk>/rotate/", views.rotate_integration_credentials, name="integration-config-rotate"),
    path("configs/<int:pk>/disable/", views.disable_integration_config, name="integration-config-disable"),
    path("configs/<int:pk>/verify/", views.verify_integration_config, name="integration-config-verify"),
    path(
        "store-authorizations/",
        views.store_authorization_collection,
        name="store-authorization-collection",
    ),
    path(
        "store-authorizations/<int:pk>/",
        views.store_authorization_detail,
        name="store-authorization-detail",
    ),
    path("store-authorizations/oauth/targets/", views.oauth_target_collection, name="oauth-target-collection"),
    path("store-authorizations/oauth/initiate/", views.oauth_initiate, name="oauth-initiate"),
    path("oauth-attempts/<int:pk>/", views.oauth_attempt_detail, name="oauth-attempt-detail"),
    path("store-authorizations/<int:pk>/refresh/", views.refresh_store_authorization, name="store-authorization-refresh"),
    path("store-authorizations/<int:pk>/revoke/", views.revoke_store_authorization, name="store-authorization-revoke"),
    path("store-authorizations/<int:pk>/retry/", views.retry_store_authorization, name="store-authorization-retry"),
    path("sync-jobs/", views.sync_job_collection, name="sync-job-collection"),
    path("sync-jobs/<int:pk>/run-mock/", views.run_mock_sync_job, name="sync-job-run-mock"),
    path("sync-jobs/<int:pk>/disable/", views.disable_sync_job, name="sync-job-disable"),
    path("sync-runs/", views.sync_run_collection, name="sync-run-collection"),
    path("sync-runs/<int:pk>/", views.sync_run_detail, name="sync-run-detail"),
]
