import csv
import hashlib
import io
import json
import os
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.conf import settings
from django.core import signing
from django.db import transaction
from django.db.models import Q
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
    ReportExportRequest.ReportType.SALES_DETAILS: {
        "name": "Sales details",
        "required_permission": "sales_management.export",
        "contains_sensitive_data": False,
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
    ReportExportRequest.ReportType.SALES_DETAILS: {
        "store_id": "store_id",
        "store_ids": "store_id__in",
        "platform": "platform__platform_type",
        "platforms": "platform__platform_type__in",
        "region": "region",
        "regions": "region__in",
        "currency": "currency",
        "date_from": "created_at_utc__gte",
        "date_to": "created_at_utc__lt",
        "order_status": "normalized_status",
        "sku": "items__seller_sku",
    },
}


def _scope_snapshot(user, permission_code):
    snapshot = [
        {"scope_type": item["scope_type"], "config": sanitize_sensitive_data(item.get("config") or {})}
        for item in get_permission_data_scopes(user, permission_code)
    ]
    return sorted(snapshot, key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))


def report_catalog_for_user(user):
    return [
        {
            "report_type": report_type,
            **metadata,
            "mode": "file_export" if report_type == ReportExportRequest.ReportType.SALES_DETAILS else "placeholder_export",
        }
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
    if report_type == ReportExportRequest.ReportType.SALES_DETAILS:
        from apps.commerce.models import SalesOrder
        from apps.sales_management.scopes import filter_sales_queryset

        return filter_sales_queryset(
            user,
            "sales_management.export",
            SalesOrder.objects.filter(tenant=user.tenant),
        )
    raise ValidationError("Unsupported report type.")


def _apply_filters(queryset, report_type, filters):
    allowed = REPORT_FILTERS[report_type]
    unsupported = set(filters) - set(allowed)
    if unsupported:
        raise ValidationError(f"Unsupported report filters: {', '.join(sorted(unsupported))}.")
    if report_type == ReportExportRequest.ReportType.SALES_DETAILS:
        return _apply_sales_detail_filters(queryset, filters)
    for key, value in filters.items():
        queryset = queryset.filter(**{allowed[key]: value})
    return queryset


def _apply_sales_detail_filters(queryset, filters):
    for key, value in filters.items():
        if key in {"date_from", "date_to"}:
            continue
        if key == "sku":
            queryset = queryset.filter(
                Q(items__seller_sku__icontains=value)
                | Q(items__internal_sku__sku_code__icontains=value)
            )
            continue
        queryset = queryset.filter(**{REPORT_FILTERS[ReportExportRequest.ReportType.SALES_DETAILS][key]: value})

    try:
        start_date = date.fromisoformat(filters["date_from"]) if filters.get("date_from") else None
        end_date = date.fromisoformat(filters["date_to"]) if filters.get("date_to") else None
    except (TypeError, ValueError) as exc:
        raise ValidationError("Sales export dates must use YYYY-MM-DD.") from exc
    if not start_date and not end_date:
        return queryset.distinct()

    from apps.masterdata.models import StoreMaster

    date_scope = Q(pk__in=[])
    stores = StoreMaster.objects.filter(pk__in=queryset.values_list("store_id", flat=True).distinct())
    for store in stores:
        try:
            store_timezone = ZoneInfo(store.timezone)
        except Exception as exc:
            raise ValidationError("A sales export store has an invalid timezone.") from exc
        branch = Q(store_id=store.id)
        if start_date:
            start = datetime.combine(start_date, time.min, tzinfo=store_timezone).astimezone(UTC)
            branch &= Q(created_at_utc__gte=start)
        if end_date:
            end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=store_timezone).astimezone(UTC)
            branch &= Q(created_at_utc__lt=end)
        date_scope |= branch
    return queryset.filter(date_scope).distinct()


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


SALES_EXPORT_COLUMNS = (
    "platform",
    "store_code",
    "external_order_id",
    "created_at_utc",
    "updated_at_utc",
    "normalized_status",
    "currency",
    "order_total_amount",
    "external_line_id",
    "seller_sku",
    "item_name",
    "quantity",
    "sale_unit_price",
    "line_total_amount",
)


def _safe_csv_value(value):
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(("=", "+", "-", "@")) else text


def _sales_export_rows(queryset):
    orders = queryset.select_related("platform", "store").prefetch_related("items").order_by("created_at_utc", "id")
    for order in orders:
        items = list(order.items.all()) or [None]
        for item in items:
            yield {
                "platform": order.platform.platform_type,
                "store_code": order.store.code,
                "external_order_id": order.external_order_id,
                "created_at_utc": order.created_at_utc.isoformat(),
                "updated_at_utc": order.updated_at_utc.isoformat(),
                "normalized_status": order.normalized_status,
                "currency": order.currency,
                "order_total_amount": str(order.order_total_amount),
                "external_line_id": item.external_line_id if item else "",
                "seller_sku": item.seller_sku if item else "",
                "item_name": item.item_name_snapshot if item else "",
                "quantity": item.quantity if item else "",
                "sale_unit_price": str(item.sale_unit_price) if item else "",
                "line_total_amount": str(item.line_total_amount) if item else "",
            }


