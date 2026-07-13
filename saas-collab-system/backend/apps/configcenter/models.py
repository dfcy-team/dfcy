import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.tenants.models import Tenant


FORBIDDEN_CONFIG_KEY_PATTERN = re.compile(
    r"(^|[._-])(api[_-]?(key|secret)|token|cookie|session|password|passwd|credential|secret)($|[._-])",
    re.IGNORECASE,
)


class SystemConfigDefinition(models.Model):
    class ScopeType(models.TextChoices):
        TENANT = "tenant", "Tenant"
        SYSTEM = "system", "System"

    class ValueType(models.TextChoices):
        STRING = "string", "String"
        INTEGER = "integer", "Integer"
        DECIMAL = "decimal", "Decimal"
        BOOLEAN = "boolean", "Boolean"
        JSON = "json", "JSON"

    config_key = models.CharField(max_length=120, unique=True)
    scope_type = models.CharField(max_length=20, choices=ScopeType.choices)
    value_type = models.CharField(max_length=20, choices=ValueType.choices)
    default_value = models.JSONField(null=True, blank=True)
    is_sensitive = models.BooleanField(default=False)
    requires_approval = models.BooleanField(default=False)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["scope_type", "config_key"]

    def clean(self):
        if FORBIDDEN_CONFIG_KEY_PATTERN.search(self.config_key):
            raise ValidationError("Credential, token, cookie, session, and secret config keys are prohibited.")
        if self.is_sensitive and self.default_value not in (None, {}, ""):
            raise ValidationError("Sensitive config definitions cannot contain a plaintext default value.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class TenantConfigVersionQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Config versions are immutable and require the version service.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Config versions are immutable and require the version service.")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("Config versions require the version service.")


class TenantConfigVersion(models.Model):
    class Status(models.TextChoices):
        PENDING_APPROVAL = "pending_approval", "Pending approval"
        APPROVED = "approved", "Approved for future activation"
        EFFECTIVE = "effective", "Effective"
        SUPERSEDED = "superseded", "Superseded"
        REJECTED = "rejected", "Rejected"

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="config_versions",
        null=True,
        blank=True,
    )
    definition = models.ForeignKey(SystemConfigDefinition, on_delete=models.PROTECT, related_name="versions")
    config_key = models.CharField(max_length=120)
    scope_key = models.CharField(max_length=80)
    version = models.PositiveIntegerField()
    value = models.JSONField()
    status = models.CharField(max_length=30, choices=Status.choices)
    effective_at = models.DateTimeField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_config_versions",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approved_config_versions",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    objects = TenantConfigVersionQuerySet.as_manager()

    class Meta:
        ordering = ["scope_key", "config_key", "-version"]
        constraints = [
            models.UniqueConstraint(fields=["scope_key", "config_key", "version"], name="uniq_config_scope_version"),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="config_version_gte_1"),
        ]
        indexes = [
            models.Index(fields=["scope_key", "config_key", "status"], name="idx_config_scope_status"),
            models.Index(fields=["tenant", "status", "effective_at"], name="idx_tenant_config_effective"),
        ]

    def clean(self):
        if self.definition_id and self.config_key != self.definition.config_key:
            raise ValidationError("Config version key must match its definition.")
        if self.definition_id:
            if self.definition.scope_type == SystemConfigDefinition.ScopeType.SYSTEM:
                if self.tenant_id is not None or self.scope_key != "system":
                    raise ValidationError("System config versions must use the system scope.")
            elif self.tenant_id is None or self.scope_key != f"tenant:{self.tenant_id}":
                raise ValidationError("Tenant config versions must use their tenant scope.")
        if self.created_by_id and self.tenant_id and self.created_by.tenant_id != self.tenant_id:
            raise ValidationError("Tenant config creator must belong to the same tenant.")
        if self.approved_by_id and self.tenant_id and self.approved_by.tenant_id != self.tenant_id:
            raise ValidationError("Tenant config approver must belong to the same tenant.")

    def save(self, *args, **kwargs):
        if not getattr(self, "_config_service_write", False):
            raise ValidationError("Config versions require the version service.")
        self.full_clean()
        try:
            super().save(*args, **kwargs)
        finally:
            self._config_service_write = False


class ConfigChangeLogQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Config change logs are immutable.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Config change logs are immutable.")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("Config change logs require the config service.")


class ConfigChangeLog(models.Model):
    class Action(models.TextChoices):
        CREATE_VERSION = "create_version", "Create version"
        APPROVE = "approve", "Approve"
        ROLLBACK = "rollback", "Rollback"

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="config_change_logs",
        null=True,
        blank=True,
    )
    config_key = models.CharField(max_length=120)
    scope_key = models.CharField(max_length=80)
    from_version = models.PositiveIntegerField(null=True, blank=True)
    to_version = models.PositiveIntegerField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="config_change_logs")
    action = models.CharField(max_length=30, choices=Action.choices)
    masked_detail = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = ConfigChangeLogQuerySet.as_manager()

    class Meta:
        ordering = ["scope_key", "config_key", "created_at", "id"]
        indexes = [models.Index(fields=["scope_key", "config_key", "created_at"], name="idx_config_change_log")]

    def save(self, *args, **kwargs):
        if not getattr(self, "_config_service_write", False):
            raise ValidationError("Config change logs require the config service.")
        self.full_clean()
        try:
            super().save(*args, **kwargs)
        finally:
            self._config_service_write = False
