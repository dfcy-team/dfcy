"""Explicit sales/inventory read contracts. No task execution or source writes."""
from django.db.models import Count, F, Max, Min, Q, Subquery, Sum, Window
from django.db.models.functions import RowNumber

from apps.alerts.models import InventoryAlert
from apps.commerce.models import (
    InboundRecord, InventorySnapshot, RefundReturn, RefundReturnItem,
    SalesOrder, SalesOrderItem, ShipmentRecord,
)
from apps.influencers.models import SkuPriceSnapshot
from apps.replenishment.models import ReplenishmentRecommendation
from apps.reports.models import ReportExportRequest
from apps.sales_management.operating_models import OperatingOrder, OperatingOrderLine
from .models import APIDataQualityCheck, SyncRun


ORDER_FIELDS = ("id", "platform_id", "store_id", "external_order_id", "normalized_status", "business_date", "currency", "order_total_amount", "updated_at_utc", "region", "raw_status", "created_at_utc", "paid_at_utc", "delivered_at_utc", "cancelled_at_utc", "completed_at_utc", "subtotal_amount", "seller_discount_amount", "platform_discount_amount", "shipping_amount", "tax_amount")
RETURN_FIELDS = ("id", "platform_id", "store_id", "sales_order_id", "external_return_id", "normalized_status", "currency", "refund_amount", "updated_at", "external_refund_id", "case_type", "arbitration_status", "reason_code", "requested_at_utc", "updated_at_utc", "completed_at_utc", "refund_subtotal", "refund_shipping_fee", "refund_tax", "requires_physical_return", "is_partial_quantity_return", "is_refund_amount_adjusted")
STOCK_FIELDS = ("id", "site_code", "warehouse_id", "internal_sku_id", "source_sku", "available_qty", "reserved_qty", "snapshot_at_utc", "platform_product_id", "platform_variant_id", "seller_sku", "on_hand_qty", "in_transit_qty", "pending_putaway_qty", "defective_qty", "provided_quantity_fields")
LINE_FIELDS = ("id", "sales_order_id", "internal_spu_id", "internal_sku_id", "external_line_id", "platform_product_id", "platform_variant_id", "seller_sku", "item_name_snapshot", "variation_snapshot", "quantity", "original_unit_price", "sale_unit_price", "discount_amount", "tax_amount", "line_total_amount", "currency", "raw_line_status", "created_at", "updated_at")
DAILY_FIELDS = ("id", "platform_id", "store_id", "business_date", "currency", "order_count", "order_total_amount", "updated_at_utc")

CONTRACTS = {
    "sales_orders": (SalesOrder, ORDER_FIELDS),
    "sales_returns": (RefundReturn, RETURN_FIELDS),
    "inventory_snapshots": (InventorySnapshot, STOCK_FIELDS),
    "sales_order_items": (SalesOrderItem, LINE_FIELDS),
    "sales_return_items": (RefundReturnItem, ("id", "refund_return_id", "sales_order_item_id", "internal_sku_id", "external_return_item_id", "external_order_item_id", "platform_product_id", "platform_variant_id", "seller_sku", "item_name_snapshot", "quantity", "currency", "refund_amount", "created_at", "updated_at")),
    "operating_orders_v2": (OperatingOrder, ("id", "number", "country_id", "country_code_snapshot", "source_kind", "status", "order_date", "campaign", "demand_start", "demand_end", "plan_revision", "created_at", "updated_at", "version")),
    "operating_order_items": (OperatingOrderLine, ("id", "order_id", "sku_id", "sku_code_snapshot", "product_name_snapshot", "quantity", "is_active", "created_at", "updated_at", "version")),
    "sales_overview": (SalesOrder, DAILY_FIELDS),
    "store_sales": (SalesOrder, DAILY_FIELDS),
    "sku_sales": (SalesOrderItem, ("id", "platform_id", "store_id", "business_date", "internal_sku_id", "seller_sku", "currency", "quantity", "line_total_amount", "order_count", "updated_at")),
    "sales_exports": (ReportExportRequest, ("id", "report_type", "status", "row_count", "file_format", "expires_at", "requested_at", "finished_at")),
    "sales_data_quality": (APIDataQualityCheck, ("id", "sync_log_id", "check_type", "status", "platform", "sync_type", "sync_status", "started_at", "finished_at")),
    "sales_sync_runs": (SyncRun, ("id", "sync_job_id", "run_id", "status", "enqueued_at", "started_at", "finished_at", "fetched_count", "created_count", "updated_count", "skipped_count", "failed_count", "retry_count", "error_code")),
    "prices": (SkuPriceSnapshot, ("id", "listing_id", "store_id", "sku_id", "external_sku", "variant_id", "variant_name", "original_price", "promotion_price", "effective_price", "currency", "stock", "source", "source_updated_at", "imported_at")),
    "inventory_workbench": (InventorySnapshot, STOCK_FIELDS),
    "inventory_alerts": (InventoryAlert, ("id", "rule_id", "spu_id", "sku_id", "warehouse_code", "alert_type", "severity", "available_stock", "in_transit_stock", "average_daily_sales", "coverage_days", "threshold_value", "status", "due_date", "version", "triggered_at", "silenced_until", "closed_at", "created_at", "updated_at")),
    "replenishment_suggestions": (ReplenishmentRecommendation, ("id", "spu_id", "sku_id", "available_stock", "in_transit_stock", "average_daily_sales", "safety_stock_days", "supplier_lead_days", "replenishment_cycle_days", "suggested_quantity", "suggested_date", "confidence", "reason_code", "status", "formula_version", "reviewed_at", "created_at", "updated_at")),
    "inventory_inbounds": (InboundRecord, ("id", "site_code", "warehouse_id", "internal_sku_id", "external_inbound_id", "external_line_id", "inbound_type", "source_sku", "planned_quantity", "received_quantity", "status", "expected_at_utc", "received_at_utc", "updated_at_utc", "created_at", "updated_at")),
    "inventory_shipments": (ShipmentRecord, ("id", "platform_id", "store_id", "sales_order_id", "sales_order_item_id", "internal_sku_id", "external_shipment_id", "external_line_id", "shipment_type", "source_sku", "carrier_code", "quantity", "status", "shipped_at_utc", "delivered_at_utc", "updated_at_utc", "created_at", "updated_at")),
}


