from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db.models import Count, Max, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.views import APIView

from apps.commerce.models import InventorySnapshot, RefundReturn, RefundReturnItem, SalesOrder, SalesOrderItem
from apps.common.responses import paginated_data, success_response
from apps.integrations.models import APIDataQualityCheck, SyncJob
from apps.masterdata.models import StoreMaster
from apps.permissions.api_permissions import DeclaredApplicationPermission
from apps.permissions.services import check_user_permission
from apps.reports.export_services import create_export_request, visible_export_requests

from .scopes import (
    filter_inventory_queryset,
    filter_quality_queryset,
    filter_sales_queryset,
    filter_sync_job_queryset,
)
from .serializers import (
    DataQualityIssueSerializer,
    InventorySnapshotSerializer,
    SalesExportRequestSerializer,
    SalesOrderDetailSerializer,
    SalesOrderSerializer,
    SalesReturnSerializer,
    SyncSourceSerializer,
)


ZERO = Decimal("0")


def _pagination(request):
    try:
        page = max(1, int(request.query_params.get("page", 1)))
        page_size = min(100, max(1, int(request.query_params.get("page_size", 20))))
    except (TypeError, ValueError) as exc:
        raise ValidationError("Invalid pagination values.") from exc
    return page, page_size


def _paginated_rows(request, rows):
    page, page_size = _pagination(request)
    count = len(rows)
    start = (page - 1) * page_size
    if start >= count and count:
        raise ValidationError("Requested page does not exist.")

    def page_url(target):
        if target is None:
            return None
        params = request.query_params.copy()
        params["page"] = target
        params["page_size"] = page_size
        return request.build_absolute_uri(f"{request.path}?{params.urlencode()}")

    end = start + page_size
    return {
        "count": count,
        "next": page_url(page + 1) if end < count else None,
        "previous": page_url(page - 1) if page > 1 else None,
        "results": rows[start:end],
    }


def _parse_date(value, field_name):
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError) as exc:
        raise ValidationError({field_name: "Expected an ISO date."}) from exc


def _apply_dimensions(queryset, request, *, date_field=None, region_field="region"):
    if request.query_params.get("platform"):
        queryset = queryset.filter(platform__platform_type=request.query_params["platform"])
    region = request.query_params.get("region") or request.query_params.get("country")
    if region and region_field:
        queryset = queryset.filter(**{region_field: region})
    if request.query_params.get("store_id"):
        queryset = queryset.filter(store_id=request.query_params["store_id"])
    if request.query_params.get("currency"):
        queryset = queryset.filter(currency=str(request.query_params["currency"]).upper())
    if not date_field:
        return queryset

    start_date = _parse_date(
        request.query_params.get("date_from") or request.query_params.get("period_start"),
        "date_from",
    )
    end_date = _parse_date(
        request.query_params.get("date_to") or request.query_params.get("period_end"),
        "date_to",
    )
    if not start_date and not end_date:
        return queryset
    stores = StoreMaster.objects.filter(tenant=request.user.tenant)
    if request.query_params.get("store_id"):
        stores = stores.filter(pk=request.query_params["store_id"])
    date_scope = Q(pk__in=[])
    for store in stores:
        try:
            store_tz = ZoneInfo(store.timezone)
        except Exception as exc:
            raise ValidationError({"store_id": "Store timezone is invalid."}) from exc
        branch = Q(store_id=store.id)
        if start_date:
            local_start = datetime.combine(start_date, time.min, tzinfo=store_tz).astimezone(UTC)
            branch &= Q(**{f"{date_field}__gte": local_start})
        if end_date:
            local_end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=store_tz).astimezone(UTC)
            branch &= Q(**{f"{date_field}__lt": local_end})
        date_scope |= branch
    return queryset.filter(date_scope)


def _decimal_string(value):
    normalized = format(Decimal(value or 0).normalize(), "f")
    return "0" if normalized == "-0" else normalized


def _metric(code, label, value, unit, definition):
    return {"code": code, "label": label, "value": _decimal_string(value), "unit": unit, "definition": definition}


