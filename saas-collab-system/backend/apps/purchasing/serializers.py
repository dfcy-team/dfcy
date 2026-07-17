from rest_framework import serializers

from .models import PurchaseOrder


class PurchaseOrderSerializer(serializers.ModelSerializer):
    CONTROLLED_UPDATE_FIELDS = {"status", "approval_status"}

    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    created_by_id = serializers.IntegerField(source="created_by.id", read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = (
            "id",
            "tenant_id",
            "po_no",
            "sku_code",
            "supplier_id",
            "quantity",
            "unit_price",
            "delivery_date",
            "payment_terms",
            "status",
            "approval_status",
            "created_by_id",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "tenant_id",
            "status",
            "approval_status",
            "created_by_id",
            "created_at",
            "updated_at",
        )

    def validate(self, attrs):
        if self.instance is not None:
            attempted = self.CONTROLLED_UPDATE_FIELDS.intersection(self.initial_data)
            if attempted:
                raise serializers.ValidationError(
                    {field: "This status can only be changed through an authorized workflow action." for field in attempted}
                )
        return attrs
