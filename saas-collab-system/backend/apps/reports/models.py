import hashlib
import json

from django.core.exceptions import ValidationError
from django.db import models

from apps.tenants.models import Tenant


class MetricDefinitionQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if "status" in kwargs:
            raise ValidationError("Metric definition lifecycle changes require the audited service.")
        immutable_updates = set(kwargs) & (MetricDefinition.IMMUTABLE_FIELDS | {"tenant"})
        if immutable_updates:
            raise ValidationError(
                f"Create a new metric definition version instead of updating: {', '.join(sorted(immutable_updates))}."
            )
        return super().update(**kwargs)

    def bulk_update(self, objs, fields, batch_size=None):
        if "status" in fields:
            raise ValidationError("Metric definition lifecycle changes require the audited service.")
        immutable_updates = set(fields) & MetricDefinition.IMMUTABLE_FIELDS
        if immutable_updates:
            raise ValidationError(
                f"Create new metric definition versions instead of updating: {', '.join(sorted(immutable_updates))}."
            )
        return super().bulk_update(objs, fields, batch_size=batch_size)

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("Metric definitions must be created individually through the version service.")


class MetricDataPointManager(models.Manager):
    def bulk_create(self, objs, **kwargs):
        for obj in objs:
            obj.full_clean()
        return super().bulk_create(objs, **kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        for obj in objs:
            obj.full_clean()
        return super().bulk_update(objs, fields, **kwargs)


class MetricDataPointQuerySet(models.QuerySet):
    OWNERSHIP_FIELDS = {
        "tenant",
        "tenant_id",
        "metric_definition",
        "metric_definition_id",
        "source_table",
        "source_record_id",
    }

    def update(self, **kwargs):
        ownership_updates = set(kwargs) & self.OWNERSHIP_FIELDS
        if ownership_updates:
            raise ValidationError(
                f"Use the metric ingestion service instead of updating: {', '.join(sorted(ownership_updates))}."
            )
        return super().update(**kwargs)


class SafeMetricDataPointManager(models.Manager.from_queryset(MetricDataPointQuerySet), MetricDataPointManager):
    pass


class MetricAggregateQuerySet(models.QuerySet):
    def bulk_create(self, objs, **kwargs):
        raise ValidationError("Metric aggregates can only be created by the aggregation service.")

    def update(self, **kwargs):
        raise ValidationError("Metric aggregates can only be updated by the aggregation service.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Metric aggregates can only be updated by the aggregation service.")


class MetricDefinition(models.Model):
    class AggregationMethod(models.TextChoices):
        SUM = "sum", "Sum"
        COUNT = "count", "Count"
        AVERAGE = "average", "Average"
        LATEST = "latest", "Latest"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"

    class MissingDataPolicy(models.TextChoices):
        MARK_MISSING = "mark_missing", "Mark missing"
        REJECT = "reject", "Reject incomplete data"
        ZERO_FILL = "zero_fill", "Fill missing values with zero"

    IMMUTABLE_FIELDS = {
        "tenant_id",
        "metric_code",
        "name",
        "description",
        "formula",
        "aggregation_method",
        "source_tables",
        "supported_granularities",
        "allowed_dimensions",
        "permission_code",
        "allow_drill_down",
        "contains_sensitive_data",
        "missing_data_policy",
        "minimum_quality_rate",
        "allows_automated_decision",
        "version",
    }

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="metric_definitions")
    metric_code = models.CharField(max_length=80)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    formula = models.TextField()
    aggregation_method = models.CharField(max_length=20, choices=AggregationMethod.choices)
    source_tables = models.JSONField(default=list)
    supported_granularities = models.JSONField(default=list)
    allowed_dimensions = models.JSONField(default=list, blank=True)
    permission_code = models.CharField(max_length=120, default="analytics.view")
    allow_drill_down = models.BooleanField(default=False)
    contains_sensitive_data = models.BooleanField(default=False)
    missing_data_policy = models.CharField(
        max_length=40,
        choices=MissingDataPolicy.choices,
        default=MissingDataPolicy.MARK_MISSING,
    )
    minimum_quality_rate = models.DecimalField(max_digits=5, decimal_places=4, default=1)
    allows_automated_decision = models.BooleanField(default=False, editable=False)
    version = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    objects = MetricDefinitionQuerySet.as_manager()

    class Meta:
        ordering = ["tenant_id", "metric_code", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "metric_code", "version"],
                name="uniq_metric_definition_version",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="metric_definition_version_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(allows_automated_decision=False),
                name="metric_definition_no_auto_decision",
            ),
            models.CheckConstraint(
                condition=models.Q(minimum_quality_rate__gte=0, minimum_quality_rate__lte=1),
                name="metric_definition_quality_rate_range",
            ),
        ]

    def __str__(self):
        return f"{self.tenant_id}:{self.metric_code}:v{self.version}"

    def clean(self):
        existing_versions = type(self).objects.filter(
            tenant_id=self.tenant_id,
            metric_code=self.metric_code,
        )
        if self.pk:
            current = existing_versions.filter(pk=self.pk).values("status").first()
            if (
                current
                and current["status"] != self.status
                and not getattr(self, "_definition_service_write", False)
            ):
                raise ValidationError("Metric definition lifecycle changes require the audited service.")
            return

        if not getattr(self, "_definition_service_write", False):
            raise ValidationError("Metric definitions must be created through the audited service.")
        if not existing_versions.exists() and self.version != 1:
            raise ValidationError("The first metric definition version must be 1.")

    def save(self, *args, **kwargs):
        if self.pk:
            current = type(self).objects.filter(pk=self.pk).values(*self.IMMUTABLE_FIELDS).first()
            if current:
                changed_fields = [field for field in self.IMMUTABLE_FIELDS if current[field] != getattr(self, field)]
                if changed_fields:
                    raise ValidationError(
                        f"Create a new metric definition version instead of updating: {', '.join(sorted(changed_fields))}."
                    )
        self.full_clean()
        try:
            super().save(*args, **kwargs)
        finally:
            self._definition_service_write = False