def _scoped_orders(request, permission_code):
    queryset = SalesOrder.objects.filter(tenant=request.user.tenant).select_related("platform", "store")
    queryset = filter_sales_queryset(request.user, permission_code, queryset)
    return _apply_dimensions(queryset, request, date_field="created_at_utc")


def _scoped_refunds(request, permission_code):
    queryset = RefundReturn.objects.filter(tenant=request.user.tenant).select_related("platform", "store", "sales_order")
    queryset = filter_sales_queryset(
        request.user,
        permission_code,
        queryset,
        {
            "store_ids": "store_id",
            "platforms": "platform__platform_type",
            "regions": "store__country_code",
        },
    )
    queryset = _apply_dimensions(
        queryset,
        request,
        date_field="requested_at_utc",
        region_field=None,
    )
    region = request.query_params.get("region") or request.query_params.get("country")
    if region:
        queryset = queryset.filter(
            Q(sales_order__region=region)
            | Q(sales_order__isnull=True, store__country_code=region)
        )
    return queryset


def _currency_summary(orders, refunds):
    refunds = refunds.filter(normalized_status="completed")
    valid_orders = orders.exclude(normalized_status="cancelled")
    rows = {}
    for row in orders.values("currency").annotate(
        orders=Count("id"),
        refreshed_at=Max("updated_at_utc"),
    ):
        rows[row["currency"]] = {
            "currency": row["currency"],
            "gross": ZERO,
            "orders": row["orders"],
            "valid_orders": 0,
            "cancelled_orders": 0,
            "units": 0,
            "refunds": ZERO,
            "refreshed_at": row["refreshed_at"],
        }
    for row in valid_orders.values("currency").annotate(
        gross=Coalesce(Sum("order_total_amount"), ZERO),
        valid_orders=Count("id"),
    ):
        target = rows.setdefault(row["currency"], {"currency": row["currency"], "gross": ZERO, "orders": 0, "valid_orders": 0, "cancelled_orders": 0, "units": 0, "refunds": ZERO, "refreshed_at": None})
        target["gross"] = row["gross"]
        target["valid_orders"] = row["valid_orders"]
    for row in orders.filter(normalized_status="cancelled").values("currency").annotate(cancelled_orders=Count("id")):
        rows[row["currency"]]["cancelled_orders"] = row["cancelled_orders"]
    for row in SalesOrderItem.objects.filter(sales_order__in=valid_orders).values("currency").annotate(units=Sum("quantity")):
        rows.setdefault(row["currency"], {"currency": row["currency"], "gross": ZERO, "orders": 0, "valid_orders": 0, "cancelled_orders": 0, "units": 0, "refunds": ZERO, "refreshed_at": None})["units"] = row["units"] or 0
    for row in refunds.values("currency").annotate(refunds=Coalesce(Sum("refund_amount"), ZERO), refreshed_at=Max("updated_at_utc")):
        target = rows.setdefault(row["currency"], {"currency": row["currency"], "gross": ZERO, "orders": 0, "valid_orders": 0, "cancelled_orders": 0, "units": 0, "refunds": ZERO, "refreshed_at": None})
        target["refunds"] = row["refunds"]
        target["refreshed_at"] = max(filter(None, (target["refreshed_at"], row["refreshed_at"])), default=None)
    return [rows[key] for key in sorted(rows)]


