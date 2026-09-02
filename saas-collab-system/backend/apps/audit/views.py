import csv
import io
from datetime import datetime, time

from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework.exceptions import ValidationError
from rest_framework.views import APIView

from apps.common.exceptions import get_scoped_object_or_404
from apps.common.query import positive_int
from apps.common.responses import paginated_data, success_response
from apps.permissions.api_permissions import DeclaredApplicationPermission

from .models import OperationLog
from .serializers import OperationLogDetailSerializer, OperationLogSummarySerializer
from .services import operation_log_queryset


LIST_QUERY_FIELDS = {
    "page",
    "page_size",
    "operator",
    "operator_id",
    "module",
    "action",
    "object_type",
    "object_id",
    "search",
    "created_from",
    "created_to",
    "date_from",
    "date_to",
    "ordering",
}
EXPORT_QUERY_FIELDS = LIST_QUERY_FIELDS | {"limit"}
ALLOWED_ORDERINGS = {"-created_at", "created_at", "-id", "id"}
EXPORT_MAX_ROWS = 5000
MAX_PAGE = 100_000
MAX_QUERY_TEXT_LENGTH = 200
MAX_DATETIME_TEXT_LENGTH = 64


def _validate_query(request, allowed):
    unknown = set(request.query_params) - allowed
    if unknown:
        raise ValidationError(f"Unknown audit query parameter(s): {', '.join(sorted(unknown))}.")


def _parse_datetime(value, field, *, end_of_day=False):
    if value in (None, ""):
        return None
    value = str(value)
    if len(value) > MAX_DATETIME_TEXT_LENGTH:
        raise ValidationError({field: "Date or datetime value is too long."})
    parsed = parse_datetime(value)
    if parsed is None:
        parsed_date = parse_date(value)
        if parsed_date is None:
            raise ValidationError({field: "Use an ISO-8601 date or datetime."})
        parsed = datetime.combine(parsed_date, time.max if end_of_day else time.min)
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _query_datetime(request, primary, alias, *, end_of_day=False):
    primary_value = request.query_params.get(primary)
    alias_value = request.query_params.get(alias)
    if primary_value not in (None, "") and alias_value not in (None, ""):
        raise ValidationError(f"Use only one of {primary} and {alias}.")
    return _parse_datetime(primary_value or alias_value, primary, end_of_day=end_of_day)


def _apply_filters(queryset, request):
    def query_text(name):
        value = request.query_params.get(name, "").strip()
        if len(value) > MAX_QUERY_TEXT_LENGTH:
            raise ValidationError({name: f"查询条件不能超过 {MAX_QUERY_TEXT_LENGTH} 个字符。"})
        return value

    operator = query_text("operator")
    operator_id = request.query_params.get("operator_id", "").strip()
    if operator_id:
        operator_id = positive_int(operator_id, default=None, maximum=2_147_483_647)
        queryset = queryset.filter(user_id=operator_id)
    if operator:
        if operator.isdigit():
            queryset = queryset.filter(user_id=int(operator))
        else:
            queryset = queryset.filter(
                Q(user__username__icontains=operator) | Q(user__full_name__icontains=operator)
            )
    for field in ("module", "action", "object_type", "object_id"):
        value = query_text(field)
        if value:
            queryset = queryset.filter(**{f"{field}__icontains": value})
    search = query_text("search")
    if search:
        queryset = queryset.filter(
            Q(module__icontains=search)
            | Q(action__icontains=search)
            | Q(object_type__icontains=search)
            | Q(object_id__icontains=search)
            | Q(user__username__icontains=search)
            | Q(user__full_name__icontains=search)
        )
    created_from = _query_datetime(request, "created_from", "date_from")
    created_to = _query_datetime(request, "created_to", "date_to", end_of_day=True)
    if created_from and created_to and created_from > created_to:
        raise ValidationError("created_from must be earlier than or equal to created_to.")
    if created_from:
        queryset = queryset.filter(created_at__gte=created_from)
    if created_to:
        queryset = queryset.filter(created_at__lte=created_to)
    ordering = request.query_params.get("ordering", "-created_at")
    if ordering not in ALLOWED_ORDERINGS:
        raise ValidationError({"ordering": "Unsupported audit log ordering."})
    # A stable secondary key prevents records with equal timestamps moving
    # between pages while the table is being browsed.
    secondary = "-id" if ordering.startswith("-") else "id"
    return queryset.order_by(ordering, secondary)


def _csv_cell(value):
    text = "" if value is None else str(value)
    # Avoid spreadsheet formula injection when an audited free-text field is
    # opened in Excel/LibreOffice.
    return f"'{text}" if text.startswith(("=", "+", "-", "@")) else text


def _export_response(queryset, request):
    limit = positive_int(request.query_params.get("limit"), default=EXPORT_MAX_ROWS, maximum=EXPORT_MAX_ROWS)
    total_count = queryset.count()
    rows = queryset[:limit]
    output = io.StringIO(newline="")
    # UTF-8 BOM keeps Chinese headers readable in common spreadsheet clients.
    output.write("\ufeff")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        ["ID", "操作人", "操作人ID", "模块", "动作", "对象类型", "对象ID", "IP", "时间"]
    )
    for log in rows:
        operator = log.user
        writer.writerow(
            [
                _csv_cell(log.pk),
                _csv_cell(operator.username if operator else "system"),
                _csv_cell(operator.pk if operator else ""),
                _csv_cell(log.module),
                _csv_cell(log.action),
                _csv_cell(log.object_type),
                _csv_cell(log.object_id),
                _csv_cell(log.ip_address),
                _csv_cell(log.created_at.isoformat() if log.created_at else ""),
            ]
        )
    response = HttpResponse(output.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="operation-logs.csv"'
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["X-Audit-Export-Count"] = str(total_count)
    response["X-Audit-Export-Limit"] = str(limit)
    response["X-Audit-Export-Truncated"] = "true" if total_count > limit else "false"
    return response


class OperationLogCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "audit.operation_logs.view"

    def get(self, request):
        _validate_query(request, LIST_QUERY_FIELDS)
        queryset = operation_log_queryset(request.user, self.read_permission_code)
        queryset = _apply_filters(queryset, request)
        page = positive_int(request.query_params.get("page"), default=1, maximum=MAX_PAGE)
        page_size = positive_int(request.query_params.get("page_size"), default=20, maximum=100)
        return success_response(
            paginated_data(
                request,
                queryset,
                OperationLogSummarySerializer,
                page=page,
                page_size=page_size,
            )
        )


class OperationLogDetailView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "audit.operation_logs.view"

    def get(self, request, pk):
        _validate_query(request, set())
        queryset = operation_log_queryset(request.user, self.read_permission_code)
        log = get_scoped_object_or_404(queryset, pk=pk)
        return success_response(OperationLogDetailSerializer(log).data)


class OperationLogExportView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "audit.operation_logs.export"

    def get(self, request):
        _validate_query(request, EXPORT_QUERY_FIELDS)
        queryset = operation_log_queryset(request.user, self.read_permission_code)
        queryset = _apply_filters(queryset, request)
        return _export_response(queryset, request)
