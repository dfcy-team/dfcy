from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import write_operation_log
from apps.permissions.services import check_user_permission

from .models import MetricAggregate, MetricAggregateLineage, MetricDataPoint, MetricDefinition


MAX_AGGREGATION_WINDOWS = {
    MetricAggregate.Granularity.DAY: timedelta(days=1),
    MetricAggregate.Granularity.WEEK: timedelta(days=7),
    MetricAggregate.Granularity.MONTH: timedelta(days=31),
}
MAX_LINEAGE_VALUES = 100
LINEAGE_BATCH_SIZE = 1000
MAX_AGGREGATION_POINTS = 100000


def _definition_audit_data(definition):
    return {
        "metric_code": definition.metric_code,
        "version": definition.version,
        "name": definition.name,
        "description": definition.description,
        "formula": definition.formula,
        "aggregation_method": definition.aggregation_method,
        "source_tables": definition.source_tables,
        "supported_granularities": definition.supported_granularities,
        "allowed_dimensions": definition.allowed_dimensions,
        "permission_code": definition.permission_code,
        "missing_data_policy": definition.missing_data_policy,
        "minimum_quality_rate": str(definition.minimum_quality_rate),
        "status": definition.status,
    }


def _validate_definition_actor(*, actor, tenant, reason):
    if not actor or not getattr(actor, "is_active", False) or getattr(actor, "user_type", None) != "internal":
        raise ValidationError("An active internal actor is required for metric version changes.")
    reason = str(reason or "").strip()
    if not reason:
        raise ValidationError("A version change reason is required.")
    if not check_user_permission(actor, "analytics.manage"):
        raise ValidationError("The actor is not authorized to manage metric definitions.")
    if actor.tenant_id != tenant.id:
        raise ValidationError("Metric definition actor must belong to the same tenant.")
    return reason


def create_metric_definition(*, tenant, actor, reason, **definition_fields):
    reason = _validate_definition_actor(actor=actor, tenant=tenant, reason=reason)
    forbidden_fields = set(definition_fields) & {"tenant", "tenant_id", "version", "status", "allows_automated_decision"}
    if forbidden_fields:
        raise ValidationError(f"Unsupported initial definition fields: {', '.join(sorted(forbidden_fields))}.")

    with transaction.atomic():
        definition = MetricDefinition(
            tenant=tenant,
            version=1,
            status=MetricDefinition.Status.ACTIVE,
            **definition_fields,
        )
        definition._definition_service_write = True
        definition.save()
        write_operation_log(
            tenant=tenant,
            user=actor,
            module="analytics",
            action="metric_definition.create",
            object_type="MetricDefinition",
            object_id=definition.id,
            before_data={},
            after_data={"definition": _definition_audit_data(definition), "reason": reason},
        )
    return definition


def create_metric_definition_version(metric_definition, *, actor, reason, **changes):

    versioned_fields = MetricDefinition.IMMUTABLE_FIELDS - {
        "tenant_id",
        "metric_code",
        "version",
        "allows_automated_decision",
    }
    unsupported_fields = set(changes) - versioned_fields
    if unsupported_fields:
        raise ValidationError(f"Unsupported version fields: {', '.join(sorted(unsupported_fields))}.")

    with transaction.atomic():
        versions = list(
            MetricDefinition.objects.select_for_update()
            .filter(
                tenant_id=metric_definition.tenant_id,
                metric_code=metric_definition.metric_code,
            )
            .order_by("-version", "-id")
        )
        current = next((item for item in versions if item.pk == metric_definition.pk), None)
        if current is None:
            raise ValidationError("Metric definition does not exist in the requested version chain.")
        reason = _validate_definition_actor(actor=actor, tenant=current.tenant, reason=reason)
        latest = versions[0]
        if current.pk != latest.pk or current.status != MetricDefinition.Status.ACTIVE:
            raise ValidationError("New metric versions must be created from the latest active version.")

        latest_version = latest.version
        values = {field: getattr(current, field) for field in versioned_fields}
        values.update(changes)
        for item in versions:
            if item.status != MetricDefinition.Status.ACTIVE:
                continue
            item.status = MetricDefinition.Status.INACTIVE
            item._definition_service_write = True
            item.save(update_fields=["status", "updated_at"])
        new_definition = MetricDefinition(
            tenant=current.tenant,
            metric_code=current.metric_code,
            version=latest_version + 1,
            **values,
        )
        new_definition._definition_service_write = True
        new_definition.save()
        write_operation_log(
            tenant=current.tenant,
            user=actor,
            module="analytics",
            action="metric_definition.create_version",
            object_type="MetricDefinition",
            object_id=new_definition.id,
            before_data={"definition": _definition_audit_data(current)},
            after_data={"definition": _definition_audit_data(new_definition), "reason": reason},
        )
    return new_definition