def _currency_metrics(row):
    gross = Decimal(row["gross"] or 0)
    refunds = Decimal(row["refunds"] or 0)
    net = gross - refunds
    orders = int(row["orders"] or 0)
    return [
        _metric("gross_sales", "Sales", gross, row["currency"], "Order total grouped by currency."),
        _metric("net_sales", "Net sales", net, row["currency"], "Order total less completed refund facts."),
        _metric("order_count", "Orders", orders, "orders", "Distinct sales orders."),
        _metric("valid_order_count", "Valid orders", row["valid_orders"], "orders", "Orders excluding cancelled orders."),
        _metric("cancelled_order_count", "Cancelled orders", row["cancelled_orders"], "orders", "Orders whose normalized status is cancelled."),
        _metric("units_sold", "Units", row["units"], "units", "Sales-order item quantity."),
        _metric("average_order_value", "Average order value", net / orders if orders else 0, row["currency"], "Net sales divided by order count."),
        _metric("refund_amount", "Refund amount", refunds, row["currency"], "Refund amount from refund_return only."),
        _metric("refund_rate", "Refund rate", refunds / gross if gross else 0, "ratio", "Refund amount divided by order total."),
    ]


def _store_rows(orders, refunds):
    orders = orders.exclude(normalized_status="cancelled")
    refunds = refunds.filter(normalized_status="completed")
    rows = {}
    dimensions = ("store_id", "store__code", "platform__platform_type", "region", "currency")
    for row in orders.values(*dimensions).annotate(
        gross_sales=Coalesce(Sum("order_total_amount"), ZERO),
        order_count=Count("id"),
        source_updated_at=Max("updated_at_utc"),
    ):
        key = tuple(row[field] for field in dimensions)
        rows[key] = {**row, "units_sold": 0, "refund_amount": ZERO}
    for row in SalesOrderItem.objects.filter(sales_order__in=orders).values(
        "sales_order__store_id", "sales_order__store__code", "sales_order__platform__platform_type", "sales_order__region", "currency"
    ).annotate(units_sold=Sum("quantity")):
        key = (
            row["sales_order__store_id"], row["sales_order__store__code"], row["sales_order__platform__platform_type"], row["sales_order__region"], row["currency"]
        )
        if key in rows:
            rows[key]["units_sold"] = row["units_sold"] or 0
    for row in refunds.values(
        "store_id",
        "store__code",
        "store__country_code",
        "platform__platform_type",
        "sales_order__region",
        "currency",
    ).annotate(
        refund_amount=Coalesce(Sum("refund_amount"), ZERO),
        source_updated_at=Max("updated_at_utc"),
    ):
        region = row["sales_order__region"] or row["store__country_code"]
        key = (
            row["store_id"],
            row["store__code"],
            row["platform__platform_type"],
            region,
            row["currency"],
        )
        target = rows.setdefault(
            key,
            {
                "store_id": row["store_id"],
                "store__code": row["store__code"],
                "platform__platform_type": row["platform__platform_type"],
                "region": region,
                "currency": row["currency"],
                "gross_sales": ZERO,
                "order_count": 0,
                "units_sold": 0,
                "refund_amount": ZERO,
                "source_updated_at": row["source_updated_at"],
            },
        )
        target["refund_amount"] = row["refund_amount"]
    output = []
    for row in rows.values():
        gross = Decimal(row["gross_sales"] or 0)
        refund = Decimal(row["refund_amount"] or 0)
        orders_count = int(row["order_count"] or 0)
        output.append({
            "store_id": row["store_id"],
            "store_code": row["store__code"],
            "platform": row["platform__platform_type"],
            "region": row["region"],
            "currency": row["currency"],
            "gross_sales": _decimal_string(gross),
            "net_sales": _decimal_string(gross - refund),
            "order_count": orders_count,
            "units_sold": int(row["units_sold"] or 0),
            "average_order_value": _decimal_string((gross - refund) / orders_count if orders_count else 0),
            "refund_amount": _decimal_string(refund),
            "refund_rate": _decimal_string(refund / gross if gross else 0),
            "source_updated_at": row["source_updated_at"],
        })
    return sorted(output, key=lambda item: (item["currency"], Decimal(item["net_sales"])), reverse=True)


