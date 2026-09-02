from rest_framework import serializers

from .services import operation_log_payload


class OperationLogSummarySerializer(serializers.Serializer):
    """Explicit allow-list serializer for the audit table.

    A ModelSerializer would make future model fields visible by accident.  An
    explicit serializer keeps the API response limited to operational metadata.
    """

    id = serializers.IntegerField(read_only=True)
    tenant_id = serializers.IntegerField(read_only=True)
    operator = serializers.CharField(read_only=True)
    operator_id = serializers.IntegerField(read_only=True, allow_null=True)
    operator_name = serializers.CharField(read_only=True)
    module = serializers.CharField(read_only=True)
    action = serializers.CharField(read_only=True)
    object_type = serializers.CharField(read_only=True)
    object_id = serializers.CharField(read_only=True)
    ip_address = serializers.IPAddressField(read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)

    def to_representation(self, instance):
        return super().to_representation(operation_log_payload(instance))


class OperationLogDetailSerializer(OperationLogSummarySerializer):
    before_data = serializers.JSONField(read_only=True)
    after_data = serializers.JSONField(read_only=True)

    def to_representation(self, instance):
        return serializers.Serializer.to_representation(self, operation_log_payload(instance, include_changes=True))
