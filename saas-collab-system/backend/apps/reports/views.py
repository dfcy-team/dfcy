from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.common.error_codes import ErrorCode
from apps.common.exceptions import DataScopeDenied, get_scoped_object_or_404
from apps.common.responses import paginated_data, success_response
from apps.permissions.api_permissions import IsInternalUser

from .models import MetricAggregate, MetricDefinition, ReportExportRequest
from .permissions import (
    IsAnalyticsCalculator,
    IsAnalyticsViewer,
    IsReportExporter,
    IsReportViewer,
    can_access_analytics_dimensions,
    filter_analytics_aggregates,
    filter_authorized_metric_definitions,
)
from .serializers import (
    MetricAggregateSerializer,
    MetricAggregateQuerySerializer,
    MetricAggregationRequestSerializer,
    MetricDefinitionSerializer,
    MetricDefinitionQuerySerializer,
    ReportExportCreateSerializer,
    ReportExportQuerySerializer,
    ReportExportRequestSerializer,
)
from .services import aggregate_metric
from .export_services import (
    create_download_grant,
    create_export_request,
    log_export_view,
    report_catalog_for_user,
    visible_export_requests,
)


@api_view(["GET"])
def health(request):
    return success_response({"status": "ok", "service": "report"})


def _paginated_data(request, queryset, serializer_class, query):
    return paginated_data(
        request,
        queryset,
        serializer_class,
        page=query["page"],
        page_size=query["page_size"],
    )


def _authorized_aggregate_queryset(request, query):
    queryset = MetricAggregate.objects.filter(tenant=request.user.tenant).select_related("metric_definition")
    authorized_definitions = filter_authorized_metric_definitions(
        request.user,
        MetricDefinition.objects.filter(tenant=request.user.tenant),
    )
    queryset = queryset.filter(metric_definition__in=authorized_definitions)
    if query.get("metric_code"):
        queryset = queryset.filter(metric_definition__metric_code=query["metric_code"])
    if query.get("granularity"):
        queryset = queryset.filter(granularity=query["granularity"])
    if query.get("period_start"):
        queryset = queryset.filter(period_end__gt=query["period_start"])
    if query.get("period_end"):
        queryset = queryset.filter(period_start__lt=query["period_end"])
    if not query["include_non_formal"]:
        queryset = queryset.filter(is_formal=True)
    for dimension in ("platform", "store_id", "country", "product_id", "sku_id", "warehouse_id"):
        if query.get(dimension) is not None:
            queryset = queryset.filter(**{f"dimensions__{dimension}": query[dimension]})
    return filter_analytics_aggregates(request.user, queryset).order_by("-refreshed_at", "-id")


def _dashboard_payload(request, dashboard_type):
    common_parameters = {"page", "page_size", "period_start", "period_end", "granularity", "metric_code"}
    dimension_parameters = {
        "overview": {"platform", "store_id", "country"},
        "sales": {"platform", "store_id", "country", "product_id", "sku_id"},
        "inventory": {"platform", "store_id", "country", "product_id", "sku_id", "warehouse_id"},
    }[dashboard_type]
    unknown = set(request.query_params) - common_parameters - dimension_parameters
    if unknown:
        raise ValidationError({key: "Unknown query parameter." for key in sorted(unknown)})
    query_serializer = MetricAggregateQuerySerializer(data=request.query_params)
    query_serializer.is_valid(raise_exception=True)
    query = query_serializer.validated_data
    collection = _paginated_data(
        request,
        _authorized_aggregate_queryset(request, query),
        MetricAggregateSerializer,
        query,
    )
    metric_rows = collection["results"]
    passed_count = sum(row["quality_status"] == MetricAggregate.QualityStatus.PASSED for row in metric_rows)
    quality_score = round((passed_count / len(metric_rows)) * 100) if metric_rows else 0
    metric_version = max((row["metric_version"] for row in metric_rows), default=None)
    refreshed_at = max((row["updated_at"] for row in metric_rows), default=None)
    missing_fields = sorted({row["metric_code"] for row in metric_rows if row["is_missing"]})
    source_summary = []
    for row in metric_rows:
        for source in row["source_summary"]:
            if source not in source_summary:
                source_summary.append(source)
    payload = {
        **collection,
        "api_status": "connected",
        "dashboard_type": dashboard_type,
        "quality": {
            "status": "good" if quality_score >= 95 else "warning",
            "score": quality_score,
            "metric_version": metric_version,
            "refreshed_at": refreshed_at,
            "missing_fields": missing_fields,
            "source_summary": source_summary,
        },
        "metrics": [
            {
                "code": row["metric_code"],
                "metric_code": row["metric_code"],
                "label": row["metric_name"],
                "metric_name": row["metric_name"],
                "value": row["value"],
                "unit": row["unit"],
                "change": None,
                "change_direction": "unknown",
            }
            for row in metric_rows
        ],
        "trend": [],
    }
    if dashboard_type == "sales":
        payload["attribution_scope"] = sorted(dimension_parameters)
    if dashboard_type == "inventory":
        payload["inventory_scope"] = sorted(dimension_parameters)
    return payload


