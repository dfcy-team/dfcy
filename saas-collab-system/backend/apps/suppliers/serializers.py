from rest_framework import serializers

from .models import SupplierShipment, SupplierTask


class SupplierTaskSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)

    class Meta:
        model = SupplierTask
        fields = (
            "id",
            "tenant_id",
            "supplier_id",
            "task_no",
            "sku_code",
            "production_quantity",
            "completed_quantity",
            "expected_ship_date",
            "status",
            "is_overdue",
            "feedback_note",
            "exception_note",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "tenant_id",
            "supplier_id",
            "task_no",
            "sku_code",
            "production_quantity",
            "expected_ship_date",
            "is_overdue",
            "created_at",
            "updated_at",
        )


class SupplierTaskFeedbackSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupplierTask
        fields = ("completed_quantity", "status", "feedback_note", "exception_note")


class SupplierShipmentSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)

    class Meta:
        model = SupplierShipment
        fields = (
            "id",
            "tenant_id",
            "supplier_id",
            "shipment_no",
            "sku_code",
            "ship_quantity",
            "carton_count",
            "weight",
            "volume",
            "shipping_mark",
            "tracking_no",
            "attachment_placeholder",
            "status",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "tenant_id", "supplier_id", "status", "created_at", "updated_at")
