from rest_framework import serializers

from .adapters import MAX_BATCH_RECORDS, MAX_ORDER_LINES, NORMALIZED_CONTRACT_VERSION
from .models import (
    MarketplaceImportBatch,
    MarketplaceInventorySnapshot,
    MarketplaceOrder,
    MarketplaceRefund,
)


ALLOWED_CURRENCIES = {"PHP", "THB", "MYR"}


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        unknown = set(data) - set(self.fields) if isinstance(data, dict) else set()
        if unknown:
            raise serializers.ValidationError(
                {"unknown_fields": f"Unsupported fields: {', '.join(sorted(unknown))}."}
            )
        return super().to_internal_value(data)


class CurrencyField(serializers.CharField):
    def __init__(self, **kwargs):
        super().__init__(min_length=3, max_length=3, **kwargs)

    def to_internal_value(self, data):
        value = super().to_internal_value(data).upper()
        if value not in ALLOWED_CURRENCIES:
            self.fail("invalid")
        return value


class OrderLineSerializer(StrictSerializer):
    platform_line_id = serializers.CharField(min_length=1, max_length=160)
    platform_variant_id = serializers.CharField(min_length=1, max_length=160)
    platform_sku = serializers.CharField(max_length=160, allow_blank=True, required=False, default="")
    quantity = serializers.IntegerField(min_value=1, max_value=2_147_483_647)
    unit_price = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=0)
    line_amount = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=0)


class RefundInputSerializer(StrictSerializer):
    platform_refund_id = serializers.CharField(min_length=1, max_length=160)
    status = serializers.ChoiceField(choices=MarketplaceRefund.Status.choices)
    currency = CurrencyField()
    amount = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=0)
    reason_code = serializers.CharField(max_length=80, allow_blank=True, required=False, default="")
    platform_updated_at = serializers.DateTimeField()


class OrderInputSerializer(StrictSerializer):
    platform_order_id = serializers.CharField(min_length=1, max_length=160)
    status = serializers.ChoiceField(choices=MarketplaceOrder.Status.choices)
    currency = CurrencyField()
    total_amount = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=0)
    ordered_at = serializers.DateTimeField()
    platform_updated_at = serializers.DateTimeField()
    cancelled_at = serializers.DateTimeField(allow_null=True, required=False, default=None)
    line_items = OrderLineSerializer(many=True, allow_empty=False)
    refunds = RefundInputSerializer(many=True, required=False, default=list)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if len(attrs["line_items"]) > MAX_ORDER_LINES:
            raise serializers.ValidationError({"line_items": "Order line limit exceeded."})
        line_ids = [item["platform_line_id"] for item in attrs["line_items"]]
        if len(line_ids) != len(set(line_ids)):
            raise serializers.ValidationError({"line_items": "platform_line_id must be unique per order."})
        refund_ids = [item["platform_refund_id"] for item in attrs["refunds"]]
        if len(refund_ids) != len(set(refund_ids)):
            raise serializers.ValidationError({"refunds": "platform_refund_id must be unique per order."})
        if attrs["status"] == MarketplaceOrder.Status.CANCELLED and not attrs.get("cancelled_at"):
            raise serializers.ValidationError({"cancelled_at": "Cancelled orders require cancelled_at."})
        if attrs["status"] != MarketplaceOrder.Status.CANCELLED and attrs.get("cancelled_at"):
            raise serializers.ValidationError({"cancelled_at": "Only cancelled orders may provide cancelled_at."})
        return attrs


class InventoryInputSerializer(StrictSerializer):
    platform_variant_id = serializers.CharField(min_length=1, max_length=160)
    platform_sku = serializers.CharField(max_length=160, allow_blank=True, required=False, default="")
    on_hand = serializers.IntegerField(min_value=0, max_value=2_147_483_647)
    reserved = serializers.IntegerField(min_value=0, max_value=2_147_483_647)
    available = serializers.IntegerField(min_value=0, max_value=2_147_483_647)
    incoming = serializers.IntegerField(min_value=0, max_value=2_147_483_647)
    observed_at = serializers.DateTimeField()


