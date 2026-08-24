from django.utils import timezone
from rest_framework import serializers

from apps.common.security import sanitize_sensitive_data
from apps.rpa.models import (
    RPAAccountLock,
    RPAAgent,
    RPAEvidence,
    RPAPageSignature,
    RPATask,
    RPATaskAttempt,
    RPATaskStepLog,
)


class RPATaskListSerializer(serializers.ModelSerializer):
    task_id = serializers.IntegerField(source="id", read_only=True)
    agent = serializers.CharField(source="claimed_by.name", allow_null=True, read_only=True)
    manual_assignee = serializers.CharField(source="manual_assignee.username", allow_null=True, read_only=True)

    class Meta:
        model = RPATask
        fields = (
            "id", "task_id", "task_type", "business_type", "business_id", "status", "execution_mode", "priority",
            "agent", "retry_count", "max_retry_count", "manual_assignee", "manual_reason",
            "manual_assigned_at", "claimed_at", "started_at", "finished_at", "created_at", "updated_at",
        )


class RPATaskCreateSerializer(serializers.ModelSerializer):
    confirm_production = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta:
        model = RPATask
        fields = (
            "task_type", "business_type", "business_id", "execution_mode", "priority",
            "payload", "max_retry_count", "confirm_production",
        )

    def validate_payload(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Payload must be a JSON object.")
        return sanitize_sensitive_data(value)

    def validate(self, attrs):
        mode = attrs.get("execution_mode", RPATask.ExecutionMode.DRY_RUN)
        if mode == RPATask.ExecutionMode.PRODUCTION and not attrs.pop("confirm_production", False):
            raise serializers.ValidationError(
                {"confirm_production": "Production tasks require explicit confirmation."}
            )
        attrs.pop("confirm_production", None)
        return attrs


class RPATaskStepLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = RPATaskStepLog
        fields = ("id", "step_name", "status", "message", "screenshot_url", "created_at")


class RPAEvidenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = RPAEvidence
        fields = ("id", "attempt_id", "evidence_type", "placeholder_url", "payload_hash", "created_at")


class RPATaskDetailSerializer(RPATaskListSerializer):
    payload = serializers.SerializerMethodField()
    result = serializers.SerializerMethodField()
    logs = RPATaskStepLogSerializer(source="step_logs", many=True, read_only=True)
    screenshots = RPAEvidenceSerializer(source="evidence", many=True, read_only=True)

    class Meta(RPATaskListSerializer.Meta):
        fields = RPATaskListSerializer.Meta.fields + ("payload", "result", "error_message", "logs", "screenshots")

    def get_payload(self, obj):
        return sanitize_sensitive_data(obj.payload)

    def get_result(self, obj):
        return sanitize_sensitive_data(obj.result)


class RPARunSerializer(serializers.ModelSerializer):
    task_id = serializers.IntegerField(read_only=True)
    task_code = serializers.SerializerMethodField()
    agent = serializers.CharField(source="agent.name", read_only=True)

    class Meta:
        model = RPATaskAttempt
        fields = (
            "id", "task_id", "task_code", "attempt_no", "agent", "started_at", "heartbeat_at",
            "finished_at", "status", "failed_step", "last_success_step", "masked_error", "manual_required",
        )

    def get_task_code(self, obj):
        return f"RPA-{obj.task_id:06d}"


class RPADeviceSerializer(serializers.ModelSerializer):
    availability = serializers.SerializerMethodField()
    fingerprint_masked = serializers.SerializerMethodField()
    user_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = RPAAgent
        fields = (
            "id", "name", "user_id", "status", "execution_mode", "availability",
            "fingerprint_masked", "last_heartbeat_at", "created_at", "updated_at",
        )

    def get_availability(self, obj):
        if obj.status != RPAAgent.Status.ACTIVE:
            return "disabled"
        if not obj.last_heartbeat_at:
            return "unknown"
        return "online" if (timezone.now() - obj.last_heartbeat_at).total_seconds() <= 300 else "offline"

    def get_fingerprint_masked(self, obj):
        value = obj.device_fingerprint or ""
        if not value:
            return ""
        if len(value) <= 8:
            return "***"
        return f"{value[:4]}***{value[-4:]}"


class RPAAccountLockSerializer(serializers.ModelSerializer):
    task_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = RPAAccountLock
        fields = (
            "id", "platform", "account_alias", "task_id", "lock_status",
            "acquired_at", "expires_at", "released_at",
        )


class RPAPageSignatureSerializer(serializers.ModelSerializer):
    signature_hash_masked = serializers.SerializerMethodField()

    class Meta:
        model = RPAPageSignature
        fields = ("id", "platform", "page_type", "signature_hash_masked", "detected_status", "created_at")

    def get_signature_hash_masked(self, obj):
        return f"{obj.signature_hash[:8]}***" if obj.signature_hash else ""
