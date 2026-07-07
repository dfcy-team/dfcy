from django.contrib import admin

from .models import DataScope, Permission, Role, UserRole


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "tenant", "status", "created_at", "updated_at")
    list_filter = ("status", "tenant")
    search_fields = ("name", "code", "tenant__name", "tenant__code")


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "module", "action")
    list_filter = ("module", "action")
    search_fields = ("code", "name", "module", "action")


@admin.register(UserRole)
class UserRoleAdmin(admin.ModelAdmin):
    list_display = ("tenant", "user", "role")
    list_filter = ("tenant", "role")
    search_fields = ("user__username", "role__name", "role__code", "tenant__code")


@admin.register(DataScope)
class DataScopeAdmin(admin.ModelAdmin):
    list_display = ("tenant", "role", "scope_type")
    list_filter = ("tenant", "scope_type")
    search_fields = ("role__name", "role__code", "tenant__code")
