import json

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.alerts.models import BusinessAlert, InventoryAlert
from apps.alerts.permissions import filter_business_alerts, filter_inventory_alerts
from apps.common.error_codes import ErrorCode
from apps.common.exceptions import DataScopeDenied
from apps.common.security import sanitize_sensitive_data
from apps.finance.models import PlatformStatement
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from apps.permissions.ui_p6_scopes import filter_report_exports, report_type_allowed
from apps.products.models import ProductLifecycleReview
from apps.products.permissions import filter_lifecycle_reviews
from apps.replenishment.models import ReplenishmentRecommendation
from apps.replenishment.permissions import filter_recommendations

from .models import MetricAggregate, MetricDefinition, ReportExportAuditLog, ReportExportRequest
from .permissions import filter_analytics_aggregates, filter_authorized_metric_definitions


MAX_EXPORT_ROWS = 10000

REPORT_CATALOG = {
    ReportExportRequest.ReportType.ANALYTICS_SUMMARY: {
        "name": "Analytics summary",
        "required_permission": "analytics.view",
        "contains_sensitive_data": False,
    },
    ReportExportRequest.ReportType.INVENTORY_ALERTS: {
        "name": "Inventory alerts",
        "required_permission": "alerts.inventory.view",
        "contains_sensitive_data": False,
    },
    ReportExportRequest.ReportType.REPLENISHMENT: {
        "name": "Replenishment recommendations",
        "required_permission": "replenishment.view",
        "contains_sensitive_data": False,
    },
    ReportExportRequest.ReportType.LIFECYCLE: {
        "name": "Lifecycle reviews",
        "required_permission": "products.lifecycle.view",
        "contains_sensitive_data": False,
    },
    ReportExportRequest.ReportType.BUSINESS_ALERTS: {
        "name": "Business alerts",
        "required_permission": "alerts.business.view",
        "contains_sensitive_data": False,
    },
    ReportExportRequest.ReportType.FINANCE_SUMMARY: {
        "name": "Masked finance summary",
        "required_permission": "finance.export",
        "contains_sensitive_data": True,
    },
}

REPORT_FILTERS = {
    ReportExportRequest.ReportType.ANALYTICS_SUMMARY: {
        "metric_code": "metric_definition__metric_code",
        "period_start": "period_end__gt",
        "period_end": "period_start__lt",
    },
    ReportExportRequest.ReportType.INVENTORY_ALERTS: {
        "sku_id": "sku_id",
        "status": "status",
        "severity": "severity",
    },
    ReportExportRequest.ReportType.REPLENISHMENT: {"sku_id": "sku_id", "status": "status"},
    ReportExportRequest.ReportType.LIFECYCLE: {
        "sku_id": "sku_id",
        "status": "status",
        "recommended_stage": "recommended_stage",
    },
    ReportExportRequest.ReportType.BUSINESS_ALERTS: {
        "business_type": "business_type",
        "status": "status",
        "severity": "severity",
    },
    ReportExportRequest.ReportType.FINANCE_SUMMARY: {"currency": "currency"},
}


def _scope_snapshot(user, permission_code):
    snapshot = [
        {"scope_type": item["scope_type"], "config": sanitize_sensitive_data(item.get("config") or {})}
        for item in get_permission_data_scopes(user, permission_code)
    ]
    return sorted(snapshot, key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))


def report_catalog_for_user(user):
    return [
        {"report_type": report_type, **metadata, "mode": "placeholder_export"}
        for report_type, metadata in REPORT_CATALOG.items()
        if report_type_allowed(user, "reports.view", report_type)
        and check_user_permission(user, metadata["required_permission"])
    ]


def _source_queryset(user, report_type):
    if report_type == ReportExportRequest.ReportType.ANALYTICS_SUMMARY:
        definitions = filter_authorized_metric_definitions(
            user,
            MetricDefinition.objects.filter(tenant=user.tenant),
        )
        return filter_analytics_aggregates(
            user,
            MetricAggregate.objects.filter(tenant=user.tenant, metric_definition__in=definitions, is_formal=True),
        )
    if report_type == ReportExportRequest.ReportType.INVENTORY_ALERTS:
        return filter_inventory_alerts(user, InventoryAlert.objects.filter(tenant=user.tenant))
    if report_type == ReportExportRequest.ReportType.REPLENISHMENT:
        return filter_recommendations(user, ReplenishmentRecommendation.objects.filter(tenant=user.tenant))
    if report_type == ReportExportRequest.ReportType.LIFECYCLE:
        return filter_lifecycle_reviews(user, ProductLifecycleReview.objects.filter(tenant=user.tenant))
    if report_type == ReportExportRequest.ReportType.BUSINESS_ALERTS:
        return filter_business_alerts(user, BusinessAlert.objects.filter(tenant=user.tenant))
    if report_type == ReportExportRequest.ReportType.FINANCE_SUMMARY:
        return PlatformStatement.objects.filter(tenant=user.tenant)
    raise ValidationError("Unsupported report type.")


def _apply_filters(queryset, report_type, filters):
    allowed = REPORT_FILTERS[report_type]
    unsupported = set(filters) - set(allowed)
    if unsupported:
        raise ValidationError(f"Unsupported report filters: {', '.join(sorted(unsupported))}.")
    for key, value in filters.items():
        queryset = queryset.filter(**{allowed[key]: value})
    return queryset


