from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied

from apps.common.responses import success_response

from .models import MetricAggregate, MetricDefinition
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
from .export_services import create_export_request, log_export_view, report_catalog_for_user, visible_export_requests


@api_view(["GET"])
def health(request):
    return success_response({"status": "ok", "service": "report"})


def _paginated_data(queryset, serializer_class, query):
    paginator = Paginator(queryset, query["page_size"])
    if query["page"] > paginator.num_pages:
        raise NotFound("Requested page does not exist.")
    page = paginator.page(query["page"])
    return {
        "items": serializer_class(page.object_list, many=True).data,
        "pagination": {
            "page": page.number,
            "page_size": query["page_size"],
            "total": paginator.count,
            "total_pages": paginator.num_pages,
        },
    }


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
    queryset = filter_authorized_metric_definitions(request.user, queryset)
    return success_response(_paginated_data(queryset, MetricDefinitionSerializer, query))


@api_view(["GET"])
@permission_classes([IsAnalyticsViewer])
def metric_definition_detail(request, pk):
    queryset = filter_authorized_metric_definitions(
        request.user,
        MetricDefinition.objects.filter(tenant=request.user.tenant),
    )
    definition = get_object_or_404(queryset, pk=pk)
    return success_response(MetricDefinitionSerializer(definition).data)


@api_view(["GET"])
@permission_classes([IsAnalyticsViewer])
def metric_aggregate_collection(request):
    query_serializer = MetricAggregateQuerySerializer(data=request.query_params)
    query_serializer.is_valid(raise_exception=True)
    query = query_serializer.validated_data
    queryset = MetricAggregate.objects.filter(tenant=request.user.tenant).select_related("metric_definition")
    authorized_definitions = filter_authorized_metric_definitions(
        request.user,
        MetricDefinition.objects.filter(tenant=request.user.tenant),
    )
    queryset = queryset.filter(metric_definition__in=authorized_definitions)
    metric_code = query.get("metric_code")
    granularity = query.get("granularity")
    if metric_code:
        queryset = queryset.filter(metric_definition__metric_code=metric_code)
    if granularity:
        queryset = queryset.filter(granularity=granularity)
    if query.get("period_start"):
        queryset = queryset.filter(period_end__gt=query["period_start"])
    if query.get("period_end"):
        queryset = queryset.filter(period_start__lt=query["period_end"])
    if not query["include_non_formal"]:
        queryset = queryset.filter(is_formal=True)
    queryset = filter_analytics_aggregates(request.user, queryset)
    return success_response(_paginated_data(queryset, MetricAggregateSerializer, query))


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
    aggregate = get_object_or_404(filter_analytics_aggregates(request.user, queryset), pk=pk)
    return success_response(MetricAggregateSerializer(aggregate).data)


@api_view(["POST"])
@permission_classes([IsAnalyticsCalculator])
def aggregate_mock(request):
    serializer = MetricAggregationRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    dimensions = serializer.validated_data["dimensions"]
    if not can_access_analytics_dimensions(request.user, dimensions):
        raise PermissionDenied("Analytics dimensions are outside the authorized data scope.")

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
    return success_response(_paginated_data(queryset, ReportExportRequestSerializer, query))


@api_view(["GET"])
@permission_classes([IsReportViewer])
def report_export_detail(request, pk):
    export_request = get_object_or_404(
        visible_export_requests(request.user).select_related("requested_by").prefetch_related("audit_logs"),
        pk=pk,
    )
    log_export_view(export_request=export_request, actor=request.user)
    export_request.refresh_from_db()
    return success_response(ReportExportRequestSerializer(export_request).data)
