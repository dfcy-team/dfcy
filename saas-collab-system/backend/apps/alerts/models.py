from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.products.models import ProductSKU, ProductSPU
from apps.tenants.models import Tenant


class InventoryAlertType(models.TextChoices):
    STOCKOUT_RISK = "stockout_risk", "Stockout risk"
    OVERSTOCK_RISK = "overstock_risk", "Overstock risk"
    LOW_COVERAGE = "low_coverage", "Low coverage"
    SLOW_MOVING = "slow_moving", "Slow moving"


class InventoryAlertRule(models.Model):
    class Severity(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="inventory_alert_rules")
    rule_code = models.CharField(max_length=80)
    alert_type = models.CharField(max_length=30, choices=InventoryAlertType.choices)
    threshold_config = models.JSONField(default=dict)
    severity = models.CharField(max_length=20, choices=Severity.choices)
    silence_minutes = models.PositiveIntegerField(default=60)
    is_enabled = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    effective_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "rule_code", "-version"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "rule_code", "version"], name="uniq_inventory_rule_version"),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="inventory_rule_version_gte_1"),
        ]
        indexes = [
            models.Index(fields=["tenant", "alert_type", "is_enabled"], name="idx_inventory_rule_type"),
        ]


class InventoryAlert(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ASSIGNED = "assigned", "Assigned"
        IN_PROGRESS = "in_progress", "In progress"
        SILENCED = "silenced", "Silenced"
        CLOSED = "closed", "Closed"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="inventory_alerts")
    rule = models.ForeignKey(InventoryAlertRule, on_delete=models.PROTECT, related_name="alerts")
    spu = models.ForeignKey(ProductSPU, on_delete=models.PROTECT, related_name="inventory_alerts", null=True, blank=True)
    sku = models.ForeignKey(ProductSKU, on_delete=models.PROTECT, related_name="inventory_alerts", null=True, blank=True)
    warehouse_code = models.CharField(max_length=80, blank=True)
    alert_type = models.CharField(max_length=30, choices=InventoryAlertType.choices)
    severity = models.CharField(max_length=20, choices=InventoryAlertRule.Severity.choices)
    available_stock = models.DecimalField(max_digits=16, decimal_places=4)
    in_transit_stock = models.DecimalField(max_digits=16, decimal_places=4)
    average_daily_sales = models.DecimalField(max_digits=16, decimal_places=4, null=True, blank=True)
    coverage_days = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    threshold_value = models.DecimalField(max_digits=12, decimal_places=4)
    dedup_key = models.CharField(max_length=64)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assigned_inventory_alerts",
        null=True,
        blank=True,
    )
    reason = models.TextField()
    source_summary = models.JSONField(default=dict)
    triggered_at = models.DateTimeField()
    silenced_until = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "-triggered_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "dedup_key"], name="uniq_inventory_alert_dedup"),
            models.CheckConstraint(
                condition=models.Q(spu__isnull=False) | models.Q(sku__isnull=False),
                name="inventory_alert_has_product",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status", "severity"], name="idx_inventory_alert_state"),
            models.Index(fields=["tenant", "sku", "alert_type"], name="idx_inventory_alert_sku"),
        ]

    def clean(self):
        if self.rule_id and self.rule.tenant_id != self.tenant_id:
            raise ValidationError("Inventory alert and rule must belong to the same tenant.")
        if self.spu_id and self.spu.tenant_id != self.tenant_id:
            raise ValidationError("Inventory alert and SPU must belong to the same tenant.")
        if self.sku_id and self.sku.tenant_id != self.tenant_id:
            raise ValidationError("Inventory alert and SKU must belong to the same tenant.")
        if self.assigned_to_id and (
            self.assigned_to.tenant_id != self.tenant_id or self.assigned_to.user_type != "internal"
        ):
            raise ValidationError("Inventory alert assignee must be an internal user in the same tenant.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

class InventoryAlertEvent(models.Model):
    class EventType(models.TextChoices):
        TRIGGERED = "triggered", "Triggered"
        DEDUPLICATED = "deduplicated", "Deduplicated"
        ASSIGNED = "assigned", "Assigned"
        SILENCED = "silenced", "Silenced"
        CLOSED = "closed", "Closed"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="inventory_alert_events")
    alert = models.ForeignKey(InventoryAlert, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=30, choices=EventType.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="inventory_alert_events",
        null=True,
        blank=True,
    )
    detail = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["tenant_id", "alert_id", "created_at", "id"]
        indexes = [models.Index(fields=["tenant", "alert", "event_type"], name="idx_inventory_alert_event")]

    def clean(self):
        if self.alert_id and self.alert.tenant_id != self.tenant_id:
            raise ValidationError("Inventory alert event must belong to the alert tenant.")
        if self.actor_id and self.actor.tenant_id != self.tenant_id:
            raise ValidationError("Inventory alert event actor must belong to the same tenant.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
