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


class BusinessAlertType(models.TextChoices):
    SALES_DROP = "sales_drop", "Sales drop"
    SLOW_MOVING = "slow_moving", "Slow moving"
    RECONCILIATION_DIFFERENCE = "reconciliation_difference", "Reconciliation difference"
    SUPPLIER_OVERDUE = "supplier_overdue", "Supplier overdue"
    RPA_FAILURE = "rpa_failure", "RPA failure"
    PAGE_SIGNATURE_CHANGE = "page_signature_change", "Page signature change"
    SYNC_FAILURE = "sync_failure", "Sync failure"
    STALE_DATA = "stale_data", "Stale data"


class BusinessAlertRuleQuerySet(models.QuerySet):
    IMMUTABLE_FIELDS = {
        "tenant", "tenant_id", "rule_code", "alert_type", "severity",
        "condition_config", "silence_minutes", "version", "effective_at",
    }

    def update(self, **kwargs):
        if set(kwargs) & self.IMMUTABLE_FIELDS:
            raise ValidationError("Create a new business alert rule version instead of updating in place.")
        return super().update(**kwargs)

    def bulk_update(self, objs, fields, batch_size=None):
        if set(fields) & self.IMMUTABLE_FIELDS:
            raise ValidationError("Create new business alert rule versions instead of updating in place.")
        return super().bulk_update(objs, fields, batch_size=batch_size)


class BusinessAlertRule(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="business_alert_rules")
    rule_code = models.CharField(max_length=80)
    alert_type = models.CharField(max_length=40, choices=BusinessAlertType.choices)
    severity = models.CharField(max_length=20, choices=InventoryAlertRule.Severity.choices)
    condition_config = models.JSONField(default=dict)
    silence_minutes = models.PositiveIntegerField(default=60)
    is_enabled = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    effective_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    objects = BusinessAlertRuleQuerySet.as_manager()

    class Meta:
        ordering = ["tenant_id", "rule_code", "-version"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "rule_code", "version"], name="uniq_business_alert_rule_version"),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="business_alert_rule_version_gte_1"),
        ]
        indexes = [models.Index(fields=["tenant", "alert_type", "is_enabled"], name="idx_business_alert_rule")]

    def save(self, *args, **kwargs):
        if self.pk:
            fields = BusinessAlertRuleQuerySet.IMMUTABLE_FIELDS - {"tenant"}
            current = type(self).objects.filter(pk=self.pk).values(*fields).first()
            if current and any(current[field] != getattr(self, field) for field in fields):
                raise ValidationError("Create a new business alert rule version instead of updating in place.")
        self.full_clean()
        super().save(*args, **kwargs)


class BusinessAlertQuerySet(models.QuerySet):
    STATE_FIELDS = {"status", "assigned_to", "assigned_to_id", "silenced_until", "closed_at"}

    def update(self, **kwargs):
        if set(kwargs) & self.STATE_FIELDS:
            raise ValidationError("Business alert state changes require the audited action service.")
        return super().update(**kwargs)

    def bulk_update(self, objs, fields, batch_size=None):
        if set(fields) & self.STATE_FIELDS:
            raise ValidationError("Business alert state changes require the audited action service.")
        return super().bulk_update(objs, fields, batch_size=batch_size)

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("Business alerts must be created by the evaluation service.")


class BusinessAlert(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ASSIGNED = "assigned", "Assigned"
        SILENCED = "silenced", "Silenced"
        CLOSED = "closed", "Closed"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="business_alerts")
    rule = models.ForeignKey(BusinessAlertRule, on_delete=models.PROTECT, related_name="alerts")
    business_type = models.CharField(max_length=80)
    business_id = models.CharField(max_length=120)
    severity = models.CharField(max_length=20, choices=InventoryAlertRule.Severity.choices)
    title = models.CharField(max_length=200)
    detail = models.JSONField(default=dict)
    metric_value = models.DecimalField(max_digits=20, decimal_places=4)
    threshold_value = models.DecimalField(max_digits=20, decimal_places=4)
    dedup_key = models.CharField(max_length=64)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assigned_business_alerts",
        null=True,
        blank=True,
    )
    triggered_at = models.DateTimeField()
    silenced_until = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    objects = BusinessAlertQuerySet.as_manager()

    class Meta:
        ordering = ["tenant_id", "-triggered_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["tenant", "dedup_key"], name="uniq_business_alert_dedup")]
        indexes = [
            models.Index(fields=["tenant", "status", "severity"], name="idx_business_alert_state"),
            models.Index(fields=["tenant", "business_type", "business_id"], name="idx_business_alert_target"),
        ]

    def clean(self):
        if self.rule_id and self.rule.tenant_id != self.tenant_id:
            raise ValidationError("Business alert and rule must belong to the same tenant.")
        if self.assigned_to_id and (
            self.assigned_to.tenant_id != self.tenant_id or self.assigned_to.user_type != "internal"
        ):
            raise ValidationError("Business alert assignee must be an internal user in the same tenant.")

    def save(self, *args, **kwargs):
        if not self.pk and not getattr(self, "_action_service_write", False):
            raise ValidationError("Business alerts must be created by the evaluation service.")
        if self.pk and not getattr(self, "_action_service_write", False):
            current = type(self).objects.filter(pk=self.pk).values(
                "status", "assigned_to_id", "silenced_until", "closed_at"
            ).first()
            if current and any(
                current[field] != getattr(self, field)
                for field in ("status", "assigned_to_id", "silenced_until", "closed_at")
            ):
                raise ValidationError("Business alert state changes require the audited action service.")
        self.full_clean()
        try:
            super().save(*args, **kwargs)
        finally:
            self._action_service_write = False


class BusinessAlertActionLogQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Business alert action logs are immutable.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Business alert action logs are immutable.")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("Business alert action logs require the audited action service.")


class BusinessAlertActionLog(models.Model):
    class Action(models.TextChoices):
        TRIGGERED = "triggered", "Triggered"
        DEDUPLICATED = "deduplicated", "Deduplicated"
        ASSIGNED = "assigned", "Assigned"
        SILENCED = "silenced", "Silenced"
        CLOSED = "closed", "Closed"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="business_alert_action_logs")
    alert = models.ForeignKey(BusinessAlert, on_delete=models.CASCADE, related_name="action_logs")
    action = models.CharField(max_length=30, choices=Action.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="business_alert_action_logs",
        null=True,
        blank=True,
    )
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = BusinessAlertActionLogQuerySet.as_manager()

    class Meta:
        ordering = ["tenant_id", "alert_id", "created_at", "id"]
        indexes = [models.Index(fields=["tenant", "alert", "action"], name="idx_business_alert_action")]

    def clean(self):
        if self.alert_id and self.alert.tenant_id != self.tenant_id:
            raise ValidationError("Business alert action must belong to the alert tenant.")
        if self.actor_id and self.actor.tenant_id != self.tenant_id:
            raise ValidationError("Business alert actor must belong to the same tenant.")

    def save(self, *args, **kwargs):
        if not getattr(self, "_action_service_write", False):
            raise ValidationError("Business alert action logs require the audited action service.")
        self.full_clean()
        try:
            super().save(*args, **kwargs)
        finally:
            self._action_service_write = False
