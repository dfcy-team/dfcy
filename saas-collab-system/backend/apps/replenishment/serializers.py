from rest_framework import serializers

from .models import ReplenishmentRecommendation


class ReplenishmentRecommendationSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    reviewed_by_id = serializers.IntegerField(source="reviewed_by.id", read_only=True)

    class Meta:
        model = ReplenishmentRecommendation
        fields = (
            "id", "tenant_id", "spu", "sku", "available_stock", "in_transit_stock",
            "average_daily_sales", "safety_stock_days", "supplier_lead_days",
            "replenishment_cycle_days", "suggested_quantity", "suggested_date", "confidence",
            "reason_code", "reason_detail", "status", "reviewed_by_id", "reviewed_at",
            "review_reason", "source_summary", "formula_version", "created_at", "updated_at",
        )
        read_only_fields = fields


class ReplenishmentEvaluationSerializer(serializers.Serializer):
    sku_id = serializers.IntegerField(min_value=1, required=False)
    spu_id = serializers.IntegerField(min_value=1, required=False)
    available_stock = serializers.DecimalField(max_digits=16, decimal_places=4, min_value=0)
    in_transit_stock = serializers.DecimalField(max_digits=16, decimal_places=4, min_value=0)
    average_daily_sales = serializers.DecimalField(max_digits=16, decimal_places=4, min_value=0, allow_null=True)
    safety_stock_days = serializers.IntegerField(min_value=0)
    supplier_lead_days = serializers.IntegerField(min_value=0)
    replenishment_cycle_days = serializers.IntegerField(min_value=0)

    def validate(self, attrs):
        if not attrs.get("sku_id") and not attrs.get("spu_id"):
            raise serializers.ValidationError("sku_id or spu_id is required.")
        return attrs


class ReplenishmentReviewSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=1000, trim_whitespace=True)


class ReplenishmentQuerySerializer(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=50)
    status = serializers.ChoiceField(choices=ReplenishmentRecommendation.Status.choices, required=False)
