"""Read-only monthly ledger and permission-scoped missing-cost export."""
import csv
import io
from datetime import date
from django.db.models import Q
from django.db.models import Sum, Count
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from apps.common.responses import success_response
from apps.masterdata.models import WarehouseMaster
from apps.permissions.ui_p6_scopes import permission_scope_configs
from .permissions import IsProductCostViewer


def authorized_warehouses(user):
    configs = permission_scope_configs(user, "products.cost.view", {"warehouse_ids", "site_ids", "regions"},
        allowed_keys={"warehouse_ids", "site_ids", "regions"})
    warehouses = WarehouseMaster.objects.filter(tenant=user.tenant)
    if configs is None:
        return warehouses
    allowed = Q(pk__in=[])
    for config in configs:
        condition = Q()
        if "warehouse_ids" in config:
            condition &= Q(pk__in=config["warehouse_ids"])
        if "regions" in config:
            condition &= Q(country_code__in=config["regions"])
        if "site_ids" in config:
            from apps.masterdata.models import CountrySiteMaster
            codes = CountrySiteMaster.objects.filter(tenant=user.tenant, pk__in=config["site_ids"]).values("country_code")
            condition &= Q(country_code__in=codes)
        allowed |= condition
    return warehouses.filter(allowed)


def ledger_queryset(request):
    from .monthly_cost_models import MonthlyProductCost
    month = request.query_params.get("month", "")
    try:
        if len(month) != 7:
            raise ValueError()
        parsed = date.fromisoformat(month + "-01")
    except ValueError:
        raise ValidationError({"month": "Use YYYY-MM."})
    query = MonthlyProductCost.objects.filter(tenant=request.user.tenant, month=parsed,
        warehouse__in=authorized_warehouses(request.user)).select_related("sku", "warehouse")
    warehouse = request.query_params.get("warehouse_id")
    if warehouse:
        if not warehouse.isdigit():
            raise ValidationError({"warehouse_id": "Use a positive warehouse ID."})
        query = query.filter(warehouse_id=int(warehouse))
    return query


def serialize(record):
    def value(name, fallback=None):
        item = getattr(record, name, fallback)
        return str(item) if item is not None else None
    labels = {"estimated": "暂估", "pending_review": "待核验", "finalized": "已核定"}
    payment_states = {"confirmed": "已确认", "estimated": "暂估", "unknown": "未知"}
    watermark = record.watermark or {}
    return {"id": record.pk, "sku_code": record.sku.sku_code, "product_name": record.sku.product_name,
        "warehouse_name": record.warehouse.name, "country": record.warehouse.country_code,
        "month": record.month.isoformat()[:7], "opening_quantity": value("opening_quantity"),
        "opening_amount": value("opening_amount"), "receipt_quantity": value("receipt_quantity"),
        "receipt_amount": value("receipt_amount"), "outbound_quantity": value("outbound_quantity"),
        "closing_quantity": value("closing_quantity"), "closing_amount": value("closing_amount"),
        "sales_cost_amount": value("sales_cost_amount"),
        "historical_sold_adjustment": value("historical_sold_adjustment"),
        "other_in_quantity": value("other_in_quantity"), "other_in_amount": value("other_in_amount"),
        "other_out_quantity": value("other_out_quantity"),
        "unit_cost": value("unit_cost"), "status": record.status, "status_label": labels.get(record.status, record.status),
        "payment_status": payment_states.get(watermark.get("payment_state"), "未知"),
        "payment_estimate": watermark.get("payment_audit", {}).get("snapshot"),
        "reason": getattr(record, "missing_reason", ""), "version": record.version_no,
        "is_complete": record.is_complete}


@api_view(["GET"])
@permission_classes([IsProductCostViewer])
def monthly_cost_collection(request):
    query = ledger_queryset(request)
    try:
        page = max(1, int(request.query_params.get("page", 1)))
    except ValueError:
        raise ValidationError({"page": "Use an integer."})
    total = query.count()
    rows = query.order_by("sku_id", "warehouse_id")[(page-1)*50:page*50]
    warehouse = request.query_params.get("warehouse_id")
    from .monthly_cost_models import MonthlyCostAdjustment
    month = date.fromisoformat(request.query_params["month"] + "-01")
    adjustments = MonthlyCostAdjustment.objects.filter(tenant=request.user.tenant,
        effective_month=month,
        warehouse__in=authorized_warehouses(request.user))
    if warehouse:
        adjustments = adjustments.filter(warehouse_id=int(warehouse))
    allocated = adjustments.filter(status="allocated").aggregate(
        count=Count("pk"), inventory=Sum("inventory_amount"), sold=Sum("sold_amount"), delta=Sum("delta_amount"))
    pending = adjustments.exclude(status="allocated").aggregate(count=Count("pk"), delta=Sum("delta_amount"))
    return success_response({"items": [serialize(r) for r in rows], "total": total, "page": page,
        "historical_adjustments": {"allocated_count": allocated["count"],
            "inventory_amount": str(allocated["inventory"] or 0), "sold_amount": str(allocated["sold"] or 0),
            "delta_amount": str(allocated["delta"] or 0), "pending_count": pending["count"],
            "pending_delta_amount": str(pending["delta"] or 0), "warehouse_scope": "authorized; no store allocation"}})


@api_view(["GET"])
@permission_classes([IsProductCostViewer])
def monthly_cost_missing(request):
    query = ledger_queryset(request).filter(is_complete=False).order_by("sku_id", "warehouse_id")
    # Bound downloads; never silently truncate an apparently complete export.
    if query.count() > 20000:
        raise ValidationError("Please filter the export by warehouse (maximum 20,000 rows).")
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["国家", "仓库", "SKU", "商品名称", "月份", "月初数量", "出库数量", "缺失原因"])
    def safe(value):
        text = str(value or "")
        return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text
    count = 0
    for record in query.iterator(chunk_size=500):
        row = serialize(record)
        writer.writerow([safe(row[k]) for k in ("country", "warehouse_name", "sku_code", "product_name", "month", "opening_quantity", "outbound_quantity", "reason")])
        count += 1
    return success_response({"csv": output.getvalue(), "rows": count})


@api_view(["GET"])
@permission_classes([IsProductCostViewer])
def monthly_cost_warehouses(request):
    return success_response(list(authorized_warehouses(request.user).order_by("country_code", "pk").values("id", "name", "country_code")))
