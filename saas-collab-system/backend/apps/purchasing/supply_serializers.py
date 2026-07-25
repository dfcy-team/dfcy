from django.db import transaction
from rest_framework import serializers

from apps.masterdata.models import SupplierMaster
from apps.products.models import ProductSKU

from .models import (
    SupplyProductionProgress,
    SupplyPurchaseOrder,
    SupplyPurchaseOrderEvent,
    SupplyPurchaseOrderLine,
)


class SupplyPurchaseOrderLineSerializer(serializers.ModelSerializer):
    sku_id = serializers.IntegerField(source="sku.id", read_only=True)

    class Meta:
        model = SupplyPurchaseOrderLine
        fields = (
            "id",
            "line_no",
            "sku_id",
            "sku_code_snapshot",
            "product_name_snapshot",
            "quantity",
            "unit_price",
            "expected_delivery_date",
            "source_record_id",
        )


class SupplierSupplyPurchaseOrderLineSerializer(serializers.ModelSerializer):
    sku_id = serializers.IntegerField(source="sku.id", read_only=True)

    class Meta:
        model = SupplyPurchaseOrderLine
        fields = (
            "id",
            "line_no",
            "sku_id",
            "sku_code_snapshot",
            "product_name_snapshot",
            "quantity",
            "expected_delivery_date",
        )


class SupplyProductionProgressSerializer(serializers.ModelSerializer):
    actor_id = serializers.IntegerField(source="actor.id", read_only=True)

    class Meta:
        model = SupplyProductionProgress
        fields = (
            "id",
            "completed_quantity",
            "progress_percent",
            "note",
            "actor_id",
            "request_id",
            "created_at",
        )


class SupplierSupplyProductionProgressSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupplyProductionProgress
        fields = (
            "id",
            "completed_quantity",
            "progress_percent",
            "note",
            "created_at",
        )


class SupplyPurchaseOrderEventSerializer(serializers.ModelSerializer):
    actor_id = serializers.IntegerField(source="actor.id", read_only=True)

    class Meta:
        model = SupplyPurchaseOrderEvent
        fields = (
            "id",
            "action",
            "actor_id",
            "actor_type",
            "before_status",
            "after_status",
            "payload",
            "created_at",
        )


class SupplyPurchaseOrderSummarySerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    supplier_id = serializers.IntegerField(source="supplier.id", read_only=True)
    supplier_code = serializers.CharField(source="supplier.code", read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    total_quantity = serializers.SerializerMethodField()
    line_count = serializers.SerializerMethodField()

    class Meta:
        model = SupplyPurchaseOrder
        fields = (
            "id",
            "tenant_id",
            "order_no",
            "supplier_id",
            "supplier_code",
            "supplier_name",
            "order_date",
            "expected_delivery_date",
            "currency",
            "status",
            "total_quantity",
            "completed_quantity",
            "line_count",
            "version",
            "created_at",
            "updated_at",
        )

    def get_total_quantity(self, obj):
        return sum(line.quantity for line in obj.lines.all())

    def get_line_count(self, obj):
        return len(obj.lines.all())


class SupplyPurchaseOrderDetailSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    supplier_id = serializers.IntegerField(source="supplier.id", read_only=True)
    supplier_code = serializers.CharField(source="supplier.code", read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    created_by_id = serializers.IntegerField(source="created_by.id", read_only=True)
    total_quantity = serializers.SerializerMethodField()
    lines = SupplyPurchaseOrderLineSerializer(many=True, read_only=True)
    progress_entries = SupplyProductionProgressSerializer(many=True, read_only=True)
    events = SupplyPurchaseOrderEventSerializer(many=True, read_only=True)

    class Meta:
        model = SupplyPurchaseOrder
        fields = (
            "id",
            "tenant_id",
            "order_no",
            "supplier_id",
            "supplier_code",
            "supplier_name",
            "order_date",
            "expected_delivery_date",
            "currency",
            "notes",
            "status",
            "total_quantity",
            "completed_quantity",
            "version",
            "source_system",
            "source_table",
            "source_record_id",
            "source_updated_at",
            "source_payload_hash",
            "accepted_at",
            "production_started_at",
            "production_completed_at",
            "created_by_id",
            "created_at",
            "updated_at",
            "lines",
            "progress_entries",
            "events",
        )

    def get_total_quantity(self, obj):
        return sum(line.quantity for line in obj.lines.all())


class SupplierSupplyPurchaseOrderSerializer(serializers.ModelSerializer):
    supplier_id = serializers.IntegerField(source="supplier.id", read_only=True)
    supplier_code = serializers.CharField(source="supplier.code", read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    total_quantity = serializers.SerializerMethodField()
    lines = SupplierSupplyPurchaseOrderLineSerializer(many=True, read_only=True)
    progress_entries = SupplierSupplyProductionProgressSerializer(many=True, read_only=True)

    class Meta:
        model = SupplyPurchaseOrder
        fields = (
            "id",
            "order_no",
            "supplier_id",
            "supplier_code",
            "supplier_name",
            "order_date",
            "expected_delivery_date",
            "status",
            "total_quantity",
            "completed_quantity",
            "version",
            "accepted_at",
            "production_started_at",
            "production_completed_at",
            "created_at",
            "updated_at",
            "lines",
            "progress_entries",
        )

    def get_total_quantity(self, obj):
        return sum(line.quantity for line in obj.lines.all())


class SupplyPurchaseOrderLineCreateSerializer(serializers.Serializer):
    line_no = serializers.IntegerField(min_value=1)
    sku_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1)
    unit_price = serializers.DecimalField(max_digits=14, decimal_places=4, min_value=0)
    expected_delivery_date = serializers.DateField(required=False, allow_null=True)
    source_record_id = serializers.CharField(max_length=128, required=False, allow_null=True, allow_blank=False)


class SupplyPurchaseOrderCreateSerializer(serializers.Serializer):
    order_no = serializers.CharField(max_length=80)
    supplier_id = serializers.IntegerField(min_value=1)
    order_date = serializers.DateField()
    expected_delivery_date = serializers.DateField(required=False, allow_null=True)
    currency = serializers.CharField(max_length=8, default="CNY")
    notes = serializers.CharField(required=False, allow_blank=True)
    source_system = serializers.CharField(max_length=80, required=False, allow_null=True, allow_blank=False)
    source_table = serializers.CharField(max_length=80, required=False, allow_null=True, allow_blank=False)
    source_record_id = serializers.CharField(max_length=128, required=False, allow_null=True, allow_blank=False)
    source_updated_at = serializers.DateTimeField(required=False, allow_null=True)
    source_payload_hash = serializers.RegexField(
        r"^[0-9a-fA-F]{64}$",
        required=False,
        allow_blank=True,
    )
    lines = SupplyPurchaseOrderLineCreateSerializer(many=True, allow_empty=False)

    def validate(self, attrs):
        request = self.context["request"]
        tenant = request.user.tenant
        supplier = SupplierMaster.objects.filter(
            pk=attrs["supplier_id"],
            tenant=tenant,
        ).first()
        if supplier is None:
            raise serializers.ValidationError({"supplier_id": "Supplier is not available in the current tenant."})
        if SupplyPurchaseOrder.objects.filter(
            tenant=tenant,
            order_no=attrs["order_no"],
        ).exists():
            raise serializers.ValidationError(
                {"order_no": "A supply purchase order with this number already exists in the tenant."}
            )

        line_numbers = [line["line_no"] for line in attrs["lines"]]
        if len(line_numbers) != len(set(line_numbers)):
            raise serializers.ValidationError({"lines": "Line numbers must be unique within an order."})

        sku_ids = {line["sku_id"] for line in attrs["lines"]}
        skus = {
            sku.id: sku
            for sku in ProductSKU.objects.select_related("spu").filter(
                tenant=tenant,
                id__in=sku_ids,
            )
        }
        missing_sku_ids = sorted(sku_ids - set(skus))
        if missing_sku_ids:
            raise serializers.ValidationError(
                {"lines": f"SKU IDs are not available in the current tenant: {missing_sku_ids}"}
            )

        source_values = (
            attrs.get("source_system"),
            attrs.get("source_table"),
            attrs.get("source_record_id"),
        )
        if any(source_values) and not all(source_values):
            raise serializers.ValidationError(
                {"source_record_id": "Source system, table, and record ID must be provided together."}
            )
        attrs["_supplier"] = supplier
        attrs["_skus"] = skus
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        request = self.context["request"]
        lines = validated_data.pop("lines")
        supplier = validated_data.pop("_supplier")
        skus = validated_data.pop("_skus")
        validated_data.pop("supplier_id")
        order = SupplyPurchaseOrder.objects.create(
            tenant=request.user.tenant,
            supplier=supplier,
            created_by=request.user,
            currency=validated_data.pop("currency").upper(),
            **validated_data,
        )
        for line in lines:
            sku = skus[line.pop("sku_id")]
            SupplyPurchaseOrderLine.objects.create(
                tenant=request.user.tenant,
                order=order,
                sku=sku,
                sku_code_snapshot=sku.sku_code,
                product_name_snapshot=sku.spu.product_name,
                **line,
            )
        return order


class SupplyOrderProgressActionSerializer(serializers.Serializer):
    completed_quantity = serializers.IntegerField(min_value=0)
    note = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class EmptySupplyOrderActionSerializer(serializers.Serializer):
    pass
