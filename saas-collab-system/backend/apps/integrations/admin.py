from django.contrib import admin

from .models import (
    APIDataQualityCheck,
    APIIntegrationConfig,
    APISyncLog,
    APISyncTask,
    IntegrationAuditLog,
    PlatformIntegrationConfig,
)


@admin.register(PlatformIntegrationConfig)
class PlatformIntegrationConfigAdmin(admin.ModelAdmin):
    list_display = ("tenant", "platform", "account_alias", "environment", "status", "credential_key_version")
    list_filter = ("platform", "environment", "status", "tenant")
    search_fields = ("account_alias", "credential_fingerprint", "tenant__name", "tenant__code")
    exclude = ("credential_ciphertext",)


@admin.register(IntegrationAuditLog)
class IntegrationAuditLogAdmin(admin.ModelAdmin):
    list_display = ("tenant", "integration_config", "action", "actor", "result", "created_at")
    list_filter = ("action", "result", "tenant")
    search_fields = ("integration_config__account_alias", "actor__username", "tenant__code")


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
