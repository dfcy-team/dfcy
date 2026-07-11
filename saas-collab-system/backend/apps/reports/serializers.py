from rest_framework import serializers

from .models import MetricAggregate, MetricDefinition


class MetricDefinitionSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)

    class Meta:
        model = MetricDefinition
        fields = (
            "id",
            "tenant_id",
            "metric_code",
            "name",
            "description",
            "formula",
            "aggregation_method",
            "source_tables",
            "supported_granularities",
            "allowed_dimensions",
            "permission_code",
            "allow_drill_down",
            "contains_sensitive_data",
            "missing_data_policy",
            "allows_automated_decision",
            "version",
            "status",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class MetricAggregateSerializer(serializers.ModelSerializer):
    tenant_id = serializers.IntegerField(source="tenant.id", read_only=True)
    metric_code = serializers.CharField(source="metric_definition.metric_code", read_only=True)

    class Meta:
        model = MetricAggregate
        fields = (
            "id",
            "tenant_id",
            "metric_code",
            "definition_version",
            "granularity",
            "period_start",
            "period_end",
            "dimensions",
            "numeric_value",
            "valid_point_count",
            "excluded_point_count",
            "quality_status",
            "quality_detail",
            "is_formal",
            "source_lineage",
            "refreshed_at",
            "calculated_at",
        )
        read_only_fields = fields


class MetricAggregationRequestSerializer(serializers.Serializer):
    metric_code = serializers.CharField(max_length=80)
    granularity = serializers.ChoiceField(choices=MetricAggregate.Granularity.choices)
    period_start = serializers.DateTimeField()
    period_end = serializers.DateTimeField()
    dimensions = serializers.DictField(required=False, default=dict)

    def validate(self, attrs):
        if attrs["period_start"] >= attrs["period_end"]:
            raise serializers.ValidationError({"period_end": "Must be later than period_start."})
        return attrs


class PaginationQuerySerializer(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=50)


class MetricDefinitionQuerySerializer(PaginationQuerySerializer):
    metric_code = serializers.CharField(max_length=80, required=False)


class MetricAggregateQuerySerializer(PaginationQuerySerializer):
    metric_code = serializers.CharField(max_length=80, required=False)
    granularity = serializers.ChoiceField(choices=MetricAggregate.Granularity.choices, required=False)
    period_start = serializers.DateTimeField(required=False)
    period_end = serializers.DateTimeField(required=False)
    include_non_formal = serializers.BooleanField(default=False)

    def validate(self, attrs):
        period_start = attrs.get("period_start")
        period_end = attrs.get("period_end")
        if period_start and period_end and period_start >= period_end:
            raise serializers.ValidationError({"period_end": "Must be later than period_start."})
        return attrs
