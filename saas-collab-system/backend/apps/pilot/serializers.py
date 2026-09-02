from datetime import timedelta
import json
import unicodedata

from rest_framework import serializers, status

from apps.common.error_codes import ErrorCode
from apps.common.exceptions import ContractViolation

from .models import CapacityObservation, PilotExecution, RecoveryDrill, RecoveryPlan, ReleasePlan, TopologyService


class StrictSerializer(serializers.Serializer):
    def validate(self, attrs):
        def inspect(value):
            if isinstance(value, str) and any(unicodedata.category(char) == "Cc" for char in value):
                raise serializers.ValidationError("Control characters are not allowed.")
            if isinstance(value, list):
                canonical = [json.dumps(item, sort_keys=True, ensure_ascii=False) for item in value]
                if len(canonical) != len(set(canonical)):
                    raise serializers.ValidationError("Array values must be unique.")
                for item in value:
                    inspect(item)
            elif isinstance(value, dict):
                for item in value.values():
                    inspect(item)

        inspect(attrs)
        return attrs

    def to_internal_value(self, data):
        unknown = set(data) - set(self.fields)
        if unknown:
            raise ContractViolation(
                f"Unknown fields: {', '.join(sorted(unknown))}.",
                error_code=ErrorCode.UNKNOWN_FIELD,
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        return super().to_internal_value(data)

    def is_valid(self, *, raise_exception=False):
        valid = super().is_valid(raise_exception=False)
        if not valid and raise_exception:
            raise ContractViolation(
                "Request fields failed contract validation.",
                error_code=ErrorCode.FIELD_VALIDATION_FAILED,
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        return valid


class CapacityObservationSerializer(serializers.ModelSerializer):
    environment_id = serializers.CharField(source="environment.code")
    threshold = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    expires_at = serializers.SerializerMethodField()
    is_missing = serializers.SerializerMethodField()

    class Meta:
        model = CapacityObservation
        fields = (
            "id", "environment_id", "service_name", "metric_code", "value", "unit", "threshold",
            "status", "source", "observed_at", "expires_at", "is_missing",
        )

    def get_threshold(self, obj):
        if obj.status == CapacityObservation.Status.CRITICAL:
            return obj.critical_threshold
        if obj.status in {CapacityObservation.Status.NORMAL, CapacityObservation.Status.WARNING}:
            return obj.warning_threshold
        return None

    def get_status(self, obj):
        return obj.status

    def get_expires_at(self, obj):
        return obj.observed_at + timedelta(minutes=15)

    def get_is_missing(self, obj):
        return obj.value is None


class TopologyServiceSerializer(serializers.ModelSerializer):
    masked_endpoint = serializers.SerializerMethodField()
    exposure = serializers.SerializerMethodField()
    health_status = serializers.SerializerMethodField()
    checked_at = serializers.DateTimeField(source="verified_at", allow_null=True)

    class Meta:
        model = TopologyService
        fields = (
            "service_name", "host_role", "network_zone", "masked_endpoint",
            "exposure", "health_status", "checked_at",
        )

    def get_masked_endpoint(self, obj):
        return f"{obj.service_name}@{obj.network_zone}"

    def get_exposure(self, obj):
        if obj.exposure in {"loopback", "app_host_only", "controlled_lan", "none"}:
            return obj.exposure
        return "app_host_only" if obj.network_zone == "controlled_db" else "controlled_lan"

    def get_health_status(self, obj):
        return "unknown" if obj.verified_at is None else "healthy"


class RecoveryPlanSerializer(serializers.ModelSerializer):
    environment_id = serializers.CharField(source="environment.code")
    created_by_id = serializers.IntegerField(read_only=True)
    approved_by_id = serializers.IntegerField(read_only=True)
    audit_ref = serializers.SerializerMethodField()

    class Meta:
        model = RecoveryPlan
        fields = (
            "id", "environment_id", "name", "rpo_minutes", "rto_minutes", "backup_summary",
            "backup_checksum_masked", "approval_ref", "status", "scheduled_at", "created_by_id",
            "approved_by_id", "version", "created_at", "updated_at", "audit_ref",
        )

    def get_audit_ref(self, obj):
        return f"pilot-audit:{obj.audit_events.order_by('-id').values_list('id', flat=True).first() or 'pending'}"


class RecoveryDrillSerializer(serializers.ModelSerializer):
    recovery_plan_id = serializers.IntegerField(read_only=True)
    environment_id = serializers.CharField(source="recovery_plan.environment.code", read_only=True)
    audit_ref = serializers.SerializerMethodField()

    class Meta:
        model = RecoveryDrill
        fields = (
            "id", "environment_id", "recovery_plan_id", "status", "started_at", "finished_at",
            "actual_rpo_minutes", "actual_rto_minutes", "result_summary", "evidence_refs", "version", "audit_ref",
        )

    def get_audit_ref(self, obj):
        event_id = obj.recovery_plan.audit_events.order_by("-id").values_list("id", flat=True).first()
        return f"pilot-audit:{event_id or 'pending'}"


class ReleasePlanSerializer(serializers.ModelSerializer):
    environment_id = serializers.CharField(source="environment.code")
    # ``tenant_refs`` is the production UI contract; retain the historical
    # ``demo_tenant_refs`` field in responses for API compatibility.
    tenant_refs = serializers.ListField(source="demo_tenant_refs", read_only=True)
    created_by_id = serializers.IntegerField(read_only=True)
    approved_by_id = serializers.IntegerField(read_only=True)
    rollback_approved_by_id = serializers.IntegerField(read_only=True)
    audit_ref = serializers.SerializerMethodField()

    class Meta:
        model = ReleasePlan
        fields = (
            "id", "environment_id", "release_channel", "commit_sha", "tag", "demo_tenant_refs",
            "tenant_refs",
            "observation_minutes", "stop_conditions", "rollback_point", "database_compatibility",
            "approval_ref", "rollback_approval_ref", "rollback_approved_by_id", "rollback_approved_at",
            "rollback_approval_expires_at", "status", "manual_context", "scheduled_at", "created_by_id",
            "approved_by_id", "version", "result_summary", "evidence_refs", "created_at", "updated_at", "audit_ref",
        )

    def get_audit_ref(self, obj):
        return f"pilot-audit:{obj.audit_events.order_by('-id').values_list('id', flat=True).first() or 'pending'}"


class RecoveryCreateSerializer(StrictSerializer):
    environment_id = serializers.RegexField(r"^[a-z0-9][a-z0-9-]{1,63}$")
    name = serializers.CharField(min_length=1, max_length=120)
    rpo_minutes = serializers.IntegerField(min_value=1, max_value=10080)
    rto_minutes = serializers.IntegerField(min_value=1, max_value=10080)
    backup_summary = serializers.CharField(min_length=1, max_length=500)
    backup_checksum_masked = serializers.CharField(min_length=1, max_length=128)
    reason = serializers.CharField(min_length=1, max_length=500)


class ReleaseCreateSerializer(StrictSerializer):
    environment_id = serializers.RegexField(r"^[a-z0-9][a-z0-9-]{1,63}$")
    release_channel = serializers.ChoiceField(choices=("demo", "controlled_pilot"))
    # production-control consumes an exact lowercase Git object id; accepting
    # abbreviated or uppercase values would defer a predictable failure until
    # after approval.
    commit_sha = serializers.RegexField(r"^[0-9a-f]{40}$")
    tag = serializers.CharField(max_length=120, required=False, allow_blank=True, allow_null=True)
    demo_tenant_refs = serializers.ListField(child=serializers.CharField(min_length=1, max_length=120), min_length=1, max_length=20, required=False)
    tenant_refs = serializers.ListField(child=serializers.CharField(min_length=1, max_length=120), min_length=1, max_length=20, required=False)
    observation_minutes = serializers.IntegerField(min_value=15, max_value=1440)
    stop_conditions = serializers.ListField(child=serializers.CharField(min_length=1, max_length=300), min_length=1, max_length=20)
    rollback_point = serializers.CharField(min_length=1, max_length=200)
    database_compatibility = serializers.ChoiceField(choices=("verified", "not_required", "pending"))
    reason = serializers.CharField(min_length=1, max_length=500)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        legacy = attrs.get("demo_tenant_refs")
        current = attrs.get("tenant_refs")
        if legacy is None and current is None:
            raise serializers.ValidationError("tenant_refs is required.")
        if legacy is not None and current is not None and legacy != current:
            raise serializers.ValidationError("tenant_refs and demo_tenant_refs must match when both are supplied.")
        attrs["demo_tenant_refs"] = current if current is not None else legacy
        attrs.pop("tenant_refs", None)
        return attrs


class VersionReasonSerializer(StrictSerializer):
    version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(min_length=1, max_length=500)


class ApprovalSerializer(VersionReasonSerializer):
    approval_ref = serializers.CharField(min_length=1, max_length=160)


class ScheduleSerializer(VersionReasonSerializer):
    scheduled_at = serializers.DateTimeField()


class ResumeSerializer(VersionReasonSerializer):
    manual_resolution_ref = serializers.CharField(min_length=1, max_length=160)


class RecoveryResultSerializer(VersionReasonSerializer):
    result_status = serializers.ChoiceField(choices=("success", "failed", "manual_required"))
    actual_rpo_minutes = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    actual_rto_minutes = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    result_summary = serializers.CharField(min_length=1, max_length=1000)
    evidence_refs = serializers.ListField(child=serializers.CharField(min_length=1, max_length=200), max_length=20)


class ReleaseResultSerializer(VersionReasonSerializer):
    result_status = serializers.ChoiceField(choices=("success", "failed", "rollback_required", "manual_required"))
    result_summary = serializers.CharField(min_length=1, max_length=1000)
    evidence_refs = serializers.ListField(child=serializers.CharField(min_length=1, max_length=200), max_length=20)


class RollbackApprovalSerializer(VersionReasonSerializer):
    rollback_approval_ref = serializers.CharField(min_length=1, max_length=160)
    approval_expires_at = serializers.DateTimeField()


class RollbackResumeSerializer(ResumeSerializer):
    rollback_approval_ref = serializers.CharField(min_length=1, max_length=160)


class RollbackResultSerializer(VersionReasonSerializer):
    rollback_approval_ref = serializers.CharField(min_length=1, max_length=160)
    rollback_status = serializers.ChoiceField(choices=("rolled_back", "failed", "manual_required"))
    result_summary = serializers.CharField(min_length=1, max_length=1000)
    evidence_refs = serializers.ListField(child=serializers.CharField(min_length=1, max_length=200), max_length=20)


class TopologyVerifySerializer(StrictSerializer):
    environment_id = serializers.RegexField(r"^[a-z0-9][a-z0-9-]{1,63}$")
    services = serializers.ListField(child=serializers.DictField(), min_length=1, max_length=20)
    reason = serializers.CharField(min_length=1, max_length=500)

    def validate_services(self, services):
        allowed = {"service_name", "host_role", "network_zone", "exposure"}
        service_names = {"nginx", "backend", "celery_worker", "celery_beat", "redis", "mysql"}
        for service in services:
            if set(service) != allowed:
                raise serializers.ValidationError("Each service must contain exactly the frozen topology fields.")
            if service["service_name"] not in service_names:
                raise serializers.ValidationError("Unknown service name.")
            if service["host_role"] not in {"application", "database"}:
                raise serializers.ValidationError("Unknown host role.")
            if service["network_zone"] not in {"controlled_app", "controlled_db"}:
                raise serializers.ValidationError("Unknown network zone.")
            if service["exposure"] not in {"loopback", "app_host_only", "controlled_lan", "none"}:
                raise serializers.ValidationError("Unknown exposure.")
        return services


class ProductionExecutionSerializer(StrictSerializer):
    """Only a version fence and business reason are accepted from callers."""

    version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(min_length=1, max_length=500)


class ProductionRollbackExecutionSerializer(ProductionExecutionSerializer):
    rollback_approval_ref = serializers.CharField(min_length=1, max_length=160)


class PilotExecutionSerializer(serializers.ModelSerializer):
    performance_run_id = serializers.IntegerField(read_only=True)
    recovery_plan_id = serializers.IntegerField(read_only=True)
    recovery_drill_id = serializers.IntegerField(read_only=True)
    release_plan_id = serializers.IntegerField(read_only=True)
    api_status = serializers.SerializerMethodField()

    class Meta:
        model = PilotExecution
        fields = (
            "id", "execution_type", "performance_run_id", "recovery_plan_id", "recovery_drill_id", "release_plan_id",
            "request_version", "request_id", "status", "attempt", "runner_job_id",
            "runner_reference", "result_metrics", "evidence_refs", "result_summary",
            "error_code", "error_message", "celery_task_id", "started_at", "finished_at",
            "runner_deadline_at", "created_at", "updated_at", "api_status",
        )

    def get_api_status(self, obj):
        from .runner import runner_dependency_status

        return runner_dependency_status()["status"]