def deactivate_metric_definition(metric_definition, *, actor, reason):
    with transaction.atomic():
        current = MetricDefinition.objects.select_for_update().get(pk=metric_definition.pk)
        reason = _validate_definition_actor(actor=actor, tenant=current.tenant, reason=reason)
        if current.status != MetricDefinition.Status.ACTIVE:
            raise ValidationError("Only active metric definitions can be deactivated.")
        before_data = _definition_audit_data(current)
        current.status = MetricDefinition.Status.INACTIVE
        current._definition_service_write = True
        current.save(update_fields=["status", "updated_at"])
        write_operation_log(
            tenant=current.tenant,
            user=actor,
            module="analytics",
            action="metric_definition.deactivate",
            object_type="MetricDefinition",
            object_id=current.id,
            before_data={"definition": before_data},
            after_data={"definition": _definition_audit_data(current), "reason": reason},
        )
    return current


def upsert_metric_data_point(*, tenant, metric_definition, source_table, source_record_id, **defaults):
    if metric_definition.tenant_id != tenant.id:
        raise ValidationError("Metric definition is outside the requested tenant.")
    if source_table not in metric_definition.source_tables:
        raise ValidationError("Source table is not allowed by the metric definition.")

    with transaction.atomic():
        point, created = MetricDataPoint.objects.update_or_create(
            tenant=tenant,
            metric_definition=metric_definition,
            source_table=source_table,
            source_record_id=source_record_id,
            defaults=defaults,
        )
    return point, created