class ImportRequestSerializer(StrictSerializer):
    store_mapping_id = serializers.IntegerField(min_value=1)
    resource_type = serializers.ChoiceField(choices=("orders", "inventory"))
    import_mode = serializers.ChoiceField(choices=MarketplaceImportBatch.Mode.choices)
    source_mode = serializers.ChoiceField(choices=(MarketplaceImportBatch.SourceMode.SYNTHETIC_CONTRACT,))
    idempotency_key = serializers.CharField(min_length=8, max_length=160, trim_whitespace=False)
    cursor_before = serializers.CharField(max_length=500, allow_blank=True)
    cursor_after = serializers.CharField(min_length=1, max_length=500)
    watermark_after = serializers.DateTimeField()
    contract_version = serializers.CharField(max_length=40)
    orders = OrderInputSerializer(many=True, required=False)
    inventory = InventoryInputSerializer(many=True, required=False)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs["contract_version"] != NORMALIZED_CONTRACT_VERSION:
            raise serializers.ValidationError({"contract_version": "Unsupported normalized contract version."})
        resource = attrs["resource_type"]
        expected = "orders" if resource == "orders" else "inventory"
        unexpected = "inventory" if expected == "orders" else "orders"
        if expected not in attrs:
            raise serializers.ValidationError({expected: "This record collection is required."})
        if unexpected in attrs:
            raise serializers.ValidationError({unexpected: "This collection does not match resource_type."})
        if not attrs[expected]:
            raise serializers.ValidationError({expected: "At least one record is required."})
        if len(attrs[expected]) > MAX_BATCH_RECORDS:
            raise serializers.ValidationError({expected: "Batch record limit exceeded."})
        identities = [
            item["platform_order_id"] if expected == "orders" else (item["platform_variant_id"], item["observed_at"])
            for item in attrs[expected]
        ]
        if len(identities) != len(set(identities)):
            raise serializers.ValidationError({expected: "Duplicate record identity in one batch."})
        return attrs


class MarketplaceImportBatchSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(read_only=True)
    store_mapping_id = serializers.IntegerField(read_only=True)
    created_by_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = MarketplaceImportBatch
        fields = (
            "id", "tenant_id", "store_mapping_id", "platform", "resource_type", "import_mode", "source_mode",
            "contract_version", "status", "cursor_before", "cursor_after", "watermark_before",
            "watermark_after", "received_count", "created_count", "updated_count", "skipped_count",
            "controlled_error_code", "created_by_id", "created_at", "completed_at",
        )


class MarketplaceRefundSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarketplaceRefund
        exclude = ("fingerprint", "tenant", "order", "last_batch")


class MarketplaceOrderSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(read_only=True)
    store_mapping_id = serializers.IntegerField(read_only=True)
    last_batch_id = serializers.IntegerField(read_only=True)
    refunds = MarketplaceRefundSerializer(many=True, read_only=True)

    class Meta:
        model = MarketplaceOrder
        fields = (
            "id", "tenant_id", "store_mapping_id", "platform_order_id", "status", "currency",
            "total_amount", "ordered_at", "platform_updated_at", "cancelled_at", "line_items",
            "refunds", "last_batch_id", "created_at", "updated_at",
        )


class MarketplaceInventorySnapshotSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(read_only=True)
    store_mapping_id = serializers.IntegerField(read_only=True)
    product_mapping_id = serializers.IntegerField(read_only=True)
    last_batch_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = MarketplaceInventorySnapshot
        fields = (
            "id", "tenant_id", "store_mapping_id", "product_mapping_id", "mapping_status", "platform_variant_id",
            "platform_sku", "on_hand", "reserved", "available", "incoming", "observed_at",
            "last_batch_id", "created_at",
        )
