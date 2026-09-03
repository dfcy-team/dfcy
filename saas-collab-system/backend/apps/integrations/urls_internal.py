from django.urls import path

from . import views
from . import production_settings_api


urlpatterns = [
    path(
        "production-settings/",
        production_settings_api.production_settings_collection,
        name="integration-production-settings",
    ),
    path(
        "production-settings/versions/<int:pk>/",
        production_settings_api.production_settings_version,
        name="integration-production-settings-version",
    ),
    path(
        "production-settings/versions/",
        # Map the alias directly to the already decorated view.  Calling one
        # @api_view wrapper from another makes DRF try to initialise a
        # Request object twice and breaks POSTs from APIClient/browser clients.
        production_settings_api.production_settings_collection,
        name="integration-production-settings-versions",
    ),
    path(
        "production-settings/versions/<int:pk>/approve/",
        production_settings_api.production_settings_version,
        name="integration-production-settings-version-approve",
    ),
    path(
        "production-settings/versions/<int:pk>/rollback/",
        production_settings_api.production_settings_version_rollback,
        name="integration-production-settings-version-rollback",
    ),
    path("workspace/", views.integration_workspace_view, name="integration-workspace"),
    path("readiness/", views.platform_integration_readiness, name="platform-integration-readiness"),
    path("audit/", views.integration_audit_collection, name="integration-audit-collection"),
    path(
        "readiness/configs/<int:pk>/repair-contract/",
        views.repair_readiness_contract,
        name="platform-readiness-contract-repair",
    ),
    path(
        "readiness/configs/<int:pk>/readonly-approval/",
        views.set_readiness_readonly_approval,
        name="platform-readiness-readonly-approval",
    ),
    path("subject-api-access/", views.subject_api_access_detail, name="subject-api-access-detail"),
    path("platform-schemas/<str:platform>/", views.platform_config_schema, name="platform-config-schema"),
    path("configs/", views.integration_config_collection, name="integration-config-collection"),
    path("workspace-configs/", views.create_handoff_integration_config, name="integration-workspace-config-create"),
    path("configs/<int:pk>/", views.integration_config_detail, name="integration-config-detail"),
    path("configs/<int:pk>/rotate/", views.rotate_integration_credentials, name="integration-config-rotate"),
    path(
        "configs/<int:pk>/credentials/rotate/",
        views.rotate_integration_secret_values,
        name="integration-config-secret-rotate",
    ),
    path(
        "configs/<int:pk>/credentials/clear/",
        views.clear_integration_secret_values,
        name="integration-config-secret-clear",
    ),
    path("configs/<int:pk>/audit/", views.integration_config_audit, name="integration-config-audit"),
    path("configs/<int:pk>/disable/", views.disable_integration_config, name="integration-config-disable"),
    path("configs/<int:pk>/delete/", views.delete_integration_config, name="integration-config-delete"),
    path("configs/<int:pk>/verify/", views.verify_integration_config, name="integration-config-verify"),
    path("configs/<int:pk>/reference-check/", views.check_integration_reference, name="integration-config-reference-check"),
    path("configs/<int:pk>/consistency-check/", views.check_integration_consistency, name="integration-config-consistency-check"),
    path("configs/<int:pk>/readonly-check/", views.check_integration_readonly_connection, name="integration-config-readonly-check"),
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
        "store-authorizations/oauth/callback/lazada/",
        views.marketplace_oauth_callback_lazada,
        name="store-authorization-oauth-callback-lazada",
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
        "store-authorizations/<int:pk>/refresh/",
        views.refresh_store_authorization,
        name="store-authorization-refresh",
    ),
    path(
        "store-authorizations/<int:pk>/revoke/",
        views.revoke_store_authorization,
        name="store-authorization-revoke",
    ),
    path(
        "store-authorizations/<int:pk>/",
        views.store_authorization_detail,
        name="store-authorization-detail",
    ),
    path(
        "store-authorizations/<int:pk>/capabilities/",
        views.store_authorization_capabilities,
        name="store-authorization-capabilities",
    ),
    path("store-mappings/", views.store_mapping_collection, name="store-mapping-collection"),
    path("store-mappings/<int:pk>/", views.store_mapping_detail, name="store-mapping-detail"),
    path("product-mappings/", views.product_mapping_collection, name="product-mapping-collection"),
    path("product-mappings/<int:pk>/", views.product_mapping_detail, name="product-mapping-detail"),
    path("sync-jobs/", views.sync_job_collection, name="sync-job-collection"),
    path("sync-jobs/<int:pk>/", views.sync_job_detail, name="sync-job-detail"),
    path("sync-jobs/<int:pk>/toggle/", views.toggle_sync_job, name="sync-job-toggle"),
    path("sync-jobs/<int:pk>/delete/", views.sync_job_delete, name="sync-job-delete"),
    path("sync-jobs/<int:pk>/run/", views.enqueue_sync_job, name="sync-job-run"),
    path("sync-jobs/<int:pk>/run-mock/", views.run_mock_sync_job, name="sync-job-run-mock"),
    path("sync-jobs/<int:pk>/disable/", views.disable_sync_job, name="sync-job-disable"),
    path("sync-runs/", views.sync_run_collection, name="sync-run-collection"),
    path("sync-runs/<int:pk>/", views.sync_run_detail, name="sync-run-detail"),
    path("sync-runs/<int:pk>/retry/", views.retry_sync_run, name="sync-run-retry"),
    path("sync-alert-incidents/", views.sync_alert_incident_collection, name="sync-alert-incident-collection"),
    path("sync-alert-incidents/<int:pk>/action/", views.sync_alert_incident_action, name="sync-alert-incident-action"),
    path("sync-alert-incidents/<int:pk>/retry/", views.sync_alert_incident_retry, name="sync-alert-incident-retry"),
]
