from dataclasses import dataclass

from django.db.models import Count, F, Q
from django.utils import timezone

from apps.alerts.models import (
    BusinessAlert,
    BusinessAlertActionLog,
    BusinessAlertRule,
    InventoryAlert,
    InventoryAlertEvent,
    InventoryAlertRule,
)
from apps.configcenter.models import ConfigChangeLog, SystemConfigDefinition, TenantConfigVersion
from apps.products.lifecycle_services import ALLOWED_LIFECYCLE_TRANSITIONS
from apps.products.models import ProductLifecycleDecision, ProductLifecycleReview
from apps.replenishment.models import ReplenishmentRecommendation
from apps.reports.models import (
    MetricAggregate,
    MetricAggregateLineage,
    MetricDataPoint,
    MetricDefinition,
    ReportExportAuditLog,
    ReportExportRequest,
)

from .security import sanitize_sensitive_data


@dataclass(frozen=True)
class DataQualityFinding:
    check: str
    count: int
    detail: str


TENANT_MODELS = (
    MetricDefinition,
    MetricDataPoint,
    MetricAggregate,
    MetricAggregateLineage,
    InventoryAlertRule,
    InventoryAlert,
    InventoryAlertEvent,
    BusinessAlertRule,
    BusinessAlert,
    BusinessAlertActionLog,
    ReplenishmentRecommendation,
    ProductLifecycleReview,
    ProductLifecycleDecision,
    ReportExportRequest,
    ReportExportAuditLog,
)


def _finding(check, count, detail):
    return DataQualityFinding(check=check, count=count, detail=detail) if count else None


def _tenant_findings():
    findings = []
    for model in TENANT_MODELS:
        finding = _finding(
            "tenant_missing",
            model.objects.filter(tenant_id__isnull=True).count(),
            f"{model._meta.label} contains records without a tenant.",
        )
        if finding:
            findings.append(finding)

    tenant_config_count = TenantConfigVersion.objects.filter(
        definition__scope_type=SystemConfigDefinition.ScopeType.TENANT,
        tenant_id__isnull=True,
    ).count()
    tenant_log_count = ConfigChangeLog.objects.filter(scope_key__startswith="tenant:", tenant_id__isnull=True).count()
    for count, detail in (
        (tenant_config_count, "Tenant-scoped configuration versions are missing a tenant."),
        (tenant_log_count, "Tenant-scoped configuration logs are missing a tenant."),
    ):
        finding = _finding("tenant_missing", count, detail)
        if finding:
            findings.append(finding)
    return findings


def _invalid_dimension_findings():
    invalid_points = 0
    invalid_aggregates = 0
    for point in MetricDataPoint.objects.select_related("metric_definition").iterator():
        if not isinstance(point.dimensions, dict) or not set(point.dimensions).issubset(
            set(point.metric_definition.allowed_dimensions)
        ):
            invalid_points += 1
    for aggregate in MetricAggregate.objects.select_related("metric_definition").iterator():
        if not isinstance(aggregate.dimensions, dict) or not set(aggregate.dimensions).issubset(
            set(aggregate.metric_definition.allowed_dimensions)
        ):
            invalid_aggregates += 1
    count = invalid_points + invalid_aggregates
    finding = _finding("invalid_dimension", count, "Metric records contain dimensions outside their definition.")
    return [finding] if finding else []


def _metric_version_findings():
    count = MetricAggregate.objects.exclude(definition_version=F("metric_definition__version")).count()
    count += (
        MetricDefinition.objects.filter(status=MetricDefinition.Status.ACTIVE)
        .values("tenant_id", "metric_code")
        .annotate(active_count=Count("id"))
        .filter(active_count__gt=1)
        .count()
    )
    finding = _finding("metric_version_conflict", count, "Metric aggregate definition versions are inconsistent.")
    return [finding] if finding else []


def _duplicate_alert_findings():
    count = 0
    for model in (InventoryAlert, BusinessAlert):
        count += (
            model.objects.values("tenant_id", "dedup_key")
            .annotate(record_count=Count("id"))
            .filter(record_count__gt=1)
            .count()
        )
    finding = _finding("duplicate_alert", count, "Alert deduplication keys are duplicated within a tenant.")
    return [finding] if finding else []


def _expired_recommendation_findings():
    count = ReplenishmentRecommendation.objects.filter(
        status=ReplenishmentRecommendation.Status.SUGGESTED,
        suggested_date__lt=timezone.localdate(),
    ).count()
    finding = _finding("expired_recommendation", count, "Past-due replenishment suggestions remain active.")
    return [finding] if finding else []


def _illegal_lifecycle_findings():
    count = 0
    for review in ProductLifecycleReview.objects.only("current_stage", "recommended_stage").iterator():
        if review.recommended_stage not in ALLOWED_LIFECYCLE_TRANSITIONS.get(review.current_stage, set()):
            count += 1
    for decision in ProductLifecycleDecision.objects.only("decision", "from_stage", "to_stage").iterator():
        if decision.decision == ProductLifecycleDecision.Decision.CONFIRM:
            if decision.to_stage not in ALLOWED_LIFECYCLE_TRANSITIONS.get(decision.from_stage, set()):
                count += 1
        elif decision.to_stage != decision.from_stage:
            count += 1
    finding = _finding("illegal_lifecycle_transition", count, "Lifecycle records contain an illegal transition.")
    return [finding] if finding else []


def _contains_sensitive_value(value):
    return sanitize_sensitive_data(value) != value


def _sensitive_leakage_findings():
    count = 0
    for export in ReportExportRequest.objects.only("filters", "data_scope", "masked_file_reference").iterator():
        if _contains_sensitive_value(export.filters) or _contains_sensitive_value(export.data_scope):
            count += 1
        if export.masked_file_reference and not export.masked_file_reference.startswith("placeholder://"):
            count += 1
    for alert in BusinessAlert.objects.only("detail").iterator():
        if _contains_sensitive_value(alert.detail):
            count += 1
    for log in ConfigChangeLog.objects.only("masked_detail").iterator():
        if _contains_sensitive_value(log.masked_detail):
            count += 1
    allowed_reference_prefixes = ("placeholder://", "demo://", "not-configured")
    for version in TenantConfigVersion.objects.filter(definition__is_sensitive=True).only("value").iterator():
        value = version.value
        reference = str(value.get("reference") or "") if isinstance(value, dict) else ""
        if (
            not isinstance(value, dict)
            or set(value) - {"reference", "masked_metadata"}
            or not reference.startswith(allowed_reference_prefixes)
            or _contains_sensitive_value(value)
        ):
            count += 1
    finding = _finding("sensitive_field_leakage", count, "Persisted Phase 3 output contains unmasked sensitive data.")
    return [finding] if finding else []


def _export_audit_findings():
    count = ReportExportRequest.objects.annotate(
        request_audit_count=Count(
            "audit_logs",
            filter=Q(audit_logs__action=ReportExportAuditLog.Action.REQUEST),
        )
    ).filter(request_audit_count=0).count()
    finding = _finding("export_without_audit", count, "Report export requests are missing request audit records.")
    return [finding] if finding else []


def run_phase3_data_quality_checks():
    findings = []
    for check in (
        _tenant_findings,
        _invalid_dimension_findings,
        _metric_version_findings,
        _duplicate_alert_findings,
        _expired_recommendation_findings,
        _illegal_lifecycle_findings,
        _sensitive_leakage_findings,
        _export_audit_findings,
    ):
        findings.extend(check())
    return findings
