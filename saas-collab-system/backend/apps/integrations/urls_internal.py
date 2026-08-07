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
        "store-authorizations/oauth/start/",
        views.start_marketplace_store_oauth,
        name="store-authorization-oauth-start",
    ),
    path(
        "store-authorizations/oauth/callback/shopee/",
        views.marketplace_oauth_callback_shopee,
        name="store-authorization-oauth-callback-shopee",
    ),
    path(
        "store-authorizations/oauth/callback/tiktok/",
        views.marketplace_oauth_callback_tiktok,
        name="store-authorization-oauth-callback-tiktok",
    ),
    path(
        "store-authorizations/<int:pk>/",
        views.store_authorization_detail,
        name="store-authorization-detail",
    ),
    path("sync-jobs/", views.sync_job_collection, name="sync-job-collection"),
    path("sync-jobs/<int:pk>/run-mock/", views.run_mock_sync_job, name="sync-job-run-mock"),
    path("sync-jobs/<int:pk>/disable/", views.disable_sync_job, name="sync-job-disable"),
    path("sync-runs/", views.sync_run_collection, name="sync-run-collection"),
    path("sync-runs/<int:pk>/", views.sync_run_detail, name="sync-run-detail"),
]
