from django.contrib import admin

from .models import ApprovalLog, DataImportLog, NotificationMessage, OperationLog, SystemExceptionLog


@admin.register(OperationLog)
class OperationLogAdmin(admin.ModelAdmin):
    list_display = ("tenant", "user", "module", "action", "object_type", "object_id", "created_at")
    list_filter = ("tenant", "module", "action")
    search_fields = ("module", "action", "object_type", "object_id", "user__username")


@admin.register(ApprovalLog)
class ApprovalLogAdmin(admin.ModelAdmin):
    list_display = ("tenant", "user", "business_type", "business_id", "action", "status", "created_at")
    list_filter = ("tenant", "business_type", "status")
    search_fields = ("business_type", "business_id", "user__username")


@admin.register(NotificationMessage)
class NotificationMessageAdmin(admin.ModelAdmin):
    list_display = ("tenant", "user", "title", "message_type", "status", "created_at")
    list_filter = ("tenant", "message_type", "status")
    search_fields = ("title", "message", "user__username")


@admin.register(DataImportLog)
class DataImportLogAdmin(admin.ModelAdmin):
    list_display = ("tenant", "import_type", "file_name", "status", "total_count", "success_count", "failed_count")
    list_filter = ("tenant", "import_type", "status")
    search_fields = ("import_type", "file_name", "created_by__username")


@admin.register(SystemExceptionLog)
class SystemExceptionLogAdmin(admin.ModelAdmin):
    list_display = ("tenant", "module", "exception_type", "severity", "created_at")
    list_filter = ("tenant", "module", "severity")
    search_fields = ("module", "exception_type", "message")
