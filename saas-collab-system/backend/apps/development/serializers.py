from rest_framework import serializers

from .models import DevelopmentCostEstimate, DevelopmentProject, ProductSalesSummary


class DevelopmentProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = DevelopmentProject
        fields = "__all__"
        read_only_fields = ("tenant", "created_by", "stage", "finalized_product", "created_at", "updated_at")

    def validate(self, attrs):
        request = self.context["request"]
        for field in ("requirement", "supplier", "assigned_to"):
            value = attrs.get(field)
            if value is not None and value.tenant_id != request.user.tenant_id:
                raise serializers.ValidationError({field: "Referenced record must belong to the current tenant."})
        return attrs


class DevelopmentCostEstimateSerializer(serializers.ModelSerializer):
    class Meta:
        model = DevelopmentCostEstimate
        fields = "__all__"
        read_only_fields = ("total_cost", "estimated_margin", "estimated_margin_rate", "status", "approved_by", "created_at")


class ProductSalesSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductSalesSummary
        fields = "__all__"