def _sku_rows(orders, refunds):
    orders = orders.exclude(normalized_status="cancelled")
    rows = {}
    items = SalesOrderItem.objects.filter(sales_order__in=orders)
    for row in items.values(
        "sales_order__store_id",
        "sales_order__platform__platform_type",
        "sales_order__region",
        "internal_spu__spu_code",
        "internal_sku__sku_code",
        "seller_sku",
        "platform_product_id",
        "platform_variant_id",
        "item_name_snapshot",
        "currency",
    ).annotate(units_sold=Sum("quantity"), gross_sales=Coalesce(Sum("line_total_amount"), ZERO), order_count=Count("sales_order_id", distinct=True)):
        sku = row["internal_sku__sku_code"] or row["seller_sku"]
        key = (row["sales_order__store_id"], sku, row["currency"])
        rows[key] = {
            "spu": row["internal_spu__spu_code"] or "",
            "sku": sku,
            "internal_sku": row["internal_sku__sku_code"],
            "seller_sku": row["seller_sku"],
            "platform_product_id": row["platform_product_id"],
            "platform_variant_id": row["platform_variant_id"],
            "mapping_status": "mapped" if row["internal_sku__sku_code"] else "unmapped",
            "product_name": row["item_name_snapshot"],
            "store_id": row["sales_order__store_id"],
            "platform": row["sales_order__platform__platform_type"],
            "region": row["sales_order__region"],
            "currency": row["currency"],
            "units_sold": row["units_sold"] or 0,
            "gross_sales": row["gross_sales"],
            "order_count": row["order_count"],
            "refund_units": 0,
            "refund_amount": ZERO,
        }
    refund_items = RefundReturnItem.objects.filter(
        refund_return__in=refunds.filter(normalized_status="completed")
    )
    for row in refund_items.values(
        "refund_return__store_id",
        "refund_return__platform__platform_type",
        "refund_return__sales_order__region",
        "refund_return__store__country_code",
        "internal_sku__sku_code",
        "seller_sku",
        "item_name_snapshot",
        "currency",
    ).annotate(
        refund_units=Sum("quantity"), refund_amount=Coalesce(Sum("refund_amount"), ZERO)
    ):
        sku = row["internal_sku__sku_code"] or row["seller_sku"]
        key = (row["refund_return__store_id"], sku, row["currency"])
        target = rows.setdefault(
            key,
            {
                "spu": "",
                "sku": sku,
                "internal_sku": row["internal_sku__sku_code"],
                "seller_sku": row["seller_sku"],
                "platform_product_id": "",
                "platform_variant_id": "",
                "mapping_status": "mapped" if row["internal_sku__sku_code"] else "unmapped",
                "product_name": row["item_name_snapshot"],
                "store_id": row["refund_return__store_id"],
                "platform": row["refund_return__platform__platform_type"],
                "region": row["refund_return__sales_order__region"]
                or row["refund_return__store__country_code"],
                "currency": row["currency"],
                "units_sold": 0,
                "gross_sales": ZERO,
                "order_count": 0,
                "refund_units": 0,
                "refund_amount": ZERO,
            },
        )
        target["refund_units"] = row["refund_units"] or 0
        target["refund_amount"] = row["refund_amount"]
    output = []
    for row in rows.values():
        gross = Decimal(row["gross_sales"] or 0)
        refund_amount = Decimal(row["refund_amount"] or 0)
        units = int(row["units_sold"] or 0)
        refund_units = int(row["refund_units"] or 0)
        output.append({
            **row,
            "gross_sales": _decimal_string(gross),
            "net_sales": _decimal_string(gross - refund_amount),
            "refund_rate": _decimal_string(Decimal(refund_units) / units if units else 0),
        })
    return sorted(output, key=lambda item: (item["currency"], Decimal(item["gross_sales"])), reverse=True)


