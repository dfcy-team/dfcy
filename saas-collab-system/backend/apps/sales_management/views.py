from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Max, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.views import APIView

from apps.common.responses import paginated_data, success_response
from apps.permissions.api_permissions import DeclaredApplicationPermission
from apps.permissions.services import check_user_permission

from .models import (
    DataQualityIssue,
    SalesExportRequest,
    SalesOrder,
    SalesReturn,
    SKUSalesFact,
    StoreSalesFact,
    SyncSource,
)
from .scopes import filter_sales_queryset, safe_scope_snapshot, scope_allows_filters, scope_snapshot_is_visible
from .serializers import (
    DataQualityIssueSerializer,
    SalesExportRequestSerializer,
    SalesOrderDetailSerializer,
    SalesOrderSerializer,
    SalesReturnSerializer,
    SKUSalesFactSerializer,
    StoreSalesFactSerializer,
    SyncRerunRequestSerializer,
    SyncSourceSerializer,
)
from .services import (
    create_export_request,
    create_sync_rerun_request,
    validate_export_request_key,
    validate_export_filters,
    validate_sync_rerun_request,
)


def _pagination(request):
    try:
        page = max(1, int(request.query_params.get("page", 1)))
        page_size = min(100, max(1, int(request.query_params.get("page_size", 20))))
    except (TypeError, ValueError) as exc:
        raise ValidationError("Invalid pagination values.") from exc
    return page, page_size


def _apply_dimensions(queryset, request, *, date_field=None):
    for parameter, field in (("platform", "platform"), ("region", "region"), ("store_id", "store_id")):
        if request.query_params.get(parameter):
            queryset = queryset.filter(**{field: request.query_params[parameter]})
    if date_field and request.query_params.get("date_from"):
        queryset = queryset.filter(**{f"{date_field}__gte": request.query_params["date_from"]})
    if date_field and request.query_params.get("date_to"):
        queryset = queryset.filter(**{f"{date_field}__lte": request.query_params["date_to"]})
    return queryset


def _decimal(value):
    return Decimal(value or 0)


def _decimal_string(value):
    normalized = format(Decimal(value or 0).normalize(), "f")
    return "0" if normalized == "-0" else normalized


def _metric(code, label, value, unit, definition):
    metric_value = _decimal_string(value) if isinstance(value, Decimal) else str(value)
    return {"code": code, "label": label, "value": metric_value, "unit": unit, "definition": definition}


def _currency_metrics(row):
    gross = _decimal(row["gross"])
    net = _decimal(row["net"])
    orders = int(row["orders"] or 0)
    units = int(row["units"] or 0)
    refunds = _decimal(row["refunds"])
    return [
        _metric("gross_sales", "销售额", gross, row["currency"], "当前币种订单销售金额"),
        _metric("net_sales", "净销售额", net, row["currency"], "当前币种销售额扣除实际退款"),
        _metric("order_count", "订单量", orders, "单", "当前币种订单量"),
        _metric("units_sold", "销售件数", units, "件", "当前币种有效订单行数量"),
        _metric("average_order_value", "客单价", net / orders if orders else 0, row["currency"], "当前币种净销售额 / 订单量"),
        _metric("refund_amount", "退款金额", refunds, row["currency"], "当前币种已完成实际退款"),
        _metric("refund_rate", "退款率", refunds / gross if gross else 0, "比例", "当前币种实际退款金额 / 销售额"),
    ]


def _source_status(sources):
    sources = list(sources)
    if not sources:
        return "pending"
    if any(source.run_status in {"failed", "partial"} for source in sources):
        return "partial"
    stale_before = timezone.now() - timedelta(hours=24)
    if any(not source.last_success_at or source.last_success_at < stale_before for source in sources):
        return "stale"
    return "ready"


