from decimal import Decimal

from rest_framework import serializers


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError("A JSON object is required.")
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(
                {"unknown_fields": f"Unknown fields: {sorted(unknown)}"}
            )
        return super().to_internal_value(data)


class PackingBatchCreateSerializer(StrictSerializer):
    order_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        max_length=100,
    )
    note = serializers.CharField(required=False, allow_blank=True, max_length=1000)

    def validate_order_ids(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Order IDs must not contain duplicates.")
        return sorted(value)


class PackingItemSerializer(StrictSerializer):
    order_line_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1)


class PackingBoxWriteSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    weight = serializers.DecimalField(
        max_digits=12,
        decimal_places=3,
        min_value=Decimal("0.001"),
        required=False,
        allow_null=True,
    )
    volume = serializers.DecimalField(
        max_digits=12,
        decimal_places=6,
        min_value=Decimal("0.000001"),
        required=False,
        allow_null=True,
    )
    note = serializers.CharField(required=False, allow_blank=True, max_length=1000)
    items = PackingItemSerializer(many=True, allow_empty=False, max_length=500)

    def validate_items(self, value):
        line_ids = [item["order_line_id"] for item in value]
        if len(line_ids) != len(set(line_ids)):
            raise serializers.ValidationError("Order-line IDs must not contain duplicates.")
        return value


class ExpectedVersionSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)


class ProposedPackingBoxSerializer(StrictSerializer):
    weight = serializers.DecimalField(
        max_digits=12,
        decimal_places=3,
        min_value=Decimal("0.001"),
        required=False,
        allow_null=True,
    )
    volume = serializers.DecimalField(
        max_digits=12,
        decimal_places=6,
        min_value=Decimal("0.000001"),
        required=False,
        allow_null=True,
    )
    note = serializers.CharField(required=False, allow_blank=True, max_length=1000)
    items = PackingItemSerializer(many=True, allow_empty=False, max_length=500)

    def validate_items(self, value):
        line_ids = [item["order_line_id"] for item in value]
        if len(line_ids) != len(set(line_ids)):
            raise serializers.ValidationError("Order-line IDs must not contain duplicates.")
        return value


class PackingChangeSubmitSerializer(StrictSerializer):
    expected_version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(min_length=1, max_length=1000, trim_whitespace=True)
    proposed_boxes = ProposedPackingBoxSerializer(
        many=True,
        allow_empty=False,
        max_length=500,
    )

    def validate_proposed_boxes(self, value):
        if sum(len(box["items"]) for box in value) > 5000:
            raise serializers.ValidationError("A change may contain at most 5000 items.")
        return value


class PackingReviewSerializer(StrictSerializer):
    review_note = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=1000,
        trim_whitespace=True,
    )


class PackingLabelSerializer(ExpectedVersionSerializer):
    pass