class MetricDataPoint(models.Model):
    class QualityStatus(models.TextChoices):
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"
        MISSING = "missing", "Missing"
        UNKNOWN = "unknown", "Unknown"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="metric_data_points")
    metric_definition = models.ForeignKey(
        MetricDefinition,
        on_delete=models.PROTECT,
        related_name="data_points",
    )
    source_table = models.CharField(max_length=120)
    source_batch = models.CharField(max_length=120)
    source_record_id = models.CharField(max_length=120)
    calculation_task = models.CharField(max_length=120, blank=True)
    occurred_at = models.DateTimeField()
    dimensions = models.JSONField(default=dict, blank=True)
    numeric_value = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    quality_status = models.CharField(
        max_length=20,
        choices=QualityStatus.choices,
        default=QualityStatus.UNKNOWN,
    )
    quality_detail = models.JSONField(default=dict, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = SafeMetricDataPointManager()

    class Meta:
        ordering = ["tenant_id", "metric_definition_id", "occurred_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "source_table", "source_record_id", "metric_definition"],
                name="uniq_metric_source_record",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "metric_definition", "occurred_at"], name="idx_metric_point_period"),
            models.Index(fields=["tenant", "quality_status"], name="idx_metric_point_quality"),
        ]

    def clean(self):
        if self.metric_definition_id and self.tenant_id != self.metric_definition.tenant_id:
            raise ValidationError("Metric data point and definition must belong to the same tenant.")
        if self.source_table not in self.metric_definition.source_tables:
            raise ValidationError("Source table is not allowed by the metric definition.")

    def __str__(self):
        return f"{self.tenant_id}:{self.metric_definition.metric_code}:{self.source_record_id}"

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class MetricAggregate(models.Model):
    class Granularity(models.TextChoices):
        DAY = "day", "Day"
        WEEK = "week", "Week"
        MONTH = "month", "Month"

    class QualityStatus(models.TextChoices):
        PASSED = "passed", "Passed"
        DEGRADED = "degraded", "Degraded"
        NO_VALID_DATA = "no_valid_data", "No valid data"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="metric_aggregates")
    metric_definition = models.ForeignKey(
        MetricDefinition,
        on_delete=models.PROTECT,
        related_name="aggregates",
    )
    definition_version = models.PositiveIntegerField()
    granularity = models.CharField(max_length=20, choices=Granularity.choices)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    dimensions = models.JSONField(default=dict, blank=True)
    dimensions_hash = models.CharField(max_length=64)
    numeric_value = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    valid_point_count = models.PositiveIntegerField(default=0)
    excluded_point_count = models.PositiveIntegerField(default=0)
    quality_status = models.CharField(max_length=30, choices=QualityStatus.choices)
    quality_detail = models.JSONField(default=dict)
    is_formal = models.BooleanField(default=False)
    source_lineage = models.JSONField(default=dict)
    refreshed_at = models.DateTimeField()
    calculated_at = models.DateTimeField(auto_now=True)
    objects = MetricAggregateQuerySet.as_manager()

    class Meta:
        ordering = ["tenant_id", "metric_definition_id", "-period_end", "dimensions_hash"]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "tenant",
                    "metric_definition",
                    "definition_version",
                    "granularity",
                    "period_start",
                    "period_end",
                    "dimensions_hash",
                ],
                name="uniq_metric_aggregate_slice",
            ),
            models.CheckConstraint(
                condition=models.Q(period_start__lt=models.F("period_end")),
                name="metric_aggregate_valid_period",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(is_formal=False)
                    | models.Q(quality_status="passed", valid_point_count__gt=0)
                ),
                name="formal_metric_aggregate_has_valid_data",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "metric_definition", "period_end"], name="idx_metric_aggregate_period"),
            models.Index(fields=["tenant", "quality_status"], name="idx_metric_aggregate_quality"),
        ]

    @staticmethod
    def hash_dimensions(dimensions):
        canonical = json.dumps(dimensions or {}, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def clean(self):
        if self.metric_definition_id and self.tenant_id != self.metric_definition.tenant_id:
            raise ValidationError("Metric aggregate and definition must belong to the same tenant.")
        if self.metric_definition_id and self.definition_version != self.metric_definition.version:
            raise ValidationError("Aggregate definition version must match its metric definition.")
        if self.is_formal and (
            self.quality_status != self.QualityStatus.PASSED or self.valid_point_count == 0
        ):
            raise ValidationError("Formal aggregates require passed quality and valid data.")

    def save(self, *args, **kwargs):
        if not getattr(self, "_aggregation_service_write", False):
            raise ValidationError("Metric aggregates can only be persisted by the aggregation service.")
        self.dimensions_hash = self.hash_dimensions(self.dimensions)
        self.full_clean()
        try:
            super().save(*args, **kwargs)
        finally:
            self._aggregation_service_write = False

    def __str__(self):
        return f"{self.tenant_id}:{self.metric_definition.metric_code}:{self.period_start}"


class MetricAggregateLineageQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Metric lineage is immutable.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Metric lineage is immutable.")


class MetricAggregateLineageManager(models.Manager.from_queryset(MetricAggregateLineageQuerySet)):
    def bulk_create(self, objs, **kwargs):
        seen = set()
        for obj in objs:
            if obj.tenant_id != obj.aggregate.tenant_id:
                raise ValidationError("Metric lineage and aggregate must belong to the same tenant.")
            key = (obj.aggregate_id, obj.source_table, obj.source_batch, obj.calculation_task)
            if key in seen:
                raise ValidationError("Duplicate metric lineage entry in bulk create.")
            seen.add(key)
        return super().bulk_create(objs, **kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        raise ValidationError("Metric lineage is immutable.")


class MetricAggregateLineage(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="metric_aggregate_lineage")
    aggregate = models.ForeignKey(MetricAggregate, on_delete=models.CASCADE, related_name="lineage_records")
    source_table = models.CharField(max_length=120)
    source_batch = models.CharField(max_length=120)
    calculation_task = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = MetricAggregateLineageManager()

    class Meta:
        ordering = ["tenant_id", "aggregate_id", "source_table", "source_batch", "calculation_task"]
        constraints = [
            models.UniqueConstraint(
                fields=["aggregate", "source_table", "source_batch", "calculation_task"],
                name="uniq_metric_aggregate_lineage",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "aggregate"], name="idx_metric_lineage_aggregate"),
            models.Index(fields=["tenant", "source_batch"], name="idx_metric_lineage_batch"),
        ]

    def clean(self):
        if self.aggregate_id and self.tenant_id != self.aggregate.tenant_id:
            raise ValidationError("Metric lineage and aggregate must belong to the same tenant.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.aggregate_id}:{self.source_table}:{self.source_batch}"
