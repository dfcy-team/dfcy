from django.contrib import admin

from .models import (
    APIDataQualityCheck,
    APIIntegrationConfig,
    APISyncLog,
    APISyncTask,
    IntegrationAuditLog,
    MarketplaceProductMapping,
    MarketplaceStoreAuthorization,
    MarketplaceStoreMapping,
    OAuthStateSession,
    PlatformIntegrationConfig,
    SyncCursor,
    SyncJob,
    SyncRun,
    WebhookEvent,
)


@admin.register(PlatformIntegrationConfig)
class PlatformIntegrationConfigAdmin(admin.ModelAdmin):
    list_display = ("tenant", "platform", "account_alias", "environment", "status", "credential_reference_version")
    list_filter = ("platform", "environment", "status", "tenant")
    search_fields = ("account_alias", "credential_fingerprint", "tenant__name", "tenant__code")
    readonly_fields = (
        "credential_id",
        "token_id",
        "credential_mask",
        "credential_reference_version",
        "credential_key_version",
        "credential_fingerprint",
    )


@admin.register(IntegrationAuditLog)
class IntegrationAuditLogAdmin(admin.ModelAdmin):
    list_display = ("tenant", "integration_config", "action", "actor", "result", "created_at")
    list_filter = ("action", "result", "tenant")
    search_fields = ("integration_config__account_alias", "actor__username", "tenant__code")
    readonly_fields = tuple(field.name for field in IntegrationAuditLog._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MarketplaceStoreAuthorization)
class MarketplaceStoreAuthorizationAdmin(admin.ModelAdmin):
    list_display = ("tenant", "platform", "store", "region", "status", "credential_reference_version")
    list_filter = ("platform", "region", "status", "tenant")
    search_fields = ("store__code", "platform_store_id", "merchant_subject_id")
    readonly_fields = tuple(field.name for field in MarketplaceStoreAuthorization._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OAuthStateSession)
class OAuthStateSessionAdmin(admin.ModelAdmin):
    list_display = ("tenant", "platform", "store", "status", "expires_at", "consumed_at")
    list_filter = ("platform", "status", "tenant")
    search_fields = ("state_hash", "tenant__code")
    readonly_fields = tuple(field.name for field in OAuthStateSession._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MarketplaceStoreMapping)
class MarketplaceStoreMappingAdmin(admin.ModelAdmin):
    list_display = ("tenant", "platform", "store", "platform_store_id", "status", "mapping_source")
    list_filter = ("platform", "status", "mapping_source", "tenant")
    search_fields = ("platform_store_id", "store__code", "tenant__code")
    readonly_fields = tuple(field.name for field in MarketplaceStoreMapping._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MarketplaceProductMapping)
class MarketplaceProductMappingAdmin(admin.ModelAdmin):
    list_display = ("tenant", "platform", "store_mapping", "platform_variant_id", "status", "mapping_source")
    list_filter = ("platform", "status", "mapping_source", "tenant")
    search_fields = ("platform_product_id", "platform_variant_id", "platform_sku", "tenant__code")
    readonly_fields = tuple(field.name for field in MarketplaceProductMapping._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SyncJob)
class SyncJobAdmin(admin.ModelAdmin):
    list_display = (
        "tenant",
        "integration_config",
        "resource_type",
        "schedule_type",
        "status",
        "is_enabled",
        "lock_expires_at",
    )
    list_filter = ("resource_type", "schedule_type", "status", "is_enabled", "tenant")
    search_fields = ("integration_config__account_alias", "tenant__code")


@admin.register(SyncRun)
class SyncRunAdmin(admin.ModelAdmin):
    list_display = ("tenant", "sync_job", "run_id", "status", "fetched_count", "failed_count", "retry_count")
    list_filter = ("status", "tenant")
    search_fields = ("run_id", "idempotency_key", "error_code", "tenant__code")


@admin.register(SyncCursor)
class SyncCursorAdmin(admin.ModelAdmin):
    list_display = ("tenant", "sync_job", "cursor_key", "cursor_value", "updated_at")
    list_filter = ("tenant",)
    search_fields = ("cursor_key", "cursor_value", "tenant__code")


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ("tenant", "platform", "event_id", "event_type", "signature_status", "processing_status")
    list_filter = ("platform", "signature_status", "processing_status", "tenant")
    search_fields = ("event_id", "event_type", "payload_hash", "tenant__code")


@admin.register(APIIntegrationConfig)
class APIIntegrationConfigAdmin(admin.ModelAdmin):
    list_display = ("tenant", "platform", "shop_code", "status", "created_at", "updated_at")
    list_filter = ("platform", "status", "tenant")
    search_fields = ("shop_code", "tenant__name", "tenant__code")


@admin.register(APISyncTask)
class APISyncTaskAdmin(admin.ModelAdmin):
    list_display = ("tenant", "platform", "sync_type", "status", "last_sync_at", "next_sync_at")
    list_filter = ("platform", "sync_type", "status", "tenant")
    search_fields = ("tenant__name", "tenant__code")


@admin.register(APISyncLog)
class APISyncLogAdmin(admin.ModelAdmin):
    list_display = ("tenant", "task", "status", "started_at", "finished_at")
    list_filter = ("status", "tenant")
    search_fields = ("request_url", "error_message", "tenant__code")


@admin.register(APIDataQualityCheck)
class APIDataQualityCheckAdmin(admin.ModelAdmin):
    list_display = ("tenant", "sync_log", "check_type", "status")
    list_filter = ("status", "check_type", "tenant")
    search_fields = ("check_type", "message", "tenant__code")
