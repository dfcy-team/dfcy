"""Read-only period query for received WMS inbound lines."""
import csv
import hashlib
from datetime import datetime, time, timedelta
from io import StringIO
from zoneinfo import ZoneInfo

from django.db.models import Exists, Max, Min, OuterRef, Q, Sum
from django.db.models.functions import Upper
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.commerce.models import InboundRecord
from apps.permissions.services import check_user_permission
from apps.sales_management.scopes import filter_inventory_queryset
from apps.sales_management.warehouse_order_models import WarehouseOutboundLine
from .wms_reconciliation import _eligible_wms, _wms_access

COUNTRY_ZONES = {"PH": "Asia/Manila", "TH": "Asia/Bangkok", "MY": "Asia/Kuala_Lumpur"}


def _local_day_bounds(day, zone):
    start = timezone.make_aware(datetime.combine(day, time.min), zone).astimezone(ZoneInfo("UTC"))
    end = timezone.make_aware(datetime.combine(day + timedelta(days=1), time.min), zone).astimezone(ZoneInfo("UTC"))
    return start, end


def _coverage(rows, site_field, time_field):
    ranges = rows.order_by().annotate(_movement_country=Upper(site_field)).values('_movement_country').annotate(first=Min(time_field), last=Max(time_field))
    return [
        {"site_code": row['_movement_country'],
         "first_date": timezone.localtime(row["first"], ZoneInfo(COUNTRY_ZONES[row['_movement_country']])).date(),
         "last_date": timezone.localtime(row["last"], ZoneInfo(COUNTRY_ZONES[row['_movement_country']])).date()}
        for row in ranges
    ]


