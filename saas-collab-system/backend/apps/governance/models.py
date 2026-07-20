from django.db import models

from apps.tenants.models import Tenant


class ApiContract(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        MOCK = "mock", "Mock"
        SANDBOX = "sandbox", "Sandbox"
        CONNECTED = "connected", "Connected"
        DEGRADED = "degraded", "Degraded"
        DISABLED = "disabled", "Disabled"
        STALE = "stale", "Stale"

    class Compatibility(models.TextChoices):
        CURRENT = "current", "Current"
        DEPRECATED = "deprecated", "Deprecated"
        PENDING = "pending", "Pending"

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="governance_api_contracts",
    )
    module = models.SlugField(max_length=80)
    name = models.CharField(max_length=160)
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=240)
    owner = models.CharField(max_length=120)
    version = models.CharField(max_length=40)
    permission_code = models.CharField(max_length=120)
    data_scope_keys = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    compatibility = models.CharField(max_length=20, choices=Compatibility.choices, default=Compatibility.CURRENT)
    deprecation_at = models.DateTimeField(null=True, blank=True)
    request_fields = models.JSONField(default=list, blank=True)
    response_fields = models.JSONField(default=list, blank=True)
    error_codes = models.JSONField(default=list, blank=True)
    change_history = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["module", "path", "method", "id"]
        constraints = [
            models.UniqueConstraint(fields=["method", "path", "version"], name="uniq_governance_contract_version"),
        ]


class AssistantDefinition(models.Model):
    class Status(models.TextChoices):
        PLACEHOLDER = "placeholder", "Placeholder"
        REVIEW_PENDING = "review_pending", "Review pending"
        SANDBOX = "sandbox", "Sandbox"
        DISABLED = "disabled", "Disabled"

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="governance_assistants",
    )
    code = models.SlugField(max_length=80, unique=True)
    name = models.CharField(max_length=160)
    description = models.TextField()
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PLACEHOLDER)
    data_class = models.CharField(max_length=40, default="public_demo")
    allowed_tools = models.JSONField(default=list, blank=True)
    output_types = models.JSONField(default=list, blank=True)
    limitations = models.JSONField(default=list, blank=True)
    human_confirmation_required = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code", "id"]