def _trend_rows(orders, refunds):
    rows = {}
    for row in orders.values("business_date", "currency").annotate(
        order_count=Count("id"),
        gross_sales=Coalesce(
            Sum("order_total_amount", filter=~Q(normalized_status="cancelled")),
            ZERO,
        ),
    ):
        key = (row["business_date"], row["currency"])
        rows[key] = {
            "date": str(row["business_date"]),
            "currency": row["currency"],
            "order_count": row["order_count"],
            "gross_sales": Decimal(row["gross_sales"] or 0),
            "refund_amount": ZERO,
        }
    for row in refunds.filter(normalized_status="completed").values("requested_at_utc__date", "currency").annotate(
        refund_amount=Coalesce(Sum("refund_amount"), ZERO),
    ):
        business_date = row["requested_at_utc__date"]
        key = (business_date, row["currency"])
        target = rows.setdefault(
            key,
            {
                "date": str(business_date),
                "currency": row["currency"],
                "order_count": 0,
                "gross_sales": ZERO,
                "refund_amount": ZERO,
            },
        )
        target["refund_amount"] = Decimal(row["refund_amount"] or 0)
    return [
        {
            **row,
            "gross_sales": _decimal_string(row["gross_sales"]),
            "refund_amount": _decimal_string(row["refund_amount"]),
            "net_sales": _decimal_string(row["gross_sales"] - row["refund_amount"]),
        }
        for _, row in sorted(rows.items())
    ]


def _parse_boolean(value, field_name):
    if value in (None, ""):
        return None
    normalized = str(value).lower()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    raise ValidationError({field_name: "Expected true or false."})


class CommerceFiltersView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "sales_management.view"

    def get(self, request):
        orders = _scoped_orders(request, self.read_permission_code)
        stores = orders.values(
            "store_id",
            "store__code",
            "store__name",
            "store__country_code",
            "platform__platform_type",
        ).distinct().order_by("store__code")
        inventory = InventorySnapshot.objects.filter(
            tenant=request.user.tenant,
            source_run__sync_job__integration_config__platform="jifeng_wms",
            source_run__sync_job__resource_type="inventory_snapshot",
        ).select_related("warehouse")
        inventory = filter_inventory_queryset(request.user, self.read_permission_code, inventory)
        sync_jobs = filter_sync_job_queryset(
            request.user,
            self.read_permission_code,
            SyncJob.objects.filter(tenant=request.user.tenant),
        )
        return success_response({
            "platforms": list(orders.values_list("platform__platform_type", flat=True).distinct().order_by("platform__platform_type")),
            "stores": [
                {
                    "id": row["store_id"],
                    "code": row["store__code"],
                    "name": row["store__name"],
                    "region": row["store__country_code"],
                    "platform": row["platform__platform_type"],
                }
                for row in stores
            ],
            "sites": list(inventory.values_list("site_code", flat=True).distinct().order_by("site_code")),
            "warehouses": [
                {
                    "id": row["warehouse_id"],
                    "code": row["warehouse__code"],
                    "name": row["warehouse__name"],
                    "site": row["site_code"],
                }
                for row in inventory.values(
                    "warehouse_id", "warehouse__code", "warehouse__name", "site_code"
                ).distinct().order_by("warehouse__code")
            ],
            "currencies": list(orders.values_list("currency", flat=True).distinct().order_by("currency")),
            "order_statuses": list(orders.values_list("normalized_status", flat=True).distinct().order_by("normalized_status")),
            "refund_statuses": list(
                _scoped_refunds(request, self.read_permission_code)
                .values_list("normalized_status", flat=True)
                .distinct()
                .order_by("normalized_status")
            ),
            "coverage_statuses": list(sync_jobs.values_list("status", flat=True).distinct().order_by("status")),
        })


def commerce_overview_payload(request, permission_code, dashboard_type="overview"):
    orders = _scoped_orders(request, permission_code)
    refunds = _scoped_refunds(request, permission_code)
    summaries = _currency_summary(orders, refunds)
    currency_groups = [
        {"currency": row["currency"], "metrics": _currency_metrics(row), "refreshed_at": row["refreshed_at"]}
        for row in summaries
    ]
    single = currency_groups[0] if len(currency_groups) == 1 else None
    return {
        "api_status": "connected",
        "dashboard_type": dashboard_type,
        "source_status": "ready" if orders.exists() else "pending",
        "definition": {
            "currency_basis": "Amounts are grouped by currency and never directly combined.",
            "timezone_basis": "Store-local dates are converted to UTC half-open intervals.",
            "refund_basis": "Refund amounts come only from refund_return.",
        },
        "aggregation_status": "single_currency" if single else ("grouped_by_currency" if summaries else "empty"),
        "currency": single["currency"] if single else None,
        "metrics": single["metrics"] if single else [],
        "currency_groups": currency_groups,
        "trend": _trend_rows(orders, refunds),
        "results": _store_rows(orders, refunds)[:10],
        "count": orders.count(),
    }


