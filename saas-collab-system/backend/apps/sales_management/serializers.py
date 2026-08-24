from decimal import Decimal

from rest_framework import serializers

from apps.commerce.models import InventorySnapshot, RefundReturn, RefundReturnItem, SalesOrder, SalesOrderItem
from apps.integrations.models import APIDataQualityCheck, SyncJob, SyncRun
from apps.reports.models import ReportExportRequest


def _decimal_4(value):
    return f"{Decimal(value or 0):.4f}"


def _store_data(store):
    return {
        "id": store.id,
        "code": store.code,
        "name": store.name,
        "region": store.country_code,
        "timezone": store.timezone,
    }


class SalesOrderLineSerializer(serializers.ModelSerializer):
    internal_spu = serializers.SerializerMethodField()
    internal_sku = serializers.SerializerMethodField()

    class Meta:
        model = SalesOrderItem
        fields = (
            "id",
            "external_line_id",
            "platform_product_id",
            "platform_variant_id",
            "seller_sku",
            "internal_spu",
            "internal_sku",
            "item_name_snapshot",
            "variation_snapshot",
            "quantity",
            "original_unit_price",
            "sale_unit_price",
            "discount_amount",
            "tax_amount",
            "line_total_amount",
            "currency",
            "raw_line_status",
        )

    def get_internal_spu(self, obj):
        return obj.internal_spu.spu_code if obj.internal_spu_id else None

    def get_internal_sku(self, obj):
        return obj.internal_sku.sku_code if obj.internal_sku_id else None


class RefundReturnItemSerializer(serializers.ModelSerializer):
    sales_order_item_id = serializers.IntegerField(read_only=True)
    internal_sku = serializers.SerializerMethodField()

    class Meta:
        model = RefundReturnItem
        fields = (
            "id",
            "sales_order_item_id",
            "internal_sku",
            "external_return_item_id",
            "external_order_item_id",
            "platform_product_id",
            "platform_variant_id",
            "seller_sku",
            "item_name_snapshot",
            "quantity",
            "currency",
            "refund_amount",
        )

    def get_internal_sku(self, obj):
        return obj.internal_sku.sku_code if obj.internal_sku_id else None


class SalesReturnSerializer(serializers.ModelSerializer):
    platform = serializers.CharField(source="platform.platform_type")
    store = serializers.SerializerMethodField()
    sales_order_id = serializers.IntegerField(read_only=True)
    external_order_id = serializers.SerializerMethodField()
    items = RefundReturnItemSerializer(many=True, read_only=True)

    class Meta:
        model = RefundReturn
        fields = (
            "id",
            "external_return_id",
            "external_refund_id",
            "sales_order_id",
            "external_order_id",
            "platform",
            "store",
            "case_type",
            "raw_status",
            "normalized_status",
            "arbitration_status",
            "reason_code",
            "requested_at_utc",
            "updated_at_utc",
            "completed_at_utc",
            "currency",
            "refund_amount",
            "refund_subtotal",
            "refund_shipping_fee",
            "refund_tax",
            "requires_physical_return",
            "is_partial_quantity_return",
            "is_refund_amount_adjusted",
            "items",
        )

    def get_store(self, obj):
        return _store_data(obj.store)

    def get_external_order_id(self, obj):
        return obj.sales_order.external_order_id if obj.sales_order_id else None


class SalesOrderSerializer(serializers.ModelSerializer):
    platform = serializers.CharField(source="platform.platform_type")
    store = serializers.SerializerMethodField()
    item_count = serializers.IntegerField(read_only=True)
    refund_summary = serializers.SerializerMethodField()

    class Meta:
        model = SalesOrder
        fields = (
            "id",
            "external_order_id",
            "platform",
            "store",
            "raw_status",
            "normalized_status",
            "created_at_utc",
            "updated_at_utc",
            "currency",
            "order_total_amount",
            "item_count",
            "refund_summary",
        )

    def get_store(self, obj):
        return _store_data(obj.store)

    def get_refund_summary(self, obj):
        refunds = list(obj.refund_returns.all())
        latest = max(refunds, key=lambda row: (row.updated_at_utc, row.id), default=None)
        return {
            "has_refund_return": bool(refunds),
            "case_count": len(refunds),
            "refund_amount": _decimal_4(sum((row.refund_amount for row in refunds), Decimal("0"))),
            "latest_status": latest.normalized_status if latest else None,
            "is_partial_quantity_return": any(row.is_partial_quantity_return is True for row in refunds),
            "is_refund_amount_adjusted": any(row.is_refund_amount_adjusted is True for row in refunds),
        }