@transaction.atomic
def aggregate_metric(
    *,
    tenant,
    metric_definition,
    period_start,
    period_end,
    granularity,
    dimensions=None,
    refreshed_at=None,
):
    if metric_definition.tenant_id != tenant.id:
        raise ValidationError("Metric definition is outside the requested tenant.")

    stored_definition = MetricDefinition.objects.filter(
        pk=metric_definition.pk,
        tenant=tenant,
    ).values("metric_code").first()
    if stored_definition is None:
        raise ValidationError("Metric definition does not exist in the requested tenant.")
    definition_versions = list(
        MetricDefinition.objects.select_for_update()
        .filter(tenant=tenant, metric_code=stored_definition["metric_code"])
        .order_by("-version", "-id")
    )
    current_definition = next(
        (definition for definition in definition_versions if definition.pk == metric_definition.pk),
        None,
    )
    latest_definition = definition_versions[0] if definition_versions else None
    if (
        current_definition is None
        or current_definition.status != MetricDefinition.Status.ACTIVE
        or latest_definition is None
        or current_definition.pk != latest_definition.pk
    ):
        raise ValidationError("Only active metric definitions can be aggregated.")
    metric_definition = current_definition
    if granularity not in MAX_AGGREGATION_WINDOWS:
        raise ValidationError("Unsupported aggregation granularity.")
    if granularity not in metric_definition.supported_granularities:
        raise ValidationError("Granularity is not supported by this metric definition.")
    if period_start >= period_end:
        raise ValidationError("period_start must be earlier than period_end.")
    if period_end - period_start > MAX_AGGREGATION_WINDOWS[granularity]:
        raise ValidationError(f"Aggregation period is too large for {granularity} granularity.")

    dimensions = dimensions or {}
    disallowed_dimensions = set(dimensions) - set(metric_definition.allowed_dimensions)
    if disallowed_dimensions:
        raise ValidationError(f"Unsupported dimensions: {', '.join(sorted(disallowed_dimensions))}.")

    refreshed_at = refreshed_at or timezone.now()
    base_points = MetricDataPoint.objects.filter(
        tenant=tenant,
        metric_definition=metric_definition,
        occurred_at__gte=period_start,
        occurred_at__lt=period_end,
    )
    for key, value in dimensions.items():
        base_points = base_points.filter(**{f"dimensions__{key}": value})
    point_rows = list(
        base_points.order_by("id").values(
            "id",
            "occurred_at",
            "numeric_value",
            "quality_status",
            "expires_at",
            "source_table",
            "source_batch",
            "calculation_task",
        )[: MAX_AGGREGATION_POINTS + 1]
    )
    if len(point_rows) > MAX_AGGREGATION_POINTS:
        raise ValidationError(
            f"Aggregation source exceeds the {MAX_AGGREGATION_POINTS} point safety limit."
        )

    source_watermark_id = point_rows[-1]["id"] if point_rows else None
    fresh_points = [
        point
        for point in point_rows
        if point["expires_at"] is None or point["expires_at"] > refreshed_at
    ]
    valid_points = [
        point
        for point in fresh_points
        if point["quality_status"] == MetricDataPoint.QualityStatus.PASSED
        and point["numeric_value"] is not None
    ]
    missing_points = [
        point
        for point in fresh_points
        if point["quality_status"] == MetricDataPoint.QualityStatus.MISSING
    ]
    valid_count = len(valid_points)
    missing_count = len(missing_points)
    total_count = len(point_rows)
    fresh_count = len(fresh_points)
    expired_count = total_count - fresh_count
    failed_count = fresh_count - valid_count - missing_count
    zero_fill = metric_definition.missing_data_policy == MetricDefinition.MissingDataPolicy.ZERO_FILL
    accepted_points = valid_points
    zero_filled_count = 0
    if zero_fill:
        accepted_points = valid_points + missing_points
        zero_filled_count = missing_count
    accepted_count = valid_count + zero_filled_count
    excluded_count = total_count - accepted_count

    if metric_definition.aggregation_method == MetricDefinition.AggregationMethod.LATEST:
        latest_point = max(
            accepted_points,
            key=lambda point: (point["occurred_at"], point["id"]),
            default=None,
        )
        numeric_value = None
        if latest_point:
            numeric_value = (
                Decimal(0)
                if latest_point["quality_status"] == MetricDataPoint.QualityStatus.MISSING
                else latest_point["numeric_value"]
            )
    elif metric_definition.aggregation_method == MetricDefinition.AggregationMethod.COUNT:
        numeric_value = Decimal(valid_count)
    elif metric_definition.aggregation_method == MetricDefinition.AggregationMethod.AVERAGE:
        value_sum = sum((point["numeric_value"] for point in valid_points), Decimal(0))
        denominator = accepted_count if zero_fill else valid_count
        numeric_value = value_sum / denominator if denominator else None
    else:
        numeric_value = sum((point["numeric_value"] for point in valid_points), Decimal(0))
        if not accepted_count:
            numeric_value = None
    if numeric_value is not None and not isinstance(numeric_value, Decimal):
        numeric_value = Decimal(numeric_value)

    quality_rate = Decimal(accepted_count) / Decimal(total_count) if total_count else Decimal(0)
    rejected_by_policy = (
        metric_definition.missing_data_policy == MetricDefinition.MissingDataPolicy.REJECT
        and excluded_count > 0
    )
    if accepted_count == 0:
        quality_status = MetricAggregate.QualityStatus.NO_VALID_DATA
    elif quality_rate < metric_definition.minimum_quality_rate or rejected_by_policy:
        quality_status = MetricAggregate.QualityStatus.DEGRADED
    else:
        quality_status = MetricAggregate.QualityStatus.PASSED
    is_formal = quality_status == MetricAggregate.QualityStatus.PASSED
    quality_detail = {
        "total_count": total_count,
        "passed_value_count": valid_count,
        "missing_count": missing_count,
        "failed_count": failed_count,
        "expired_count": expired_count,
        "zero_filled_count": zero_filled_count,
        "excluded_count": excluded_count,
        "quality_rate": str(quality_rate.quantize(Decimal("0.0001"))),
        "minimum_quality_rate": str(metric_definition.minimum_quality_rate),
        "missing_data_policy": metric_definition.missing_data_policy,
        "source_watermark_id": source_watermark_id,
    }

    source_table_values = sorted({point["source_table"] for point in accepted_points})
    source_batch_values = sorted({point["source_batch"] for point in accepted_points})
    calculation_task_values = sorted(
        {point["calculation_task"] for point in accepted_points if point["calculation_task"]}
    )
    accepted_ids = [point["id"] for point in accepted_points]
    id_bounds = {
        "first_data_point_id": min(accepted_ids, default=None),
        "last_data_point_id": max(accepted_ids, default=None),
    }
    source_lineage = {
        "source_tables": source_table_values[:MAX_LINEAGE_VALUES],
        "source_table_count": len(source_table_values),
        "source_batches": source_batch_values[:MAX_LINEAGE_VALUES],
        "source_batch_count": len(source_batch_values),
        "calculation_tasks": calculation_task_values[:MAX_LINEAGE_VALUES],
        "calculation_task_count": len(calculation_task_values),
        "data_point_count": accepted_count,
        "source_watermark_id": source_watermark_id,
        **id_bounds,
    }

    lookup = {
        "tenant": tenant,
        "metric_definition": metric_definition,
        "definition_version": metric_definition.version,
        "granularity": granularity,
        "period_start": period_start,
        "period_end": period_end,
        "dimensions_hash": MetricAggregate.hash_dimensions(dimensions),
    }
    aggregate = MetricAggregate.objects.select_for_update().filter(**lookup).first()
    if aggregate is None:
        aggregate = MetricAggregate(**lookup)
    aggregate.dimensions = dimensions
    aggregate.numeric_value = numeric_value
    aggregate.valid_point_count = accepted_count
    aggregate.excluded_point_count = excluded_count
    aggregate.quality_status = quality_status
    aggregate.quality_detail = quality_detail
    aggregate.is_formal = is_formal
    aggregate.source_lineage = source_lineage
    aggregate.refreshed_at = refreshed_at
    aggregate._aggregation_service_write = True
    aggregate.save()
    aggregate.lineage_records.all().delete()
    lineage_buffer = []
    lineage_values = sorted(
        {
            (
                point["source_table"],
                point["source_batch"],
                point["calculation_task"],
            )
            for point in accepted_points
        }
    )
    for source_table, source_batch, calculation_task in lineage_values:
        lineage_buffer.append(
            MetricAggregateLineage(
                tenant=tenant,
                aggregate=aggregate,
                source_table=source_table,
                source_batch=source_batch,
                calculation_task=calculation_task,
            )
        )
        if len(lineage_buffer) == LINEAGE_BATCH_SIZE:
            MetricAggregateLineage.objects.bulk_create(lineage_buffer, batch_size=LINEAGE_BATCH_SIZE)
            lineage_buffer = []
    if lineage_buffer:
        MetricAggregateLineage.objects.bulk_create(lineage_buffer, batch_size=LINEAGE_BATCH_SIZE)
    return aggregate
