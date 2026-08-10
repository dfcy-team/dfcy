from rest_framework import serializers

from .models import (
    DevelopmentCostEstimate,
    DevelopmentProject,
    DevelopmentRequirementCompetitorLink,
    ProductSalesSummary,
)


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


class CompetitorReportSelectionSerializer(serializers.Serializer):
    """Only operator decisions are accepted when creating a report link."""

    relation_type = serializers.ChoiceField(
        choices=DevelopmentRequirementCompetitorLink.RelationType.choices,
        required=False,
        default=DevelopmentRequirementCompetitorLink.RelationType.REFERENCE,
    )
    is_primary = serializers.BooleanField(required=False, default=False)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=5000, default="")
    selected_strengths = serializers.ListField(
        child=serializers.CharField(max_length=4000), required=False, default=list, max_length=100
    )
    selected_pain_points = serializers.ListField(
        child=serializers.CharField(max_length=4000), required=False, default=list, max_length=100
    )
    selected_recommendations = serializers.ListField(
        child=serializers.CharField(max_length=4000), required=False, default=list, max_length=100
    )
    evidence_ids = serializers.ListField(
        child=serializers.CharField(max_length=160), required=False, default=list, max_length=100
    )
    operator_conclusion = serializers.CharField(
        required=False, allow_blank=True, max_length=10000, default=""
    )
    excluded_items = serializers.ListField(
        child=serializers.JSONField(), required=False, default=list
    )

    def validate_excluded_items(self, value):
        if len(value) > 100:
            raise serializers.ValidationError("No more than 100 excluded items may be submitted.")
        for item in value:
            if not isinstance(item, dict):
                raise serializers.ValidationError("Each excluded item must be an object.")
            if not str(item.get("reason", "")).strip():
                raise serializers.ValidationError("Each excluded item requires a reason.")
            if len(str(item.get("item", ""))) > 4000 or len(str(item.get("reason", ""))) > 2000:
                raise serializers.ValidationError("Excluded item content is too long.")
        return value

    def validate(self, attrs):
        for field in (
            "selected_strengths",
            "selected_pain_points",
            "selected_recommendations",
            "evidence_ids",
        ):
            # Normalize whitespace and remove accidental duplicates while
            # preserving the operator's chosen order in the audit snapshot.
            values = []
            for item in attrs.get(field, []):
                item = item.strip()
                if item and item not in values:
                    values.append(item)
            attrs[field] = values
        return attrs


class DevelopmentRequirementCompetitorLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = DevelopmentRequirementCompetitorLink
        fields = "__all__"
        read_only_fields = (
            "tenant",
            "requirement",
            "external_report_id",
            "task_id",
            "platform",
            "site",
            "product_id",
            "product_title",
            "report_completed_at",
            "data_updated_at",
            "decision_snapshot",
            "created_by",
            "created_at",
            "updated_at",
        )