def _render_sales_export(queryset, file_format):
    rows = list(_sales_export_rows(queryset))
    if file_format == "txt":
        content = json.dumps(rows, ensure_ascii=False, indent=2, separators=(",", ": "))
        return f"\ufeff{content}\r\n".encode("utf-8")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=SALES_EXPORT_COLUMNS, lineterminator="\r\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _safe_csv_value(value) for key, value in row.items()})
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def _write_sales_export(export_request, queryset):
    root = settings.REPORT_EXPORT_ROOT.resolve()
    tenant_directory = (root / str(export_request.tenant_id)).resolve()
    if root not in tenant_directory.parents:
        raise ValidationError("Export storage path is invalid.")
    tenant_directory.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.{export_request.file_format}"
    target = tenant_directory / filename
    temporary = tenant_directory / f".{filename}.tmp"
    content = _render_sales_export(queryset, export_request.file_format)
    try:
        temporary.write_bytes(content)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    export_request.storage_key = f"{export_request.tenant_id}/{filename}"
    export_request.file_sha256 = hashlib.sha256(content).hexdigest()
    export_request.masked_file_reference = f"export://{export_request.id}"
    export_request.expires_at = timezone.now() + timedelta(seconds=settings.REPORT_EXPORT_TTL_SECONDS)
    export_request._export_service_write = True
    export_request.save(update_fields=["storage_key", "file_sha256", "masked_file_reference", "expires_at"])


@transaction.atomic
def create_export_request(*, user, report_type, filters, permission_code="reports.export", file_format="csv"):
    """Create a scoped audited export using the caller's export permission.

    Existing report callers keep the ``reports.export`` default.  Feature-owned
    exports may provide their own permission (for example
    ``sales_management.export``) so a role does not need an unrelated global
    report permission just to use that feature's export action.
    """
    if not user or not user.is_active or user.user_type != "internal" or not check_user_permission(user, permission_code):
        raise PermissionDenied("Report export permission is required.")
    metadata = REPORT_CATALOG.get(report_type)
    if metadata is None:
        raise ValidationError("Unsupported report type.")
    # The general report permission carries report-type scopes.  Feature-owned
    # permissions carry their own data scope (store/platform/etc.) and must not
    # be interpreted as a report-type scope.
    if permission_code == "reports.export" and not report_type_allowed(user, permission_code, report_type):
        raise DataScopeDenied(
            "The selected report type is outside the export data scope.",
            error_code=ErrorCode.DATA_SCOPE_FORBIDDEN,
        )
    if not check_user_permission(user, metadata["required_permission"]):
        raise PermissionDenied("The selected report type requires additional permission.")
    if file_format not in {"csv", "txt"}:
        raise ValidationError("Export format must be csv or txt.")
    sanitized_filters = sanitize_sensitive_data(filters or {})
    if sanitized_filters != (filters or {}):
        raise ValidationError("Sensitive credentials are not allowed in report filters.")
    scope_snapshot = _scope_snapshot(user, permission_code)
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
        file_format=file_format,
        rejection_reason="row_limit_exceeded" if rejected else "",
        finished_at=timezone.now(),
    )
    export_request._export_service_write = True
    export_request.save()
    if not rejected and report_type == ReportExportRequest.ReportType.SALES_DETAILS:
        _write_sales_export(export_request, queryset)
    elif not rejected:
        export_request.masked_file_reference = f"placeholder://report-export/{export_request.id}"
        export_request._export_service_write = True
        export_request.save(update_fields=["masked_file_reference"])
    _write_audit(
        export_request,
        user,
        ReportExportAuditLog.Action.REQUEST,
        "rejected_row_limit" if rejected else "file_completed" if export_request.storage_key else "placeholder_completed",
    )
    return export_request


def visible_export_requests(user, permission_code="reports.view"):
    queryset = ReportExportRequest.objects.filter(tenant=user.tenant)
    queryset = queryset if user.is_superuser else queryset.filter(requested_by=user)
    if permission_code == "sales_management.export":
        return queryset.filter(report_type=ReportExportRequest.ReportType.SALES_DETAILS)
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
            ValidationError("Only completed exports can be downloaded."),
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
    if not export_request.storage_key:
        audit = _write_audit(export_request, actor, ReportExportAuditLog.Action.DOWNLOAD, "placeholder_grant")
        return {
            "download_reference": export_request.masked_file_reference,
            "audit_id": audit.id,
            "expires_in_seconds": None,
            "placeholder_only": True,
        }
    if export_request.expires_at and export_request.expires_at <= timezone.now():
        _reject_download(export_request, actor, "expired", ValidationError("Export file has expired."))
    audit = _write_audit(export_request, actor, ReportExportAuditLog.Action.DOWNLOAD, "file_grant")
    token = signing.dumps(
        {"export_id": export_request.id, "tenant_id": actor.tenant_id, "user_id": actor.id, "audit_id": audit.id},
        salt="report-export-download",
        compress=True,
    )
    return {
        "download_reference": f"/api/report/exports/{export_request.id}/file/?token={token}",
        "audit_id": audit.id,
        "expires_in_seconds": 300,
        "placeholder_only": False,
    }


def resolve_export_file(*, export_request, actor, token):
    try:
        payload = signing.loads(token, salt="report-export-download", max_age=300)
    except signing.BadSignature as exc:
        raise PermissionDenied("Download grant is invalid or expired.") from exc
    expected = {
        "export_id": export_request.id,
        "tenant_id": actor.tenant_id,
        "user_id": actor.id,
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise PermissionDenied("Download grant does not match the current user and tenant.")
    if export_request.expires_at and export_request.expires_at <= timezone.now():
        raise ValidationError("Export file has expired.")
    root = settings.REPORT_EXPORT_ROOT.resolve()
    target = (root / export_request.storage_key).resolve()
    if root not in target.parents or not target.is_file():
        raise ValidationError("Export file is unavailable.")
    if hashlib.sha256(target.read_bytes()).hexdigest() != export_request.file_sha256:
        raise ValidationError("Export file integrity check failed.")
    return target