class SalesOrderDetailSerializer(SalesOrderSerializer):
    items = SalesOrderLineSerializer(many=True, read_only=True)
    refund_returns = SalesReturnSerializer(many=True, read_only=True)

    class Meta(SalesOrderSerializer.Meta):
        fields = SalesOrderSerializer.Meta.fields + (
            "seller_discount_amount",
            "platform_discount_amount",
            "tax_amount",
            "shipping_amount",
            "status_mapping_version",
            "items",
            "refund_returns",
        )


class InventorySnapshotSerializer(serializers.ModelSerializer):
    warehouse_id = serializers.IntegerField()
    internal_sku = serializers.SerializerMethodField()

    class Meta:
        model = InventorySnapshot
        fields = (
            "id",
            "site_code",
            "warehouse_id",
            "internal_sku",
            "source_sku",
            "platform_product_id",
            "platform_variant_id",
            "seller_sku",
            "on_hand_qty",
            "available_qty",
            "reserved_qty",
            "in_transit_qty",
            "pending_putaway_qty",
            "defective_qty",
            "snapshot_at_utc",
        )

    def get_internal_sku(self, obj):
        return obj.internal_sku.sku_code if obj.internal_sku_id else None


class DataQualityIssueSerializer(serializers.ModelSerializer):
    issue_type = serializers.CharField(source="check_type")
    severity = serializers.SerializerMethodField()
    platform = serializers.CharField(source="sync_log.task.platform")
    region = serializers.SerializerMethodField()
    store_id = serializers.SerializerMethodField()
    detected_at = serializers.DateTimeField(source="sync_log.finished_at")

    class Meta:
        model = APIDataQualityCheck
        fields = ("id", "issue_type", "severity", "status", "platform", "region", "store_id", "message", "detected_at")

    def get_severity(self, obj):
        return "high" if obj.status == APIDataQualityCheck.Status.FAILED else "medium"

    def get_region(self, obj):
        return ""

    def get_store_id(self, obj):
        config = obj.sync_log.task.config if isinstance(obj.sync_log.task.config, dict) else {}
        return str(config.get("store_id") or config.get("store_code") or "")


class SyncSourceSerializer(serializers.ModelSerializer):
    platform = serializers.CharField(source="integration_config.platform")
    region = serializers.SerializerMethodField()
    store_id = serializers.CharField(source="integration_config.account_alias")
    run_status = serializers.CharField(source="status")
    last_success_at = serializers.SerializerMethodField()
    last_run_at = serializers.DateTimeField()
    sync_cursor = serializers.SerializerMethodField()
    error_summary = serializers.SerializerMethodField()

    class Meta:
        model = SyncJob
        fields = ("id", "platform", "region", "store_id", "run_status", "last_success_at", "last_run_at", "sync_cursor", "error_summary")

    def get_region(self, obj):
        return ""

    def get_last_success_at(self, obj):
        run = obj.runs.filter(status=SyncRun.Status.SUCCESS).order_by("-finished_at").first()
        return run.finished_at if run else None

    def get_sync_cursor(self, obj):
        cursor = obj.cursors.order_by("cursor_key").first()
        return cursor.cursor_value if cursor else ""

    def get_error_summary(self, obj):
        run = obj.runs.exclude(error_code="").order_by("-started_at").first()
        return run.error_code if run else ""


class SalesExportRequestSerializer(serializers.ModelSerializer):
    export_type = serializers.CharField(source="report_type")
    created_by = serializers.CharField(source="requested_by.username")
    status = serializers.CharField()
    record_count = serializers.IntegerField(source="row_count")
    created_at = serializers.DateTimeField(source="requested_at")
    completed_at = serializers.DateTimeField(source="finished_at")

    class Meta:
        model = ReportExportRequest
        fields = ("id", "export_type", "filters", "data_scope", "created_by", "status", "record_count", "created_at", "completed_at")
