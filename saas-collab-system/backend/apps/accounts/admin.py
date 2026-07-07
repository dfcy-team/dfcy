from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import CustomUser, ExternalUserProfile, InternalUserProfile


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ("username", "email", "phone", "user_type", "tenant", "is_active", "is_staff")
    list_filter = ("user_type", "is_active", "is_staff", "tenant")
    search_fields = ("username", "email", "phone", "tenant__name", "tenant__code")
    ordering = ("username",)

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Contact", {"fields": ("email", "phone")}),
        ("Tenant", {"fields": ("tenant", "user_type")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "email", "phone", "user_type", "tenant", "password1", "password2"),
            },
        ),
    )
    readonly_fields = ("created_at", "updated_at", "last_login")


@admin.register(InternalUserProfile)
class InternalUserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "tenant", "department", "employee_no")
    list_filter = ("tenant", "department")
    search_fields = ("user__username", "user__email", "employee_no")


@admin.register(ExternalUserProfile)
class ExternalUserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "tenant", "supplier_id", "company_name", "contact_name")
    list_filter = ("tenant",)
    search_fields = ("user__username", "user__email", "company_name", "contact_name")
