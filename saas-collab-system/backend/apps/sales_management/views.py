from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db.models import Count, F, Max, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.views import APIView

from apps.commerce.models import InventorySnapshot, RefundReturn, RefundReturnItem, SalesOrder, SalesOrderItem
from apps.common.responses import paginated_data, success_response
from apps.integrations.models import (
    APIDataQualityCheck,
    MarketplaceStoreAuthorization,
    MarketplaceStoreMapping,
    SyncJob,
    SyncRun,
)
from apps.masterdata.models import StoreMaster, WarehouseMaster
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
    queryset = SalesOrder.objects.filter(tenant=request.user.tenant).select_related("platform", "store", "authorization")
    queryset = filter_sales_queryset(request.user, permission_code, queryset)
    return _apply_dimensions(queryset, request, date_field="created_at_utc")


def _scoped_refunds(request, permission_code):
    queryset = RefundReturn.objects.filter(tenant=request.user.tenant).select_related(
        "platform", "store", "source_run__sync_job__integration_config", "sales_order"
    )
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


def _currency_summary(orders, refunds, original_dimensions=False):
    if not original_dimensions:
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
    unit_orders = orders if original_dimensions else valid_orders
    for row in SalesOrderItem.objects.filter(sales_order__in=unit_orders).values("currency").annotate(units=Sum("quantity")):
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


def _store_rows(orders, refunds, original_dimensions=False):
    all_orders = orders
    if not original_dimensions:
        refunds = refunds.filter(normalized_status="completed")
        orders = orders.exclude(normalized_status="cancelled")
    rows = {}
    dimensions = (
        "store_id",
        "store__code",
        "store__name",
        "platform__platform_type",
        "region",
        "currency",
    )
    gross_sales = (
        Sum("order_total_amount", filter=~Q(normalized_status="cancelled"))
        if original_dimensions
        else Sum("order_total_amount")
    )
    for row in orders.values(*dimensions).annotate(
        gross_sales=Coalesce(gross_sales, ZERO),
        order_count=Count("id"),
        source_alias=Max("authorization__account_alias"),
        source_updated_at=Max("updated_at_utc"),
    ):
        key = tuple(row[field] for field in dimensions)
        rows[key] = {**row, "units_sold": 0, "refund_amount": ZERO, "has_refund": False}
    item_orders = all_orders if original_dimensions else orders
    for row in SalesOrderItem.objects.filter(sales_order__in=item_orders).values(
        "sales_order__store_id", "sales_order__store__code", "sales_order__store__name",
        "sales_order__platform__platform_type", "sales_order__region", "currency"
    ).annotate(units_sold=Sum("quantity")):
        key = (
            row["sales_order__store_id"], row["sales_order__store__code"],
            row["sales_order__store__name"], row["sales_order__platform__platform_type"],
            row["sales_order__region"], row["currency"]
        )
        if key in rows:
            rows[key]["units_sold"] = row["units_sold"] or 0
    for row in refunds.values(
        "store_id",
        "store__code",
        "store__name",
        "store__country_code",
        "platform__platform_type",
        "source_run__sync_job__integration_config__account_alias",
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
            row["store__name"],
            row["platform__platform_type"],
            region,
            row["currency"],
        )
        target = rows.setdefault(
            key,
            {
                "store_id": row["store_id"],
                "store__code": row["store__code"],
                "store__name": row["store__name"],
                "platform__platform_type": row["platform__platform_type"],
                "source_alias": row["source_run__sync_job__integration_config__account_alias"],
                "region": region,
                "currency": row["currency"],
                "gross_sales": ZERO,
                "order_count": 0,
                "units_sold": 0,
                "refund_amount": ZERO,
                "has_refund": False,
                "source_updated_at": row["source_updated_at"],
            },
        )
        target["refund_amount"] = row["refund_amount"]
        target["has_refund"] = True
        target["source_updated_at"] = max(
            filter(None, (target["source_updated_at"], row["source_updated_at"])),
            default=None,
        )
    output = []
    for row in rows.values():
        gross = Decimal(row["gross_sales"] or 0)
        refund = Decimal(row["refund_amount"] or 0)
        orders_count = int(row["order_count"] or 0)
        output.append({
            "store_id": row["store_id"],
            "store_code": row["store__code"],
            "store_name": row["store__name"],
            "source_alias": row.get("source_alias") or row["store__code"],
            "platform": row["platform__platform_type"],
            "region": row["region"],
            "currency": row["currency"],
            "gross_sales": _decimal_string(gross),
            "net_sales": _decimal_string(gross - refund),
            "order_count": orders_count,
            "units_sold": int(row["units_sold"] or 0),
            "average_order_value": _decimal_string(
                (gross if original_dimensions else gross - refund) / orders_count
                if orders_count else 0
            ),
            "refund_amount": None if original_dimensions and not row["has_refund"] else _decimal_string(refund),
            "refund_rate": _decimal_string(refund / gross if gross else 0),
            "quality": "healthy",
            "source_updated_at": row["source_updated_at"],
        })
    if original_dimensions:
        platform_order = {"tiktok": 0, "shopee": 1}
        region_order = {"TH": 0, "MY": 1, "PH": 2}
        return sorted(
            output,
            key=lambda item: (
                platform_order.get(item["platform"], 99),
                region_order.get(item["region"], 99),
                item["store_name"],
            ),
        )
    return sorted(output, key=lambda item: (item["currency"], Decimal(item["net_sales"])), reverse=True)