def inbound_movements(actor, params):
    if not check_user_permission(actor, "supply.v2.view"):
        from rest_framework.exceptions import PermissionDenied
        raise PermissionDenied("需要 supply.v2.view 才能读取入库明细。")
    rows = _eligible_wms(_wms_access(actor)).filter(received_at_utc__isnull=False, received_quantity__gt=0)
    # Keep source facts intact, but isolate dates that cannot be represented in
    # the supported local calendar. Apply the same predicate to every aggregate,
    # list and export, before any local-time conversion.
    renderable = Q(pk__in=[])
    for country, zone in COUNTRY_ZONES.items():
        renderable |= Q(site_code__iexact=country,
            received_at_utc__gte=datetime(1000, 1, 1, tzinfo=ZoneInfo('UTC')),
            received_at_utc__lt=datetime(9999, 1, 1, tzinfo=ZoneInfo(zone)).astimezone(ZoneInfo('UTC')))
    rows = rows.filter(renderable)
    site = params.get("site_code", "").strip().upper()
    if site:
        if site not in COUNTRY_ZONES:
            raise ValidationError({"site_code": "国家代码仅支持 PH、TH、MY。"})
        rows = rows.filter(site_code__iexact=site)
    warehouse = params.get("warehouse", "").strip()
    if warehouse:
        rows = rows.filter(Q(warehouse__code__icontains=warehouse) | Q(warehouse__name__icontains=warehouse))
    coverage_rows = rows
    document = params.get("document")
    warehouse_id = params.get("warehouse_id")
    if document and warehouse_id:
        rows = rows.filter(external_inbound_id=document, warehouse_id=_warehouse_id(warehouse_id))
    search = params.get("search", "").strip()[:160]
    if search:
        rows = rows.filter(Q(external_inbound_id__icontains=search) | Q(external_line_id__icontains=search)
            | Q(source_sku__icontains=search) | Q(internal_sku__sku_code__icontains=search)
            | Q(internal_sku__legacy_sku_code__icontains=search))

    start_text, end_text = params.get("start_date", ""), params.get("end_date", "")
    try:
        start_date = datetime.strptime(start_text, "%Y-%m-%d").date() if start_text else None
        end_date = datetime.strptime(end_text, "%Y-%m-%d").date() if end_text else None
        page = int(params.get("page", "1"))
        if page < 1 or page > 100000 or any(day and not 1900 <= day.year <= 9998 for day in (start_date, end_date)) or (start_date and end_date and start_date > end_date):
            raise ValueError
    except ValueError as exc:
        raise ValidationError("请检查日期格式、日期范围和页码。") from exc

    # Apply local calendar date boundaries per country so multi-country queries
    # use each warehouse's operating timezone.
    if start_date or end_date:
        countries = [site] if site else list(COUNTRY_ZONES)
        temporal = Q(pk__in=[])
        for country in countries:
            zone = ZoneInfo(COUNTRY_ZONES[country])
            country_rows = Q(site_code=country)
            if start_date:
                country_rows &= Q(received_at_utc__gte=_local_day_bounds(start_date, zone)[0])
            if end_date:
                country_rows &= Q(received_at_utc__lt=_local_day_bounds(end_date, zone)[1])
            temporal |= country_rows
        rows = rows.filter(temporal)

    rows = rows.select_related("warehouse", "internal_sku").order_by("-received_at_utc", "-pk")
    total = rows.count()
    totals = rows.aggregate(quantity=Sum("received_quantity"), latest=Max("received_at_utc"))
    if params.get("export", "").lower() == "csv":
        output = StringIO()
        writer = csv.writer(output)
        def safe_cell(value):
            value = "" if value is None else str(value)
            return "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value
        writer.writerow(["国家", "仓库", "收货时间", "入库单号", "行号", "来源SKU", "内部SKU", "实收数量"])
        for row in rows.iterator(chunk_size=1000):
            country = row.site_code.upper()
            local = timezone.localtime(row.received_at_utc, ZoneInfo(COUNTRY_ZONES[country]))
            writer.writerow([safe_cell(country), safe_cell(row.warehouse.name), local.isoformat(), safe_cell(row.external_inbound_id),
                safe_cell(row.external_line_id), safe_cell(row.source_sku), safe_cell(getattr(row.internal_sku, "sku_code", "")), row.received_quantity])
        response = HttpResponse("\ufeff" + output.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="inbound-movements.csv"'
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
    items = []
    for row in rows[(page - 1) * 20:page * 20]:
        country = row.site_code.upper()
        local = timezone.localtime(row.received_at_utc, ZoneInfo(COUNTRY_ZONES[country]))
        items.append({"id": row.pk, "site_code": country, "warehouse": row.warehouse_id,
            "warehouse_name": row.warehouse.name, "received_at_local": local.isoformat(),
            "external_inbound_id": row.external_inbound_id, "source_sku": row.source_sku,
            "internal_sku": getattr(row.internal_sku, "sku_code", ""),
            "received_quantity": row.received_quantity})
    return {"items": items, "total": total, "received_quantity": totals["quantity"] or 0,
            "latest_at": totals["latest"], "coverage": _coverage(coverage_rows, "site_code", "received_at_utc")}


def _warehouse_id(value):
    try:
        pk = int(value)
        if not 0 < pk < 2**63:
            raise ValueError
        return pk
    except (ValueError, TypeError) as exc:
        raise ValidationError({"warehouse_id": "仓库编号无效。"}) from exc


def outbound_movements(actor, params):
    from rest_framework.exceptions import PermissionDenied

    if not all(check_user_permission(actor, code) for code in ("supply.v2.view", "sales_management.view")):
        raise PermissionDenied("当前账户无权读取出库明细。")
    source = WarehouseOutboundLine.objects.filter(tenant_id=actor.tenant_id,
        warehouse__tenant_id=actor.tenant_id,
        lookup__order__tenant_id=actor.tenant_id)
    duplicates = source.filter(warehouse_id=OuterRef("warehouse_id"), document_key=OuterRef("document_key")).exclude(
        lookup_id=OuterRef("lookup_id"))
    rows = filter_inventory_queryset(actor, "sales_management.view", source, outbound=True).filter(~Exists(duplicates))
    site = params.get("site_code", "").strip().upper()
    if site and site not in COUNTRY_ZONES:
        raise ValidationError({"site_code": "国家代码仅支持 PH、TH、MY。"})
    warehouse = params.get("warehouse", "").strip()[:100]
    search = params.get("search", "").strip()[:160]
    if warehouse:
        rows = rows.filter(Q(warehouse__code__icontains=warehouse) | Q(warehouse__name__icontains=warehouse))
    coverage_rows = rows.filter(site_code__in=[site] if site else COUNTRY_ZONES)
    document = params.get("document")
    warehouse_id = params.get("warehouse_id")
    if document and warehouse_id:
        rows = rows.filter(document_key=hashlib.sha256(document.encode("utf-8")).hexdigest(), warehouse_id=_warehouse_id(warehouse_id))
    if search:
        rows = rows.filter(Q(document__icontains=search) | Q(warehouse_sku__icontains=search) | Q(source_sku__icontains=search))
    try:
        dates = [datetime.strptime(params[key], "%Y-%m-%d").date() if params.get(key) else None
                 for key in ("start_date", "end_date")]
        start, end = dates
        page = int(params.get("page", "1"))
        if not 1 <= page <= 100000 or any(day and not 1900 <= day.year <= 9998 for day in dates) or (start and end and start > end):
            raise ValueError
    except ValueError as exc:
        raise ValidationError("请检查日期格式、日期范围和页码。") from exc
    period = Q(pk__in=[])
    for country in ([site] if site else COUNTRY_ZONES):
        zone = ZoneInfo(COUNTRY_ZONES[country])
        condition = Q(site_code=country)
        if start:
            condition &= Q(shipped_at__gte=_local_day_bounds(start, zone)[0])
        if end:
            condition &= Q(shipped_at__lt=_local_day_bounds(end, zone)[1])
        period |= condition
    rows = rows.filter(period).select_related("warehouse").order_by("-shipped_at", "-pk")

    def item(row):
        country = row.site_code
        return dict(id=row.pk, site_code=country, warehouse=row.warehouse_id, warehouse_name=row.warehouse.name, document=row.document,
                    shipped_at_local=timezone.localtime(row.shipped_at, ZoneInfo(COUNTRY_ZONES[country])).isoformat(),
                    warehouse_sku=row.warehouse_sku, source_sku=row.source_sku, quantity=row.quantity)

    if params.get("export") == "csv":
        output = StringIO()
        writer = csv.writer(output)
        fields = ("site_code", "warehouse_name", "shipped_at_local", "document", "warehouse_sku", "source_sku", "quantity")
        writer.writerow(["国家", "仓库", "实际发货时间", "仓库单号", "仓库SKU", "来源SKU", "出库数量"])
        for row in rows.iterator(chunk_size=500):
            data = item(row)
            writer.writerow(["'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r", "\n"))
                             else value for value in (data[key] for key in fields)])
        response = HttpResponse("\ufeff" + output.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="outbound-movements.csv"'
        response["Cache-Control"] = "private, no-store"
        return response
    totals = rows.aggregate(quantity=Sum("quantity"), latest=Max("shipped_at"))
    return {"items": [item(row) for row in rows[(page - 1) * 20:page * 20]], "total": rows.count(),
            "quantity": totals["quantity"] or 0, "latest_at": totals["latest"],
            "coverage": _coverage(coverage_rows, "site_code", "shipped_at")}