def _write_audit(export_request, actor, action, result):
    log = ReportExportAuditLog(
        tenant=export_request.tenant,
        export_request=export_request,
        actor=actor,
        action=action,
        result=result,
    )
    log._export_service_write = True
    log.save()
    return log


def _reject_download(export_request, actor, result, exception):
    _write_audit(export_request, actor, ReportExportAuditLog.Action.DOWNLOAD, result)
    raise exception


@transaction.atomic
def create_export_request(*, user, report_type, filters):
    if not user or not user.is_active or user.user_type != "internal" or not check_user_permission(user, "reports.export"):
        raise PermissionDenied("Report export permission is required.")
    metadata = REPORT_CATALOG.get(report_type)
    if metadata is None:
        raise ValidationError("Unsupported report type.")
    if not report_type_allowed(user, "reports.export", report_type):
        raise DataScopeDenied(
            "The selected report type is outside the export data scope.",
            error_code=ErrorCode.DATA_SCOPE_FORBIDDEN,
        )
    if not check_user_permission(user, metadata["required_permission"]):
        raise PermissionDenied("The selected report type requires additional permission.")
    sanitized_filters = sanitize_sensitive_data(filters or {})
    if sanitized_filters != (filters or {}):
        raise ValidationError("Sensitive credentials are not allowed in report filters.")
    scope_snapshot = _scope_snapshot(user, "reports.export")
    queryset = _apply_filters(_source_queryset(user, report_type), report_type, sanitized_filters)
    limited_count = queryset.values_list("pk", flat=True)[: MAX_EXPORT_ROWS + 1].count()
    rejected = limited_count > MAX_EXPORT_ROWS
    export_request = ReportExportRequest(
        tenant=user.tenant,
        report_type=report_type,
        requested_by=user,
        data_scope=scope_snapshot,
        filters=sanitized_filters,
        status=ReportExportRequest.Status.REJECTED if rejected else ReportExportRequest.Status.COMPLETED,
        row_count=MAX_EXPORT_ROWS if rejected else limited_count,
        rejection_reason="row_limit_exceeded" if rejected else "",
        finished_at=timezone.now(),
    )
    export_request._export_service_write = True
    export_request.save()
    if not rejected:
        export_request.masked_file_reference = f"placeholder://report-export/{export_request.id}"
        export_request._export_service_write = True
        export_request.save(update_fields=["masked_file_reference"])
    _write_audit(
        export_request,
        user,
        ReportExportAuditLog.Action.REQUEST,
        "rejected_row_limit" if rejected else "placeholder_completed",
    )
    return export_request


def visible_export_requests(user, permission_code="reports.view"):
    queryset = ReportExportRequest.objects.filter(tenant=user.tenant)
    queryset = queryset if user.is_superuser else queryset.filter(requested_by=user)
    return filter_report_exports(user, queryset, permission_code)


@transaction.atomic
def log_export_view(*, export_request, actor):
    if export_request.tenant_id != actor.tenant_id:
        raise PermissionDenied("Export request is outside the current tenant.")
    if not actor.is_superuser and export_request.requested_by_id != actor.id:
        raise PermissionDenied("Export request belongs to another data scope.")
    return _write_audit(export_request, actor, ReportExportAuditLog.Action.VIEW, "metadata_only")


def create_download_grant(*, export_request, actor):
    if export_request.tenant_id != actor.tenant_id:
        raise PermissionDenied("Export request is outside the current tenant.")
    if not actor.is_superuser and export_request.requested_by_id != actor.id:
        raise PermissionDenied("Export request belongs to another data scope.")
    if not check_user_permission(actor, "reports.download"):
        _reject_download(
            export_request,
            actor,
            "denied_permission",
            PermissionDenied("Report download permission is required."),
        )
    try:
        allowed_download_scope = report_type_allowed(actor, "reports.download", export_request.report_type)
    except DataScopeDenied as exc:
        _reject_download(export_request, actor, "denied_download_scope", exc)
    if not allowed_download_scope:
        _reject_download(
            export_request,
            actor,
            "denied_report_scope",
            PermissionDenied("The selected report type is outside the download data scope."),
        )
    if export_request.status != ReportExportRequest.Status.COMPLETED:
        _reject_download(
            export_request,
            actor,
            "rejected_status",
            ValidationError("Only completed placeholder exports can be downloaded."),
        )
    metadata = REPORT_CATALOG[export_request.report_type]
    if not check_user_permission(actor, metadata["required_permission"]):
        _reject_download(
            export_request,
            actor,
            "denied_report_permission",
            PermissionDenied("The selected report type requires additional permission."),
        )
    try:
        _apply_filters(_source_queryset(actor, export_request.report_type), export_request.report_type, export_request.filters)
    except (DataScopeDenied, PermissionDenied) as exc:
        _reject_download(export_request, actor, "denied_source_scope", exc)
    audit = _write_audit(export_request, actor, ReportExportAuditLog.Action.DOWNLOAD, "placeholder_grant")
    return {
        "download_reference": f"{export_request.masked_file_reference}?audit={audit.id}",
        "audit_id": audit.id,
        "expires_in_seconds": 300,
        "placeholder_only": True,
    }