def _sku_rows(orders, refunds, original_dimensions=False):
    if not original_dimensions:
        orders = orders.exclude(normalized_status="cancelled")
    rows = {}
    items = SalesOrderItem.objects.filter(sales_order__in=orders)
    for row in items.values(
        "sales_order__store_id",
        "sales_order__store__name",
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
            "store_name": row["sales_order__store__name"],
            "platform": row["sales_order__platform__platform_type"],
            "region": row["sales_order__region"],
            "currency": row["currency"],
            "units_sold": row["units_sold"] or 0,
            "gross_sales": row["gross_sales"],
            "order_count": row["order_count"],
            "refund_units": 0,
            "refund_amount": ZERO,
        }
    refund_facts = refunds if original_dimensions else refunds.filter(normalized_status="completed")
    refund_items = RefundReturnItem.objects.filter(refund_return__in=refund_facts)
    for row in refund_items.values(
        "refund_return__store_id",
        "refund_return__store__name",
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
                "store_name": row["refund_return__store__name"],
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
    if original_dimensions:
        return sorted(output, key=lambda item: (int(item["units_sold"]), Decimal(item["gross_sales"])), reverse=True)
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


def _analytics_trend_rows(orders, refunds):
    rows = {}
    for row in orders.values("business_date", "currency").annotate(
        order_count=Count("id"),
        gross_sales=Coalesce(
            Sum("order_total_amount", filter=~Q(normalized_status="cancelled")),
            ZERO,
        ),
    ):
        key = str(row["business_date"])
        target = rows.setdefault(
            key,
            {"date": key, "order_count": 0, "gross_sales": {}, "refund_amount": {}},
        )
        target["order_count"] += int(row["order_count"] or 0)
        target["gross_sales"][row["currency"]] = _decimal_string(row["gross_sales"])
    for row in refunds.values("requested_at_utc__date", "currency").annotate(
        refund_amount=Coalesce(Sum("refund_amount"), ZERO),
    ):
        key = str(row["requested_at_utc__date"])
        target = rows.setdefault(
            key,
            {"date": key, "order_count": 0, "gross_sales": {}, "refund_amount": {}},
        )
        target["refund_amount"][row["currency"]] = _decimal_string(row["refund_amount"])
    output = []
    for key in sorted(rows):
        row = rows[key]
        currencies = set(row["gross_sales"]) | set(row["refund_amount"])
        row["net_sales"] = {
            currency: _decimal_string(
                Decimal(row["gross_sales"].get(currency, 0))
                - Decimal(row["refund_amount"].get(currency, 0))
            )
            for currency in currencies
        }
        output.append(row)
    return output


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
        return success_response(commerce_filters_payload(request, self.read_permission_code))


def commerce_filters_payload(request, permission_code):
    orders = _scoped_orders(request, permission_code)
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
    inventory = filter_inventory_queryset(request.user, permission_code, inventory)
    sync_jobs = filter_sync_job_queryset(
        request.user,
        permission_code,
        SyncJob.objects.filter(tenant=request.user.tenant),
    )
    return {
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
            _scoped_refunds(request, permission_code)
            .values_list("normalized_status", flat=True)
            .distinct()
            .order_by("normalized_status")
        ),
        "coverage_statuses": list(sync_jobs.values_list("status", flat=True).distinct().order_by("status")),
    }