def related_scope(queryset, tenant_id, *paths):
    """Also reject malformed cross-tenant foreign keys, allowing NULL links."""
    for path in paths:
        queryset = queryset.filter(Q(**{f"{path}__isnull": True}) | Q(**{f"{path}__tenant_id": tenant_id}))
    return queryset


def _orders(tenant_id):
    return related_scope(SalesOrder.objects.filter(tenant_id=tenant_id), tenant_id,
                         "store", "platform", "authorization", "source_run", "source_run__sync_job")


def _lines(tenant_id):
    return related_scope(SalesOrderItem.objects.filter(sales_order__in=_orders(tenant_id)), tenant_id,
                         "internal_sku", "internal_spu", "internal_sku__spu")


def _returns(tenant_id):
    return related_scope(RefundReturn.objects.filter(tenant_id=tenant_id), tenant_id,
                         "store", "platform", "source_run", "source_run__sync_job", "sales_order",
                         "inbound_record", "shipment_record")


def query(resource, tenant_id):
    model, _ = CONTRACTS[resource]
    if resource in {"sales_orders", "sales_overview", "store_sales"}:
        qs = _orders(tenant_id)
        if resource != "sales_orders":
            # Group by currency and business date. Cursor is applied by the caller
            # to aggregate id (HAVING), never to input orders before summing.
            return qs.exclude(normalized_status="cancelled").order_by().values(
                "platform_id", "store_id", "business_date", "currency",
            ).annotate(id=Min("pk"), order_count=Count("pk"),
                       order_total_amount=Sum("order_total_amount"), updated_at_utc=Max("updated_at_utc"))
        return qs
    if resource == "sales_returns":
        return _returns(tenant_id)
    if resource in {"sales_order_items", "sku_sales"}:
        qs = _lines(tenant_id)
        if resource == "sku_sales":
            return qs.exclude(sales_order__normalized_status="cancelled").order_by().values(
                "internal_sku_id", "seller_sku", "currency",
                platform_id=F("sales_order__platform_id"), store_id=F("sales_order__store_id"),
                business_date=F("sales_order__business_date"),
            ).annotate(id=Min("pk"), quantity=Sum("quantity"), line_total_amount=Sum("line_total_amount"),
                       order_count=Count("sales_order_id", distinct=True), updated_at=Max("updated_at"))
        return qs
    if resource == "sales_return_items":
        qs = related_scope(RefundReturnItem.objects.filter(refund_return__in=_returns(tenant_id)), tenant_id,
                           "internal_sku", "internal_sku__spu", "sales_order_item__sales_order")
        return qs.filter(Q(sales_order_item__isnull=True) | Q(sales_order_item_id__in=_lines(tenant_id).values("pk")))
    qs = model.objects.filter(tenant_id=tenant_id)
    if resource == "operating_orders_v2":
        return related_scope(qs, tenant_id, "country")
    if resource == "operating_order_items":
        return related_scope(qs, tenant_id, "order", "order__country", "sku", "sku__spu")
    if resource == "sales_exports":
        return related_scope(qs.filter(report_type="sales_details"), tenant_id, "requested_by")
    if resource == "sales_data_quality":
        return related_scope(qs.filter(sync_log__task__sync_type__in=["orders", "sales_order", "refund_return", "sales_returns"]), tenant_id,
                             "sync_log", "sync_log__task").annotate(
            platform=F("sync_log__task__platform"), sync_type=F("sync_log__task__sync_type"),
            sync_status=F("sync_log__status"), started_at=F("sync_log__started_at"), finished_at=F("sync_log__finished_at"))
    if resource == "sales_sync_runs":
        return related_scope(qs.filter(sync_job__resource_type__in=["sales_order", "refund_return"]), tenant_id,
                             "sync_job", "sync_job__integration_config")
    if resource == "prices":
        return related_scope(qs, tenant_id, "listing", "listing__store", "listing__spu", "sku", "sku__spu").annotate(store_id=F("listing__store_id"))
    if resource in {"inventory_snapshots", "inventory_workbench", "inventory_inbounds", "inventory_shipments"}:
        qs = related_scope(qs, tenant_id, "warehouse" if resource != "inventory_shipments" else "store",
                           "internal_sku", "internal_sku__spu", "source_run", "source_run__sync_job")
        if resource == "inventory_workbench":
            # Latest snapshot per site/warehouse/source SKU, not all historical
            # snapshots added together. Rank before applying collection cursor.
            ids = qs.order_by().annotate(_rank=Window(
                RowNumber(), partition_by=[F("site_code"), F("warehouse_id"), F("source_sku")],
                order_by=[F("snapshot_at_utc").desc(), F("pk").desc()],
            )).filter(_rank=1).values("pk")
            return qs.filter(pk__in=Subquery(ids))
        if resource == "inventory_shipments":
            qs = related_scope(qs, tenant_id, "platform", "sales_order", "sales_order_item__sales_order")
        return qs
    if resource in {"inventory_alerts", "replenishment_suggestions"}:
        paths = ["sku", "spu", "sku__spu"]
        if resource == "inventory_alerts":
            paths.append("rule")
        return related_scope(qs, tenant_id, *paths)
    raise KeyError(resource)
