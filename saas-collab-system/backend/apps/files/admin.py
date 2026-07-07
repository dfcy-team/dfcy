from django.contrib import admin

from .models import AttachmentFile


@admin.register(AttachmentFile)
class AttachmentFileAdmin(admin.ModelAdmin):
    list_display = ("tenant", "file_name", "file_type", "file_size", "uploaded_by", "business_type", "business_id", "is_private", "created_at")
    list_filter = ("tenant", "file_type", "is_private", "business_type")
    search_fields = ("file_name", "file_path", "business_type", "business_id", "uploaded_by__username")