def _summary_metrics(summaries):
    def money(key):
        return {
            row["currency"]: _decimal_string(row[key])
            for row in summaries
            if row["currency"]
        }

    return [
        {
            "code": "order_count",
            "label": "订单量",
            "value": sum(int(row["orders"] or 0) for row in summaries),
            "unit": "单",
            "change": f"取消 {sum(int(row['cancelled_orders'] or 0) for row in summaries)} 单",
        },
        {
            "code": "units_sold",
            "label": "销售件数",
            "value": sum(int(row["units"] or 0) for row in summaries),
            "unit": "件",
            "change": "按订单明细汇总",
        },
        {
            "code": "gross_sales",
            "label": "销售额",
            "money": money("gross"),
            "change": "按来源币种展示",
        },
        {
            "code": "net_sales",
            "label": "净销售额",
            "money": {
                row["currency"]: _decimal_string(
                    Decimal(row["gross"] or 0) - Decimal(row["refunds"] or 0)
                )
                for row in summaries
                if row["currency"]
            },
            "change": "扣除退款金额",
        },
    ]


def _sales_quality(orders, refunds, summaries):
    items = SalesOrderItem.objects.filter(sales_order__in=orders)
    refund_items = RefundReturnItem.objects.filter(refund_return__in=refunds)
    checked_rows = orders.count() + items.count() + refunds.count() + refund_items.count()
    problem_rows = (
        orders.filter(currency="").count()
        + items.filter(seller_sku="").count()
        + refunds.filter(sales_order__isnull=True).count()
    )
    score = max(0, round((1 - problem_rows / checked_rows) * 100)) if checked_rows else 100
    refreshed_at = max((row["refreshed_at"] for row in summaries if row["refreshed_at"]), default=None)
    return {
        "score": score,
        "status": "healthy" if score >= 95 else "warning",
        "metric_version": "经营分析 v1",
        "refreshed_at": refreshed_at,
        "checked_rows": checked_rows,
        "problem_rows": problem_rows,
    }


def _sales_management_metrics(summaries, refund_count=0):
    order_count = sum(int(row["orders"] or 0) for row in summaries)
    gross = {
        row["currency"]: _decimal_string(row["gross"])
        for row in summaries
        if row["currency"]
    }
    refunds = {
        row["currency"]: _decimal_string(row["refunds"])
        for row in summaries
        if row["currency"]
    }
    gross_total = sum((Decimal(value) for value in gross.values()), ZERO)
    refund_total = sum((Decimal(value) for value in refunds.values()), ZERO)
    return [
        {
            "code": "gross_sales",
            "label": "销售额",
            "money": gross,
            "change": "按来源币种分别展示",
        },
        {
            "code": "net_sales",
            "label": "净销售额",
            "money": {
                row["currency"]: _decimal_string(
                    Decimal(row["gross"] or 0) - Decimal(row["refunds"] or 0)
                )
                for row in summaries
                if row["currency"]
            },
            "change": "销售额减退款金额",
        },
        {
            "code": "order_count",
            "label": "订单量",
            "value": order_count,
            "change": f"取消 {sum(int(row['cancelled_orders'] or 0) for row in summaries)} 单",
        },
        {
            "code": "units_sold",
            "label": "销量",
            "value": sum(int(row["units"] or 0) for row in summaries),
            "change": "按订单商品数量汇总",
        },
        {
            "code": "average_order_value",
            "label": "客单价",
            "money": {
                currency: _decimal_string(Decimal(amount) / order_count if order_count else 0)
                for currency, amount in gross.items()
            },
            "change": "销售额 ÷ 订单量",
        },
        {
            "code": "refund_rate",
            "label": "退款率",
            "value": f"{(refund_total / gross_total * 100 if gross_total else ZERO):.1f}%",
            "change": f"{refund_count} 个退款退货单",
        },
    ]


