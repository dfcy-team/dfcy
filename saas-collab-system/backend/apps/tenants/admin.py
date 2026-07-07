from django.contrib import admin

from .models import Department, Tenant


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "status", "created_at", "updated_at")
    list_filter = ("status",)
    search_fields = ("name", "code")


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "parent", "status")
    list_filter = ("status", "tenant")
    search_fields = ("name", "tenant__name", "tenant__code")
