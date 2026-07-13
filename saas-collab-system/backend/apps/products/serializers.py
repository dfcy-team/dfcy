from rest_framework import serializers

from .models import (
    ProductResearch,
    ProductLifecycleDecision,
    ProductLifecycleReview,
    ProductLifecycleStage,
    ProductSKU,
    ProductSPU,
    ProductStatusRecommendation,
    ProductStatusSnapshot,
    ProductStatusTransition,
)


class ProductResearchSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    created_by_id = serializers.IntegerField(source="created_by.id", read_only=True)

    class Meta:
        model = ProductResearch
        fields = (
            "id",
            "tenant_id",
            "research_no",
            "product_name",
            "platform",
            "competitor_url",
            "estimated_sales",
            "estimated_gross_margin",
            "risk_points",
            "approval_status",
            "created_by_id",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "tenant_id", "created_by_id", "created_at", "updated_at")


class ProductSPUSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)

    class Meta:
        model = ProductSPU
        fields = (
            "id",
            "tenant_id",
            "spu_code",
            "product_name",
            "category",
            "lifecycle_status",
            "sales_status",
            "is_code_frozen",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "tenant_id", "is_code_frozen", "created_at", "updated_at")

    def validate(self, attrs):
        instance = self.instance
        if instance and instance.is_code_frozen and "spu_code" in attrs and attrs["spu_code"] != instance.spu_code:
            raise serializers.ValidationError({"spu_code": "Code is frozen and cannot be changed."})
        return attrs


class ProductSKUSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)

    class Meta:
        model = ProductSKU
        fields = (
            "id",
            "tenant_id",
            "spu",
            "sku_code",
            "size",
            "material",
            "selling_points",
            "package_weight",
            "package_volume",
            "is_code_frozen",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "tenant_id", "is_code_frozen", "created_at", "updated_at")

    def validate_spu(self, value):
        request = self.context["request"]
        if value.tenant_id != request.user.tenant_id:
            raise serializers.ValidationError("SPU does not belong to current tenant.")
        return value

    def validate(self, attrs):
        instance = self.instance
        if instance and instance.is_code_frozen and "sku_code" in attrs and attrs["sku_code"] != instance.sku_code:
            raise serializers.ValidationError({"sku_code": "Code is frozen and cannot be changed."})
        return attrs


class ProductStatusSnapshotSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)

    class Meta:
        model = ProductStatusSnapshot
        fields = (
            "id",
            "tenant_id",
            "spu",
            "sku",
            "source",
            "source_reference",
            "metrics_payload",
            "calculated_status",
            "calculated_at",
        )
        read_only_fields = fields


class ProductStatusRecommendationSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    source_snapshot = ProductStatusSnapshotSerializer(read_only=True)
    confirmed_by_id = serializers.IntegerField(source="confirmed_by.id", read_only=True)

    class Meta:
        model = ProductStatusRecommendation
        fields = (
            "id",
            "tenant_id",
            "spu",
            "sku",
            "recommended_status",
            "reason_code",
            "reason_detail",
            "confidence",
            "source_snapshot",
            "status",
            "created_at",
            "confirmed_by_id",
            "confirmed_at",
        )
        read_only_fields = fields


class ProductStatusTransitionSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    approved_by_id = serializers.IntegerField(source="approved_by.id", read_only=True)

    class Meta:
        model = ProductStatusTransition
        fields = (
            "id",
            "tenant_id",
            "spu",
            "sku",
            "from_status",
            "to_status",
            "trigger_type",
            "recommendation",
            "approved_by_id",
            "reason",
            "created_at",
        )
        read_only_fields = fields


class ProductLifecycleReviewSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    reviewed_by_id = serializers.IntegerField(source="reviewed_by.id", read_only=True)

    class Meta:
        model = ProductLifecycleReview
        fields = (
            "id", "tenant_id", "spu", "sku", "current_stage", "recommended_stage",
            "review_period_start", "review_period_end", "reason_code", "reason_detail",
            "confidence", "source_metrics", "source_type", "rule_version", "status",
            "reviewed_by_id", "reviewed_at", "created_at", "updated_at",
        )
        read_only_fields = fields


class ProductLifecycleDecisionSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    actor_id = serializers.IntegerField(source="actor.id", read_only=True)

    class Meta:
        model = ProductLifecycleDecision
        fields = ("id", "tenant_id", "review", "decision", "from_stage", "to_stage", "actor_id", "reason", "created_at")
        read_only_fields = fields


class ProductLifecycleEvaluationSerializer(serializers.Serializer):
    spu_id = serializers.IntegerField(min_value=1, required=False)
    sku_id = serializers.IntegerField(min_value=1, required=False)
    current_stage = serializers.ChoiceField(choices=ProductLifecycleStage.choices)
    recommended_stage = serializers.ChoiceField(choices=ProductLifecycleStage.choices)
    review_period_start = serializers.DateField()
    review_period_end = serializers.DateField()
    reason_code = serializers.CharField(max_length=80)
    reason_detail = serializers.CharField(max_length=2000)
    confidence = serializers.DecimalField(max_digits=5, decimal_places=4, min_value=0, max_value=1)
    source_metrics = serializers.JSONField()

    def validate(self, attrs):
        if not attrs.get("spu_id") and not attrs.get("sku_id"):
            raise serializers.ValidationError("spu_id or sku_id is required.")
        if attrs["review_period_start"] > attrs["review_period_end"]:
            raise serializers.ValidationError({"review_period_end": "Must not be earlier than review_period_start."})
        return attrs


class ProductLifecycleDecisionRequestSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=1000, trim_whitespace=True)


class ProductLifecycleQuerySerializer(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=50)
    status = serializers.ChoiceField(choices=ProductLifecycleReview.Status.choices, required=False)
    recommended_stage = serializers.ChoiceField(choices=ProductLifecycleStage.choices, required=False)