def _sales_page_context(orders, refunds):
    summaries = _currency_summary(orders, refunds, original_dimensions=True)
    quality = _sales_quality(orders, refunds, summaries)
    return {
        "source_status": "ready" if orders.exists() or refunds.exists() else "pending",
        "refreshed_at": quality["refreshed_at"],
        "definition": {
            "currency_basis": "按来源币种分别展示",
            "data_scope": "当前租户、当前角色及授权门店",
        },
        "quality": quality,
        "summary_metrics": _sales_management_metrics(summaries, refunds.count()),
    }


def commerce_overview_payload(
    request,
    permission_code,
    dashboard_type="overview",
    original_dimensions=False,
    sales_management=False,
):
    orders = _scoped_orders(request, permission_code)
    refunds = _scoped_refunds(request, permission_code)
    summaries = _currency_summary(orders, refunds, original_dimensions=original_dimensions)
    currency_groups = [
        {"currency": row["currency"], "metrics": _currency_metrics(row), "refreshed_at": row["refreshed_at"]}
        for row in summaries
    ]
    single = currency_groups[0] if len(currency_groups) == 1 else None
    store_rows = _store_rows(orders, refunds, original_dimensions=original_dimensions)
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
        "summary_metrics": (
            _sales_management_metrics(summaries, refunds.count())
            if sales_management
            else _summary_metrics(summaries)
        ),
        "quality": _sales_quality(orders, refunds, summaries),
        "currency_groups": currency_groups,
        "trend": _analytics_trend_rows(orders, refunds) if original_dimensions else _trend_rows(orders, refunds),
        "results": store_rows[:50],
        "count": len(store_rows),
        "fact_count": orders.count(),
    }


class SalesOverviewView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "sales_management.view"

    def get(self, request):
        return success_response(
            commerce_overview_payload(
                request,
                self.read_permission_code,
                original_dimensions=True,
                sales_management=True,
            )
        )


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
        scoped_orders = _scoped_orders(request, self.read_permission_code)
        scoped_refunds = _scoped_refunds(request, self.read_permission_code)
        queryset = scoped_orders.annotate(
            item_count=Coalesce(Sum("items__quantity"), 0),
            line_count=Count("items", distinct=True),
        )
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
        data = paginated_data(request, queryset, SalesOrderSerializer, page=page, page_size=page_size)
        data.update(_sales_page_context(scoped_orders, scoped_refunds))
        return success_response(data)