@api_view(["GET"])
@permission_classes([IsAnalyticsViewer])
def metric_definition_collection(request):
    query_serializer = MetricDefinitionQuerySerializer(data=request.query_params)
    query_serializer.is_valid(raise_exception=True)
    query = query_serializer.validated_data
    queryset = MetricDefinition.objects.filter(tenant=request.user.tenant)
    metric_code = query.get("metric_code")
    if metric_code:
        queryset = queryset.filter(metric_code=metric_code)
    if "is_active" in request.query_params:
        queryset = queryset.filter(status="active" if query["is_active"] else "inactive")
    queryset = filter_authorized_metric_definitions(request.user, queryset)
    return success_response(_paginated_data(request, queryset, MetricDefinitionSerializer, query))


@api_view(["GET"])
@permission_classes([IsAnalyticsViewer])
def metric_definition_detail(request, pk):
    queryset = filter_authorized_metric_definitions(
        request.user,
        MetricDefinition.objects.filter(tenant=request.user.tenant),
    )
    definition = get_scoped_object_or_404(queryset, pk=pk)
    return success_response(MetricDefinitionSerializer(definition).data)


@api_view(["GET"])
@permission_classes([IsAnalyticsViewer])
def metric_aggregate_collection(request):
    query_serializer = MetricAggregateQuerySerializer(data=request.query_params)
    query_serializer.is_valid(raise_exception=True)
    query = query_serializer.validated_data
    return success_response(
        _paginated_data(request, _authorized_aggregate_queryset(request, query), MetricAggregateSerializer, query)
    )


@api_view(["GET"])
@permission_classes([IsAnalyticsViewer])
def metric_aggregate_detail(request, pk):
    queryset = MetricAggregate.objects.filter(tenant=request.user.tenant).select_related("metric_definition")
    authorized_definitions = filter_authorized_metric_definitions(
        request.user,
        MetricDefinition.objects.filter(tenant=request.user.tenant),
    )
    queryset = queryset.filter(metric_definition__in=authorized_definitions)
    if request.query_params.get("include_non_formal", "").lower() not in {"1", "true", "yes"}:
        queryset = queryset.filter(is_formal=True)
    aggregate = get_scoped_object_or_404(filter_analytics_aggregates(request.user, queryset), pk=pk)
    return success_response(MetricAggregateSerializer(aggregate).data)


@api_view(["POST"])
@permission_classes([IsAnalyticsCalculator])
def aggregate_mock(request):
    serializer = MetricAggregationRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    dimensions = serializer.validated_data["dimensions"]
    if not can_access_analytics_dimensions(request.user, dimensions):
        raise DataScopeDenied(
            "Analytics dimensions are outside the authorized data scope.",
            error_code=ErrorCode.DATA_SCOPE_FORBIDDEN,
        )

    definition = get_object_or_404(
        filter_authorized_metric_definitions(
            request.user,
            MetricDefinition.objects.filter(
                tenant=request.user.tenant,
                metric_code=serializer.validated_data["metric_code"],
                status=MetricDefinition.Status.ACTIVE,
            ),
        ).order_by("-version")
    )
    aggregate = aggregate_metric(
        tenant=request.user.tenant,
        metric_definition=definition,
        period_start=serializer.validated_data["period_start"],
        period_end=serializer.validated_data["period_end"],
        granularity=serializer.validated_data["granularity"],
        dimensions=dimensions,
    )
    return success_response(MetricAggregateSerializer(aggregate).data)


@api_view(["GET"])
@permission_classes([IsAnalyticsViewer])
def analytics_overview(request):
    return success_response(_dashboard_payload(request, "overview"))


@api_view(["GET"])
@permission_classes([IsAnalyticsViewer])
def analytics_sales(request):
    return success_response(_dashboard_payload(request, "sales"))


@api_view(["GET"])
@permission_classes([IsAnalyticsViewer])
def analytics_inventory(request):
    return success_response(_dashboard_payload(request, "inventory"))


@api_view(["GET"])
@permission_classes([IsReportViewer])
def report_catalog(request):
    return success_response(report_catalog_for_user(request.user))


@api_view(["GET", "POST"])
def report_export_collection(request):
    permission = IsReportViewer() if request.method == "GET" else IsReportExporter()
    if not permission.has_permission(request, report_export_collection):
        raise PermissionDenied("Report permission is required.")
    if request.method == "POST":
        serializer = ReportExportCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        export_request = create_export_request(user=request.user, **serializer.validated_data)
        return success_response(ReportExportRequestSerializer(export_request).data, status=201)
    serializer = ReportExportQuerySerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    query = serializer.validated_data
    queryset = visible_export_requests(request.user).select_related("requested_by").prefetch_related("audit_logs")
    for field in ("report_type", "status"):
        if query.get(field):
            queryset = queryset.filter(**{field: query[field]})
    return success_response(_paginated_data(request, queryset, ReportExportRequestSerializer, query))


@api_view(["GET"])
@permission_classes([IsReportViewer])
def report_export_detail(request, pk):
    export_request = get_scoped_object_or_404(
        visible_export_requests(request.user).select_related("requested_by").prefetch_related("audit_logs"),
        pk=pk,
    )
    log_export_view(export_request=export_request, actor=request.user)
    export_request.refresh_from_db()
    return success_response(ReportExportRequestSerializer(export_request).data)


@api_view(["POST"])
@permission_classes([IsInternalUser])
def report_export_download(request, pk):
    queryset = ReportExportRequest.objects.filter(tenant=request.user.tenant)
    if not request.user.is_superuser:
        queryset = queryset.filter(requested_by=request.user)
    export_request = get_scoped_object_or_404(
        queryset.select_related("requested_by"),
        pk=pk,
    )
    return success_response(create_download_grant(export_request=export_request, actor=request.user))