class SalesOverviewView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "sales_management.view"

    def get(self, request):
        return success_response(commerce_overview_payload(request, self.read_permission_code))


class SalesTrendView(SalesOverviewView):
    def get(self, request):
        orders = _scoped_orders(request, self.read_permission_code)
        refunds = _scoped_refunds(request, self.read_permission_code)
        rows = _trend_rows(orders, refunds)
        return success_response({"count": len(rows), "results": rows})


class SalesOrderCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "sales_management.orders.view"

    def get(self, request):
        queryset = _scoped_orders(request, self.read_permission_code).annotate(item_count=Coalesce(Sum("items__quantity"), 0))
        status = request.query_params.get("status") or request.query_params.get("order_status")
        if status:
            queryset = queryset.filter(normalized_status=status)
        order_id = request.query_params.get("external_order_id") or request.query_params.get("order_no")
        if order_id:
            queryset = queryset.filter(external_order_id__icontains=order_id)
        if request.query_params.get("sku"):
            value = request.query_params["sku"]
            queryset = queryset.filter(Q(items__seller_sku__icontains=value) | Q(items__internal_sku__sku_code__icontains=value))
        has_refund = _parse_boolean(request.query_params.get("has_refund_return"), "has_refund_return")
        if has_refund is not None:
            queryset = queryset.filter(refund_returns__isnull=not has_refund)
        if request.query_params.get("refund_status"):
            queryset = queryset.filter(refund_returns__normalized_status=request.query_params["refund_status"])
        page, page_size = _pagination(request)
        queryset = queryset.distinct().prefetch_related("refund_returns").order_by("-created_at_utc", "-id")
        return success_response(paginated_data(request, queryset, SalesOrderSerializer, page=page, page_size=page_size))


class SalesOrderDetailView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "sales_management.orders.view"

    def get(self, request, pk):
        queryset = (
            _scoped_orders(request, self.read_permission_code)
            .annotate(item_count=Coalesce(Sum("items__quantity"), 0))
            .prefetch_related(
                "items__internal_spu",
                "items__internal_sku",
                "refund_returns__items__internal_sku",
                "refund_returns__items__sales_order_item",
            )
        )
        order = get_object_or_404(queryset, pk=pk)
        return success_response(SalesOrderDetailSerializer(order).data)


class SalesReturnCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    # Refund/return records are exposed through the dedicated menu contract.
    # Keep order permissions scoped to order endpoints only.
    read_permission_code = "sales_management.returns.view"

    def get(self, request):
        queryset = _scoped_refunds(request, self.read_permission_code)
        if request.query_params.get("refund_status") or request.query_params.get("status"):
            queryset = queryset.filter(normalized_status=request.query_params.get("refund_status") or request.query_params["status"])
        if request.query_params.get("case_type") or request.query_params.get("return_type"):
            queryset = queryset.filter(case_type=request.query_params.get("case_type") or request.query_params["return_type"])
        if request.query_params.get("sku"):
            queryset = queryset.filter(items__seller_sku__icontains=request.query_params["sku"])
        page, page_size = _pagination(request)
        queryset = queryset.distinct().prefetch_related("items__internal_sku", "items__sales_order_item")
        return success_response(paginated_data(request, queryset, SalesReturnSerializer, page=page, page_size=page_size))


class StoreSalesCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "sales_management.stores.view"

    def get(self, request):
        return success_response(_paginated_rows(request, _store_rows(_scoped_orders(request, self.read_permission_code), _scoped_refunds(request, self.read_permission_code))))


class SKUSalesCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "sales_management.skus.view"

    def get(self, request):
        rows = _sku_rows(_scoped_orders(request, self.read_permission_code), _scoped_refunds(request, self.read_permission_code))
        for field in ("sku", "spu"):
            if request.query_params.get(field):
                value = request.query_params[field].lower()
                rows = [row for row in rows if value in str(row[field]).lower()]
        return success_response(_paginated_rows(request, rows))


class InventoryCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "sales_management.view"

    def get(self, request):
        return success_response(commerce_inventory_payload(request, self.read_permission_code))


def commerce_inventory_payload(request, permission_code):
    queryset = InventorySnapshot.objects.filter(
        tenant=request.user.tenant,
        source_run__sync_job__integration_config__platform="jifeng_wms",
        source_run__sync_job__resource_type="inventory_snapshot",
    ).select_related("warehouse", "internal_sku")
    queryset = filter_inventory_queryset(request.user, permission_code, queryset)
    if request.query_params.get("site_code"):
        queryset = queryset.filter(site_code=request.query_params["site_code"])
    if request.query_params.get("warehouse_id"):
        queryset = queryset.filter(warehouse_id=request.query_params["warehouse_id"])
    if request.query_params.get("sku") or request.query_params.get("sku_id"):
        value = request.query_params.get("sku") or request.query_params["sku_id"]
        queryset = queryset.filter(
            Q(source_sku__icontains=value)
            | Q(seller_sku__icontains=value)
            | Q(internal_sku__sku_code__icontains=value)
        )
    latest_snapshot = InventorySnapshot.objects.filter(
        tenant=request.user.tenant,
        site_code=OuterRef("site_code"),
        warehouse_id=OuterRef("warehouse_id"),
        source_sku=OuterRef("source_sku"),
        source_run__sync_job__integration_config__platform="jifeng_wms",
        source_run__sync_job__resource_type="inventory_snapshot",
    ).order_by("-snapshot_at_utc", "-id")
    queryset = queryset.filter(pk=Subquery(latest_snapshot.values("pk")[:1])).order_by(
        "site_code", "warehouse_id", "source_sku"
    )
    page, page_size = _pagination(request)
    data = paginated_data(request, queryset, InventorySnapshotSerializer, page=page, page_size=page_size)
    data.update({
        "api_status": "connected",
        "dashboard_type": "inventory",
        "source_status": "ready" if data["count"] else "pending",
        "definition": {
            "inventory_basis": "Latest Jifeng WMS inventory_snapshot per site, warehouse and SKU."
        },
    })
    return data


class SalesDataQualityView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "sales_management.data_quality.view"

    def get(self, request):
        issues = APIDataQualityCheck.objects.filter(tenant=request.user.tenant).select_related("sync_log__task")
        issues = filter_quality_queryset(request.user, self.read_permission_code, issues)
        sources = SyncJob.objects.none()
        if check_user_permission(request.user, "sales_management.sync.view"):
            sources = filter_sync_job_queryset(
                request.user,
                "sales_management.sync.view",
                SyncJob.objects.filter(tenant=request.user.tenant).select_related("integration_config"),
            )
        return success_response({
            "api_status": "connected",
            "issues": DataQualityIssueSerializer(issues[:100], many=True).data,
            "sources": SyncSourceSerializer(sources[:100], many=True).data,
            "counts": dict(issues.values_list("status").annotate(count=Count("id"))),
        })


class SalesExportCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "sales_management.export"
    write_permission_code = "sales_management.export"

    def get(self, request):
        queryset = visible_export_requests(request.user, "sales_management.export")
        page, page_size = _pagination(request)
        return success_response(paginated_data(request, queryset, SalesExportRequestSerializer, page=page, page_size=page_size))

    def post(self, request):
        export = create_export_request(
            user=request.user,
            report_type="sales_details",
            filters=request.data.get("filters") or {},
            permission_code="sales_management.export",
        )
        return success_response(SalesExportRequestSerializer(export).data, status=201)