class SalesOrderDetailView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "sales_management.orders.view"

    def get(self, request, pk):
        queryset = (
            _scoped_orders(request, self.read_permission_code)
            .annotate(
                item_count=Coalesce(Sum("items__quantity"), 0),
                line_count=Count("items", distinct=True),
            )
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
        scoped_orders = _scoped_orders(request, self.read_permission_code)
        scoped_refunds = _scoped_refunds(request, self.read_permission_code)
        queryset = scoped_refunds
        if request.query_params.get("refund_status") or request.query_params.get("status"):
            queryset = queryset.filter(normalized_status=request.query_params.get("refund_status") or request.query_params["status"])
        if request.query_params.get("case_type") or request.query_params.get("return_type"):
            queryset = queryset.filter(case_type=request.query_params.get("case_type") or request.query_params["return_type"])
        if request.query_params.get("sku"):
            queryset = queryset.filter(items__seller_sku__icontains=request.query_params["sku"])
        page, page_size = _pagination(request)
        queryset = queryset.distinct().prefetch_related("items__internal_sku", "items__sales_order_item")
        data = paginated_data(request, queryset, SalesReturnSerializer, page=page, page_size=page_size)
        data.update(_sales_page_context(scoped_orders, scoped_refunds))
        return success_response(data)


class StoreSalesCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "sales_management.stores.view"

    def get(self, request):
        orders = _scoped_orders(request, self.read_permission_code)
        refunds = _scoped_refunds(request, self.read_permission_code)
        data = _paginated_rows(request, _store_rows(orders, refunds, original_dimensions=True))
        data.update(_sales_page_context(orders, refunds))
        return success_response(data)


class SKUSalesCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "sales_management.skus.view"

    def get(self, request):
        orders = _scoped_orders(request, self.read_permission_code)
        refunds = _scoped_refunds(request, self.read_permission_code)
        rows = _sku_rows(orders, refunds, original_dimensions=True)
        for field in ("sku", "spu"):
            if request.query_params.get(field):
                value = request.query_params[field].lower()
                rows = [row for row in rows if value in str(row[field]).lower()]
        data = _paginated_rows(request, rows)
        data.update(_sales_page_context(orders, refunds))
        return success_response(data)


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
    ).select_related("warehouse", "internal_sku", "internal_sku__spu")
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
    trend_queryset = queryset
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
    risk = request.query_params.get("risk") or request.query_params.get("risk_level")
    if risk == "out":
        queryset = queryset.filter(available_qty__lte=0)
    elif risk == "low":
        queryset = queryset.filter(available_qty__gt=0, available_qty__lte=5, reserved_qty__lte=F("available_qty"))
    elif risk == "locked":
        queryset = queryset.filter(reserved_qty__gt=F("available_qty"), available_qty__gt=0)
    elif risk == "healthy":
        queryset = queryset.filter(available_qty__gt=5, reserved_qty__lte=F("available_qty"))

    aggregates = queryset.aggregate(
        total=Coalesce(Sum("on_hand_qty"), 0),
        available=Coalesce(Sum("available_qty"), 0),
        reserved=Coalesce(Sum("reserved_qty"), 0),
        in_transit=Coalesce(Sum("in_transit_qty"), 0),
        pending_putaway=Coalesce(Sum("pending_putaway_qty"), 0),
        defective=Coalesce(Sum("defective_qty"), 0),
        refreshed_at=Max("snapshot_at_utc"),
    )
    result_count = queryset.count()
    mapped_count = queryset.filter(internal_sku__isnull=False).count()
    out_of_stock = queryset.filter(available_qty__lte=0).count()
    low_stock = queryset.filter(
        available_qty__gt=0,
        available_qty__lte=5,
        reserved_qty__lte=F("available_qty"),
    ).count()
    trend = list(
        trend_queryset.annotate(date=TruncDate("snapshot_at_utc"))
        .values("date")
        .annotate(
            total=Coalesce(Sum("on_hand_qty"), 0),
            available_qty=Coalesce(Sum("available_qty"), 0),
            reserved=Coalesce(Sum("reserved_qty"), 0),
        )
        .order_by("-date")[:14]
    )
    trend.reverse()
    page, page_size = _pagination(request)
    data = paginated_data(request, queryset, InventorySnapshotSerializer, page=page, page_size=page_size)
    data.update({
        "api_status": "connected",
        "dashboard_type": "inventory",
        "source_status": "ready" if data["count"] else "pending",
        "refreshed_at": aggregates["refreshed_at"],
        "metrics": [
            _metric("inventory_total", "在手库存", aggregates["total"], "件", "最新极风 WMS 快照在手数量。"),
            _metric("inventory_available", "可用库存", aggregates["available"], "件", "最新快照可用数量。"),
            _metric("inventory_reserved", "占用库存", aggregates["reserved"], "件", "最新快照占用数量。"),
            _metric("inventory_in_transit", "在途库存", aggregates["in_transit"], "件", "最新快照在途数量。"),
        ],
        "summary_metrics": [
            {
                "code": "inventory_sku",
                "label": "库存 SKU",
                "value": result_count,
                "unit": "个",
                "change": "当前筛选范围的最新快照",
            },
            {
                "code": "inventory_total",
                "label": "总库存",
                "value": aggregates["total"],
                "unit": "件",
                "change": "极风总库存口径",
            },
            {
                "code": "inventory_available",
                "label": "可用库存",
                "value": aggregates["available"],
                "unit": "件",
                "change": "可直接分配数量",
            },
            {
                "code": "inventory_reserved",
                "label": "锁定库存",
                "value": aggregates["reserved"],
                "unit": "件",
                "change": "已锁定待履约数量",
            },
            {
                "code": "inventory_flow",
                "label": "在途 / 待上架",
                "value": f"{aggregates['in_transit']} / {aggregates['pending_putaway']}",
                "change": "入库链路中的库存",
            },
            {
                "code": "inventory_risk",
                "label": "风险 SKU",
                "value": out_of_stock + low_stock,
                "unit": "个",
                "change": f"缺货 {out_of_stock} · 低库存 {low_stock}",
            },
        ],
        "quality": {
            "score": round(mapped_count * 100 / result_count) if result_count else 0,
            "status": "healthy" if result_count and mapped_count == result_count else ("warning" if result_count else "pending"),
            "metric_version": "inventory_snapshot.v1",
            "refreshed_at": aggregates["refreshed_at"],
        },
        "trend": trend,
        "definition": {
            "inventory_basis": "Latest Jifeng WMS inventory_snapshot per site, warehouse and SKU.",
            "risk_basis": "out: available<=0; low: 1-5; locked: reserved>available; healthy: available>5."
        },
    })
    return data


