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
    ALLOWED_SUPPLIER_STATUSES = {
        SupplierTask.Status.IN_PROGRESS,
        SupplierTask.Status.PARTIAL,
        SupplierTask.Status.EXCEPTION,
    }

    class Meta:
        model = SupplierTask
        fields = ("completed_quantity", "status", "feedback_note", "exception_note")

    def validate_status(self, value):
        if value not in self.ALLOWED_SUPPLIER_STATUSES:
            raise serializers.ValidationError("Supplier feedback status is not allowed.")
        return value

    def validate_completed_quantity(self, value):
        if value > self.instance.production_quantity:
            raise serializers.ValidationError("Completed quantity cannot exceed production quantity.")
        return value


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
