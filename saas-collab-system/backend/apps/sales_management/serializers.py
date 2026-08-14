from rest_framework import serializers

from .models import (
    DataQualityIssue,
    SalesExportRequest,
    SalesOrder,
    SalesOrderLine,
    SalesReturn,
    SKUSalesFact,
    StoreSalesFact,
    SyncRerunRequest,
    SyncSource,
)


def _mask_reference(value):
    value = str(value or "")
    if len(value) <= 6:
        return value
    return f"{value[:3]}…{value[-3:]}"


class SalesOrderLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = SalesOrderLine
        fields = (
            "id", "source_line_id", "spu", "sku", "product_name", "quantity", "unit_price",
            "discount_amount", "tax_amount", "shipping_amount", "source_updated_at",
        )


class SalesReturnSerializer(serializers.ModelSerializer):
    order_reference = serializers.SerializerMethodField()

    class Meta:
        model = SalesReturn
        fields = (
            "id", "source_return_id", "order_reference", "platform", "region", "store_id", "return_type",
            "status", "sku", "quantity", "requested_amount", "refunded_amount", "currency", "source_reason",
            "normalized_reason", "requested_at", "completed_at", "source_updated_at",
        )

    def get_order_reference(self, obj):
        return _mask_reference(obj.order.source_order_id)


class SalesOrderSerializer(serializers.ModelSerializer):
    order_reference = serializers.SerializerMethodField()
    item_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = SalesOrder
        fields = (
            "id", "platform", "region", "store_id", "order_reference", "system_order_no", "ordered_at",
            "order_status", "fulfillment_status", "refund_status", "item_count", "currency", "gross_amount",
            "net_amount", "buyer_region", "source_updated_at",
        )

    def get_order_reference(self, obj):
        return _mask_reference(obj.source_order_id)


class SalesOrderDetailSerializer(SalesOrderSerializer):
    lines = serializers.SerializerMethodField()
    returns = serializers.SerializerMethodField()

    class Meta(SalesOrderSerializer.Meta):
        fields = SalesOrderSerializer.Meta.fields + (
            "discount_amount", "tax_amount", "shipping_amount", "source_batch", "lines", "returns",
        )

    def get_lines(self, obj):
        return SalesOrderLineSerializer(obj.lines.filter(tenant=obj.tenant), many=True).data

    def get_returns(self, obj):
        from .scopes import filter_sales_queryset

        request = self.context["request"]
        returns = obj.returns.filter(
            tenant=obj.tenant,
            platform=obj.platform,
            region=obj.region,
            store_id=obj.store_id,
        )
        returns = filter_sales_queryset(request.user, "sales_management.orders.view", returns)
        return SalesReturnSerializer(returns, many=True).data


class StoreSalesFactSerializer(serializers.ModelSerializer):
    average_order_value = serializers.SerializerMethodField()
    refund_rate = serializers.SerializerMethodField()

    class Meta:
        model = StoreSalesFact
        fields = (
            "id", "platform", "region", "store_id", "period_start", "period_end", "currency", "gross_sales",
            "net_sales", "order_count", "units_sold", "average_order_value", "refund_amount", "refund_rate",
            "source_updated_at",
        )

    def get_average_order_value(self, obj):
        return str(obj.net_sales / obj.order_count) if obj.order_count else None

    def get_refund_rate(self, obj):
        return str(obj.refund_amount / obj.gross_sales) if obj.gross_sales else None


class SKUSalesFactSerializer(serializers.ModelSerializer):
    refund_rate = serializers.SerializerMethodField()

    class Meta:
        model = SKUSalesFact
        fields = (
            "id", "platform", "region", "store_id", "period_start", "period_end", "spu", "sku", "product_name",
            "category", "currency", "units_sold", "gross_sales", "net_sales", "order_count", "refund_units",
            "refund_rate", "last_sold_at", "inventory_risk", "inventory_source", "inventory_updated_at",
            "source_updated_at",
        )

    def get_refund_rate(self, obj):
        return str(obj.refund_units / obj.units_sold) if obj.units_sold else None


class SyncSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = SyncSource
        fields = (
            "id", "platform", "region", "store_id", "credential_mask", "credential_version",
            "authorization_status", "credential_expires_at", "run_status", "last_success_at", "last_run_at",
            "sync_cursor", "data_delay_seconds", "error_summary", "source_updated_at",
        )


class DataQualityIssueSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataQualityIssue
        fields = (
            "id", "issue_type", "severity", "status", "platform", "region", "store_id", "entity_type",
            "source_record_id", "message", "detected_at", "resolved_at",
        )


class SalesExportRequestSerializer(serializers.ModelSerializer):
    created_by = serializers.CharField(source="requested_by.username", read_only=True)

    class Meta:
        model = SalesExportRequest
        fields = (
            "id", "export_type", "filters", "data_scope", "created_by", "status", "record_count",
            "expires_at", "created_at", "completed_at",
        )


class SyncRerunRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = SyncRerunRequest
        fields = ("id", "sync_source_id", "reason", "status", "created_at")