class SalesDataQualityView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "sales_management.data_quality.view"

    def get(self, request):
        orders = _scoped_orders(request, self.read_permission_code)
        refunds = _scoped_refunds(request, self.read_permission_code)
        issues = APIDataQualityCheck.objects.filter(tenant=request.user.tenant).select_related("sync_log__task")
        issues = filter_quality_queryset(request.user, self.read_permission_code, issues)
        sources = SyncJob.objects.none()
        if check_user_permission(request.user, "sales_management.sync.view"):
            sources = filter_sync_job_queryset(
                request.user,
                "sales_management.sync.view",
                SyncJob.objects.filter(tenant=request.user.tenant).select_related("integration_config"),
            )
            handoff_sources = sources.filter(
                integration_config__account_alias__startswith="sqlite-import:jifeng_wms:"
            )
            if handoff_sources.exists():
                sources = handoff_sources.order_by("integration_config__account_alias")
        data = _sales_page_context(orders, refunds)
        data.update({
            "api_status": "connected",
            "issues": DataQualityIssueSerializer(issues[:100], many=True).data,
            "sources": SyncSourceSerializer(sources[:100], many=True).data,
            "counts": dict(issues.values_list("status").annotate(count=Count("id"))),
        })
        return success_response(data)


class DataLinkageStatusView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "sales_management.data_quality.view"

    def get(self, request):
        tenant = request.user.tenant
        orders = _scoped_orders(request, self.read_permission_code)
        refunds = _scoped_refunds(request, self.read_permission_code)
        inventory = filter_inventory_queryset(
            request.user,
            self.read_permission_code,
            InventorySnapshot.objects.filter(tenant=tenant),
        )
        jobs = filter_sync_job_queryset(
            request.user,
            self.read_permission_code,
            SyncJob.objects.filter(tenant=tenant),
        )
        runs = SyncRun.objects.filter(tenant=tenant, sync_job__in=jobs)
        authorizations = MarketplaceStoreAuthorization.objects.filter(tenant=tenant)
        mappings = MarketplaceStoreMapping.objects.filter(tenant=tenant)

        counts = {
            "stores": StoreMaster.objects.filter(tenant=tenant).count(),
            "warehouses": WarehouseMaster.objects.filter(tenant=tenant).count(),
            "authorizations": authorizations.count(),
            "store_mappings": mappings.count(),
            "unmapped_authorizations": authorizations.filter(store_mappings__isnull=True).count(),
            "sync_jobs": jobs.count(),
            "sync_runs": runs.count(),
            "failed_runs": runs.filter(status=SyncRun.Status.FAILED).count(),
            "orders": orders.count(),
            "refunds": refunds.count(),
            "inventory_snapshots": inventory.count(),
            "unmapped_order_items": SalesOrderItem.objects.filter(
                sales_order__in=orders, internal_sku__isnull=True
            ).count(),
            "unmapped_inventory": inventory.filter(internal_sku__isnull=True).count(),
        }
        latest_success = runs.filter(status=SyncRun.Status.SUCCESS).aggregate(value=Max("finished_at"))["value"]

        steps = [
            {
                "key": "masterdata",
                "label": "本地基础档案",
                "status": "ready" if counts["stores"] and counts["warehouses"] else "pending",
                "count": counts["stores"] + counts["warehouses"],
                "note": f"租户 {tenant.id} · {counts['stores']} 个店铺 · {counts['warehouses']} 个仓库",
                "href": "/master-data/stores",
            },
            {
                "key": "authorization",
                "label": "授权映射",
                "status": "partial" if counts["unmapped_authorizations"] else ("ready" if counts["authorizations"] else "pending"),
                "count": counts["authorizations"],
                "note": f"{counts['store_mappings']} 个已映射 · {counts['unmapped_authorizations']} 个待映射",
                "href": "/integrations/configs",
            },
            {
                "key": "sync",
                "label": "同步运行",
                "status": "partial" if counts["failed_runs"] else ("ready" if latest_success else "pending"),
                "count": counts["sync_runs"],
                "note": f"{counts['sync_jobs']} 个任务 · {counts['failed_runs']} 次失败",
                "href": "/integrations/sync-runs",
            },
            {
                "key": "facts",
                "label": "业务事实",
                "status": "partial" if not counts["refunds"] or counts["unmapped_order_items"] or counts["unmapped_inventory"] else "ready",
                "count": counts["orders"] + counts["refunds"] + counts["inventory_snapshots"],
                "note": f"订单 {counts['orders']} · 退款 {counts['refunds']} · 库存 {counts['inventory_snapshots']}",
                "href": "/sales-management/overview",
            },
        ]
        issues = []
        if counts["unmapped_authorizations"]:
            issues.append({"code": "STORE_MAPPING_MISSING", "count": counts["unmapped_authorizations"], "message": "存在已授权但未完成店铺档案映射的记录。"})
        if counts["failed_runs"]:
            issues.append({"code": "SYNC_RUN_FAILED", "count": counts["failed_runs"], "message": "存在失败的同步运行，需要在 API 数据接入中复核。"})
        if not counts["refunds"]:
            issues.append({"code": "REFUND_FACT_EMPTY", "count": 0, "message": "退款退货事实表尚无数据。"})
        unmapped_skus = counts["unmapped_order_items"] + counts["unmapped_inventory"]
        if unmapped_skus:
            issues.append({"code": "SKU_MAPPING_MISSING", "count": unmapped_skus, "message": "存在未映射内部 SKU 的销售或库存记录，暂不进入 SKU 级决策。"})
        return success_response({
            "api_status": "connected",
            "tenant_id": tenant.id,
            "source_status": "ready" if all(step["status"] == "ready" for step in steps) else "partial",
            "latest_success_at": latest_success,
            "steps": steps,
            "counts": counts,
            "issues": issues,
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
            file_format=request.data.get("file_format") or "csv",
        )
        return success_response(SalesExportRequestSerializer(export).data, status=201)
