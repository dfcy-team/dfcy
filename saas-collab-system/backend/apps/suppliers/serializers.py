from rest_framework import serializers

from .models import SupplierPerformanceSnapshot, SupplierShipment, SupplierTask


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
        SupplierTask.Status.COMPLETED,
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

    def validate(self, attrs):
        status = attrs.get("status", self.instance.status)
        completed_quantity = attrs.get("completed_quantity", self.instance.completed_quantity)
        if status == SupplierTask.Status.COMPLETED and completed_quantity != self.instance.production_quantity:
            raise serializers.ValidationError(
                {"completed_quantity": "Completed quantity must equal production quantity when status is completed."}
            )
        return attrs


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


class SupplierPerformanceSnapshotSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)

    class Meta:
        model = SupplierPerformanceSnapshot
        fields = (
            "id",
            "tenant_id",
            "supplier_id",
            "period_start",
            "period_end",
            "total_tasks",
            "on_time_tasks",
            "overdue_tasks",
            "exception_tasks",
            "total_shipments",
            "accurate_shipments",
            "feedback_on_time_count",
            "on_time_rate",
            "overdue_rate",
            "exception_rate",
            "shipment_accuracy_rate",
            "feedback_timeliness_rate",
            "total_score",
            "calculated_at",
        )
        read_only_fields = fields


class SupplierPerformanceCalculationSerializer(serializers.Serializer):
    supplier_id = serializers.IntegerField(min_value=1)
    period_start = serializers.DateField()
    period_end = serializers.DateField()

    def validate(self, attrs):
        if attrs["period_start"] > attrs["period_end"]:
            raise serializers.ValidationError("period_start must not be after period_end")
        return attrs
