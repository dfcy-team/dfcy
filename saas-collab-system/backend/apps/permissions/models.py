from django.conf import settings
from django.db import models

from apps.tenants.models import Tenant


class Role(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="roles")
    name = models.CharField(max_length=100)
    code = models.SlugField(max_length=80)
    permissions = models.ManyToManyField("Permission", blank=True, related_name="roles")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "name"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "code"], name="uniq_role_code_per_tenant"),
        ]

    def __str__(self):
        return f"{self.tenant.code}:{self.code}"


class Permission(models.Model):
    code = models.CharField(max_length=120, unique=True)
    name = models.CharField(max_length=100)
    module = models.CharField(max_length=80)
    action = models.CharField(max_length=80)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["module", "action", "code"]

    def __str__(self):
        return self.code


class UserRole(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="user_roles")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="user_roles")
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="user_roles")

    class Meta:
        ordering = ["tenant_id", "user_id", "role_id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "user", "role"], name="uniq_user_role_per_tenant"),
        ]

    def __str__(self):
        return f"{self.user_id}:{self.role_id}"


class DataScope(models.Model):
    class ScopeType(models.TextChoices):
        ALL = "all", "All"
        DEPARTMENT = "department", "Department"
        OWN = "own", "Own"
        CUSTOM = "custom", "Custom"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="data_scopes")
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="data_scopes")
    scope_type = models.CharField(max_length=20, choices=ScopeType.choices)
    config = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["tenant_id", "role_id", "scope_type"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "role", "scope_type"], name="uniq_data_scope_per_role"),
        ]

    def __str__(self):
        return f"{self.role.code}:{self.scope_type}"