class SalesOverviewView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "sales_management.view"

    def get(self, request):
        facts = filter_sales_queryset(
            request.user,
            self.read_permission_code,
            StoreSalesFact.objects.filter(tenant=request.user.tenant),
        )
        facts = _apply_dimensions(facts, request, date_field="period_start")
        selected_currency = str(request.query_params.get("currency") or "").strip().upper()
        if selected_currency:
            facts = facts.filter(currency=selected_currency)
        currency_rows = list(
            facts.values("currency")
            .annotate(
                gross=Coalesce(Sum("gross_sales"), Decimal("0")),
                net=Coalesce(Sum("net_sales"), Decimal("0")),
                orders=Coalesce(Sum("order_count"), 0),
                units=Coalesce(Sum("units_sold"), 0),
                refunds=Coalesce(Sum("refund_amount"), Decimal("0")),
                refreshed_at=Max("source_updated_at"),
            )
            .order_by("currency")
        )
        currency_groups = [
            {"currency": row["currency"], "metrics": _currency_metrics(row), "refreshed_at": row["refreshed_at"]}
            for row in currency_rows
        ]
        single_currency = currency_groups[0] if len(currency_groups) == 1 else None
        trend = [
            {"label": str(row["period_start"]), "currency": row["currency"], "value": _decimal_string(row["value"])}
            for row in facts.values("period_start", "currency")
            .annotate(value=Sum("net_sales"))
            .order_by("period_start", "currency")
        ]
        issues = filter_sales_queryset(
            request.user,
            self.read_permission_code,
            DataQualityIssue.objects.filter(tenant=request.user.tenant, status="open"),
        )[:8]
        sources = filter_sales_queryset(
            request.user,
            self.read_permission_code,
            SyncSource.objects.filter(tenant=request.user.tenant),
        )
        return success_response(
            {
                "api_status": "mock",
                "source_status": _source_status(sources),
                "quality": {
                    "status": "attention" if issues else ("empty" if not facts.exists() else "healthy"),
                    "score": max(0, 100 - len(issues) * 8),
                    "refreshed_at": max(
                        (row["refreshed_at"] for row in currency_rows if row["refreshed_at"]),
                        default=None,
                    ),
                },
                "definition": {
                    "currency_basis": "金额指标严格按币种分组；仅单一或显式筛选币种时提供顶部汇总",
                    "timezone_basis": "按门店来源时区归一后使用 UTC 存储",
                    "refund_basis": "实际退款金额 / 销售额",
                },
                "aggregation_status": "single_currency" if single_currency else ("grouped_by_currency" if currency_groups else "empty"),
                "currency": single_currency["currency"] if single_currency else None,
                "metrics": single_currency["metrics"] if single_currency else [],
                "currency_groups": currency_groups,
                "trend": trend,
                "results": StoreSalesFactSerializer(facts.order_by("-net_sales")[:10], many=True).data,
                "anomalies": DataQualityIssueSerializer(issues, many=True).data,
                "count": facts.count(),
            }
        )


class SalesOrderCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "sales_management.orders.view"

    def get(self, request):
        queryset = SalesOrder.objects.filter(tenant=request.user.tenant).annotate(item_count=Coalesce(Sum("lines__quantity"), 0))
        queryset = filter_sales_queryset(request.user, self.read_permission_code, queryset)
        queryset = _apply_dimensions(queryset, request, date_field="ordered_at")
        for parameter, field in (
            ("order_status", "order_status"), ("fulfillment_status", "fulfillment_status"),
            ("refund_status", "refund_status"), ("currency", "currency"),
        ):
            if request.query_params.get(parameter):
                queryset = queryset.filter(**{field: request.query_params[parameter]})
        if request.query_params.get("order_no"):
            value = request.query_params["order_no"]
            queryset = queryset.filter(source_order_id__icontains=value) | queryset.filter(system_order_no__icontains=value)
        if request.query_params.get("sku"):
            queryset = queryset.filter(lines__sku__icontains=request.query_params["sku"])
        page, page_size = _pagination(request)
        queryset = queryset.distinct().order_by("-ordered_at", "-id")
        return success_response(paginated_data(request, queryset, SalesOrderSerializer, page=page, page_size=page_size))


class SalesOrderDetailView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "sales_management.orders.view"

    def get(self, request, pk):
        queryset = filter_sales_queryset(
            request.user,
            self.read_permission_code,
            SalesOrder.objects.filter(tenant=request.user.tenant).annotate(item_count=Coalesce(Sum("lines__quantity"), 0)),
        )
        order = get_object_or_404(queryset, pk=pk)
        return success_response(SalesOrderDetailSerializer(order, context={"request": request}).data)


class SalesReturnCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "sales_management.returns.view"

    def get(self, request):
        queryset = filter_sales_queryset(
            request.user,
            self.read_permission_code,
            SalesReturn.objects.filter(tenant=request.user.tenant).select_related("order"),
        )
        queryset = _apply_dimensions(queryset, request, date_field="requested_at")
        for parameter in ("status", "return_type", "sku"):
            if request.query_params.get(parameter):
                queryset = queryset.filter(**{parameter: request.query_params[parameter]})
        page, page_size = _pagination(request)
        return success_response(paginated_data(request, queryset, SalesReturnSerializer, page=page, page_size=page_size))


class StoreSalesCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "sales_management.stores.view"

    def get(self, request):
        queryset = filter_sales_queryset(
            request.user,
            self.read_permission_code,
            StoreSalesFact.objects.filter(tenant=request.user.tenant),
        )
        queryset = _apply_dimensions(queryset, request, date_field="period_start")
        page, page_size = _pagination(request)
        return success_response(paginated_data(request, queryset, StoreSalesFactSerializer, page=page, page_size=page_size))


class SKUSalesCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "sales_management.skus.view"

    def get(self, request):
        queryset = filter_sales_queryset(
            request.user,
            self.read_permission_code,
            SKUSalesFact.objects.filter(tenant=request.user.tenant),
        )
        queryset = _apply_dimensions(queryset, request, date_field="period_start")
        for parameter in ("sku", "spu", "category", "inventory_risk"):
            if request.query_params.get(parameter):
                queryset = queryset.filter(**{f"{parameter}__icontains": request.query_params[parameter]})
        page, page_size = _pagination(request)
        return success_response(paginated_data(request, queryset, SKUSalesFactSerializer, page=page, page_size=page_size))


class SalesExportCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "sales_management.export"
    write_permission_code = "sales_management.export"
    export_types = {"orders", "order_lines", "returns", "store_sales", "sku_sales"}

    def get(self, request):
        queryset = SalesExportRequest.objects.filter(tenant=request.user.tenant, requested_by=request.user)
        visible_exports = []
        for export in queryset:
            try:
                validate_export_filters(export.export_type, export.filters)
            except ValidationError:
                continue
            if scope_snapshot_is_visible(request.user, self.read_permission_code, export.data_scope) and scope_allows_filters(
                request.user, self.read_permission_code, export.filters
            ):
                visible_exports.append(export)
        page, page_size = _pagination(request)
        return success_response(paginated_data(request, visible_exports, SalesExportRequestSerializer, page=page, page_size=page_size))

    def post(self, request):
        request_key = validate_export_request_key(request.headers.get("Idempotency-Key", ""))
        export_type = request.data.get("export_type")
        filters = request.data.get("filters") or {}
        if export_type not in self.export_types:
            raise ValidationError("Unsupported sales export type.")
        filters = validate_export_filters(export_type, filters)
        if not scope_allows_filters(request.user, self.write_permission_code, filters):
            raise PermissionDenied("Export filters exceed the authorized data scope.")
        export, created = create_export_request(
            user=request.user,
            request_key=request_key,
            export_type=export_type,
            filters=filters,
            data_scope=safe_scope_snapshot(request.user, self.write_permission_code),
        )
        return success_response(SalesExportRequestSerializer(export).data, status=201 if created else 200)


class SalesDataQualityView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "sales_management.data_quality.view"

    def get(self, request):
        issues = filter_sales_queryset(
            request.user,
            self.read_permission_code,
            DataQualityIssue.objects.filter(tenant=request.user.tenant),
        )
        sources = SyncSource.objects.none()
        if check_user_permission(request.user, "sales_management.sync.view"):
            sources = filter_sales_queryset(
                request.user,
                "sales_management.sync.view",
                SyncSource.objects.filter(tenant=request.user.tenant),
            )
        return success_response(
            {
                "api_status": "mock",
                "source_status": _source_status(sources),
                "issues": DataQualityIssueSerializer(issues[:100], many=True).data,
                "sources": SyncSourceSerializer(sources[:100], many=True).data,
                "counts": dict(issues.values_list("issue_type").annotate(count=Count("id"))),
            }
        )


class SyncRerunCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "sales_management.sync.view"
    write_permission_code = "sales_management.sync.rerun"

    def post(self, request):
        request_key, reason = validate_sync_rerun_request(
            request.headers.get("Idempotency-Key", ""),
            request.data.get("reason"),
        )
        sources = filter_sales_queryset(
            request.user,
            self.write_permission_code,
            SyncSource.objects.filter(tenant=request.user.tenant),
        )
        source = get_object_or_404(sources, pk=request.data.get("sync_source_id"))
        rerun, created = create_sync_rerun_request(
            user=request.user,
            source=source,
            request_key=request_key,
            reason=reason,
            data_scope=safe_scope_snapshot(request.user, self.write_permission_code),
        )
        return success_response(SyncRerunRequestSerializer(rerun).data, status=201 if created else 200)
