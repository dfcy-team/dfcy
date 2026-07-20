import json
import re
import unicodedata
from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers, status

from apps.common.error_codes import ErrorCode
from apps.common.exceptions import ContractViolation

from .models import EntryDecision, PerformanceRun, SecurityReview, VerificationRun


SENSITIVE_PATTERN = re.compile(
    r"(?:https?://|(?:password|passwd|token|cookie|session|api[_-]?key|api[_-]?secret)\s*[:=]|"
    r"(?:\d{1,3}\.){3}\d{1,3}|(?:mysql|redis)://)",
    re.IGNORECASE,
)


class UIP8StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        unknown = set(data) - set(self.fields)
        if unknown:
            raise ContractViolation(
                f"Forbidden or unknown fields: {', '.join(sorted(unknown))}.",
                error_code=ErrorCode.FORBIDDEN_FIELD,
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        return super().to_internal_value(data)

    def validate(self, attrs):
        def inspect(value):
            if isinstance(value, str):
                if any(unicodedata.category(char) == "Cc" for char in value):
                    raise serializers.ValidationError("Control characters are not allowed.")
                if SENSITIVE_PATTERN.search(value):
                    raise serializers.ValidationError("Sensitive values, endpoints, and connection strings are forbidden.")
            elif isinstance(value, list):
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

    def is_valid(self, *, raise_exception=False):
        valid = super().is_valid(raise_exception=False)
        if not valid and raise_exception:
            raise ContractViolation(
                "Request fields failed UI-P8 contract validation.",
                error_code=ErrorCode.VALIDATION_ERROR,
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        return valid


class FinanceScopeSerializer(UIP8StrictSerializer):
    platforms = serializers.ListField(child=serializers.RegexField(r"^[a-z][a-z0-9_-]{1,39}$"), min_length=1, max_length=20)
    currencies = serializers.ListField(child=serializers.RegexField(r"^[A-Z]{3}$"), min_length=1, max_length=20)


class ThresholdSerializer(UIP8StrictSerializer):
    p95_ms_max = serializers.FloatField(min_value=0.001, max_value=3600000)
    error_rate_max = serializers.FloatField(min_value=0, max_value=1)
    cpu_percent_max = serializers.FloatField(min_value=0, max_value=100)
    memory_percent_max = serializers.FloatField(min_value=0, max_value=100)


class CommonDraftFields(UIP8StrictSerializer):
    environment = serializers.ChoiceField(choices=("sandbox", "pilot"))
    evidence_refs = serializers.ListField(child=serializers.CharField(min_length=1, max_length=200), min_length=1, max_length=50)


class SecurityDraftSerializer(CommonDraftFields):
    review_type = serializers.ChoiceField(choices=SecurityReview.ReviewType.values)
    scope_summary = serializers.CharField(min_length=1, max_length=1000, trim_whitespace=True)
    risk_level = serializers.ChoiceField(choices=("low", "medium", "high", "critical"))
    finance_scope = FinanceScopeSerializer(required=True, allow_null=True)
    expires_at = serializers.DateTimeField()

    def validate(self, attrs):
        attrs = super().validate(attrs)
        finance_scope = attrs.get("finance_scope")
        if attrs["review_type"] == SecurityReview.ReviewType.FINANCE_BOUNDARY and not finance_scope:
            raise serializers.ValidationError("Finance boundary review requires finance_scope.")
        if attrs["review_type"] != SecurityReview.ReviewType.FINANCE_BOUNDARY and finance_scope is not None:
            raise serializers.ValidationError("Non-finance review requires finance_scope=null.")
        if not timezone.now() < attrs["expires_at"] <= timezone.now() + timedelta(days=180):
            raise serializers.ValidationError("expires_at must be within the next 180 days.")
        return attrs


class VerificationDraftSerializer(CommonDraftFields):
    category = serializers.ChoiceField(choices=(
        "authentication", "authorization", "browser_e2e", "backup_restore", "failover",
        "network_isolation", "security_scan",
    ))
    target_alias = serializers.RegexField(r"^[a-z][a-z0-9-]{1,63}$")
    data_class = serializers.ChoiceField(choices=("demo", "synthetic", "masked"))
    planned_start_at = serializers.DateTimeField()
    planned_end_at = serializers.DateTimeField()
    success_criteria = serializers.ListField(child=serializers.CharField(min_length=1, max_length=500), min_length=1, max_length=20)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs["planned_end_at"] <= attrs["planned_start_at"]:
            raise serializers.ValidationError("planned_end_at must be later than planned_start_at.")
        return attrs


class PerformanceDraftSerializer(CommonDraftFields):
    scenario = serializers.CharField(min_length=1, max_length=200, trim_whitespace=True)
    workload_profile = serializers.ChoiceField(choices=("demo", "synthetic"))
    max_rps = serializers.IntegerField(min_value=1, max_value=500)
    concurrency = serializers.IntegerField(min_value=1, max_value=100)
    duration_seconds = serializers.IntegerField(min_value=1, max_value=3600)
    thresholds = ThresholdSerializer()


class EntryDraftSerializer(UIP8StrictSerializer):
    environment = serializers.ChoiceField(choices=("sandbox", "pilot"))
    decision = serializers.ChoiceField(choices=("go", "no_go"))
    scope_summary = serializers.CharField(min_length=1, max_length=1000, trim_whitespace=True)
    security_review_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), min_length=1, max_length=100)
    verification_run_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), min_length=1, max_length=100)
    performance_run_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), min_length=1, max_length=100)
    recovery_plan_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), min_length=1, max_length=100)
    release_plan_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), min_length=1, max_length=100)
    expires_at = serializers.DateTimeField()

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if not timezone.now() < attrs["expires_at"] <= timezone.now() + timedelta(days=30):
            raise serializers.ValidationError("expires_at must be within the next 30 days.")
        return attrs


class PatchSerializer(UIP8StrictSerializer):
    version = serializers.IntegerField(min_value=1)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if len(attrs) < 2:
            raise serializers.ValidationError("PATCH requires at least one mutable field.")
        return attrs


def patch_serializer(name, draft_class):
    fields = {"version": serializers.IntegerField(min_value=1)}
    for field_name, field in draft_class().fields.items():
        field.required = False
        fields[field_name] = field
    return type(name, (PatchSerializer,), fields)


SecurityPatchSerializer = patch_serializer("SecurityPatchSerializer", SecurityDraftSerializer)
VerificationPatchSerializer = patch_serializer("VerificationPatchSerializer", VerificationDraftSerializer)
PerformancePatchSerializer = patch_serializer("PerformancePatchSerializer", PerformanceDraftSerializer)
EntryPatchSerializer = patch_serializer("EntryPatchSerializer", EntryDraftSerializer)


class VersionReasonSerializer(UIP8StrictSerializer):
    version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(min_length=1, max_length=1000, trim_whitespace=True)


class ReviewSerializer(UIP8StrictSerializer):
    version = serializers.IntegerField(min_value=1)
    review_reason = serializers.CharField(min_length=1, max_length=1000, trim_whitespace=True)


class CancelSerializer(UIP8StrictSerializer):
    version = serializers.IntegerField(min_value=1)
    cancel_reason = serializers.CharField(min_length=1, max_length=1000, trim_whitespace=True)


class VerificationResultSerializer(UIP8StrictSerializer):
    version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(min_length=1, max_length=1000)
    result = serializers.ChoiceField(choices=("passed", "failed", "manual_required"))
    result_summary = serializers.CharField(min_length=1, max_length=1000)
    evidence_refs = serializers.ListField(child=serializers.CharField(min_length=1, max_length=200), min_length=1, max_length=50)
    started_at = serializers.DateTimeField()
    finished_at = serializers.DateTimeField()
    error_code = serializers.RegexField(r"^[A-Z][A-Z0-9_]{0,79}$", allow_null=True)
    error_message = serializers.CharField(min_length=1, max_length=1000, allow_null=True)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs["finished_at"] < attrs["started_at"]:
            raise serializers.ValidationError("finished_at cannot precede started_at.")
        has_error = attrs["error_code"] is not None and attrs["error_message"] is not None
        if attrs["result"] == "passed" and (attrs["error_code"] is not None or attrs["error_message"] is not None):
            raise serializers.ValidationError("Passed results require null error fields.")
        if attrs["result"] != "passed" and not has_error:
            raise serializers.ValidationError("Failed or manual results require error fields.")
        return attrs


class PerformanceResultSerializer(UIP8StrictSerializer):
    version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(min_length=1, max_length=1000)
    result_mode = serializers.ChoiceField(choices=("measured", "manual_required"))
    p50_ms = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=0, max_value=3600000, allow_null=True)
    p95_ms = serializers.DecimalField(max_digits=12, decimal_places=3, min_value=0, max_value=3600000, allow_null=True)
    error_rate = serializers.DecimalField(max_digits=8, decimal_places=6, min_value=0, max_value=1, allow_null=True)
    cpu_percent = serializers.DecimalField(max_digits=7, decimal_places=3, min_value=0, max_value=100, allow_null=True)
    memory_percent = serializers.DecimalField(max_digits=7, decimal_places=3, min_value=0, max_value=100, allow_null=True)
    result_summary = serializers.CharField(min_length=1, max_length=1000)
    evidence_refs = serializers.ListField(child=serializers.CharField(min_length=1, max_length=200), min_length=1, max_length=50)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        metrics = [attrs[key] for key in ("p50_ms", "p95_ms", "error_rate", "cpu_percent", "memory_percent")]
        if attrs["result_mode"] == "measured":
            if any(value is None for value in metrics) or attrs["p50_ms"] > attrs["p95_ms"]:
                raise serializers.ValidationError("Measured results require valid ordered metrics.")
        elif any(value is not None for value in metrics):
            raise serializers.ValidationError("manual_required requires explicit null metrics.")
        return attrs


class AuditRefMixin:
    def get_audit_ref(self, obj):
        event = obj.tenant.pilot_audit_events.filter(object_type=self.Meta.object_type, object_id=str(obj.id)).order_by("-id").first()
        return f"pilot-audit:{event.id if event else 'pending'}"


class SecurityReviewSerializer(AuditRefMixin, serializers.ModelSerializer):
    environment = serializers.CharField(source="environment.code")
    owner_id = serializers.IntegerField(read_only=True)
    creator_id = serializers.IntegerField(read_only=True)
    reviewer_id = serializers.IntegerField(read_only=True)
    audit_ref = serializers.SerializerMethodField()

    class Meta:
        model = SecurityReview
        object_type = "security_review"
        fields = (
            "id", "code", "review_type", "environment", "scope_summary", "risk_level", "owner_id",
            "finance_scope", "evidence_refs", "expires_at", "status", "creator_id",
            "reviewer_id", "reviewed_at", "review_reason", "version", "audit_ref", "created_at", "updated_at",
        )


class VerificationRunSerializer(AuditRefMixin, serializers.ModelSerializer):
    environment = serializers.CharField(source="environment.code")
    creator_id = serializers.IntegerField(read_only=True)
    reviewer_id = serializers.IntegerField(read_only=True)
    recorder_id = serializers.IntegerField(read_only=True)
    audit_ref = serializers.SerializerMethodField()

    class Meta:
        model = VerificationRun
        object_type = "verification_run"
        fields = (
            "id", "code", "category", "environment", "target_alias", "data_class", "planned_start_at",
            "planned_end_at", "success_criteria", "evidence_refs", "status", "result_summary", "started_at",
            "finished_at", "error_code", "error_message", "creator_id", "reviewer_id", "recorder_id",
            "version", "audit_ref", "created_at", "updated_at",
        )


class PerformanceRunSerializer(AuditRefMixin, serializers.ModelSerializer):
    environment = serializers.CharField(source="environment.code")
    creator_id = serializers.IntegerField(read_only=True)
    reviewer_id = serializers.IntegerField(read_only=True)
    recorder_id = serializers.IntegerField(read_only=True)
    audit_ref = serializers.SerializerMethodField()

    class Meta:
        model = PerformanceRun
        object_type = "performance_run"
        fields = (
            "id", "code", "scenario", "environment", "workload_profile", "max_rps", "concurrency",
            "duration_seconds", "thresholds", "evidence_refs", "status", "p50_ms", "p95_ms", "error_rate",
            "cpu_percent", "memory_percent", "result_summary", "creator_id", "reviewer_id",
            "recorder_id", "version", "audit_ref", "created_at", "updated_at",
        )


class EntryDecisionSerializer(AuditRefMixin, serializers.ModelSerializer):
    environment = serializers.CharField(source="environment.code")
    creator_id = serializers.IntegerField(read_only=True)
    reviewer_id = serializers.IntegerField(read_only=True)
    audit_ref = serializers.SerializerMethodField()

    class Meta:
        model = EntryDecision
        object_type = "entry_decision"
        fields = (
            "id", "code", "environment", "decision", "scope_summary", "security_review_ids",
            "verification_run_ids", "performance_run_ids", "recovery_plan_ids", "release_plan_ids",
            "expires_at", "status", "evidence_snapshot", "evidence_hash", "blockers", "warnings",
            "contract_version", "creator_id", "reviewer_id", "reviewed_at", "review_reason",
            "version", "audit_ref", "created_at", "updated_at",
        )


class SecurityReviewSummarySerializer(serializers.ModelSerializer):
    environment = serializers.CharField(source="environment.code")
    owner_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = SecurityReview
        fields = ("id", "code", "review_type", "environment", "risk_level", "status", "owner_id", "expires_at", "version", "created_at", "updated_at")


class VerificationRunSummarySerializer(serializers.ModelSerializer):
    environment = serializers.CharField(source="environment.code")

    class Meta:
        model = VerificationRun
        fields = ("id", "code", "category", "environment", "data_class", "status", "planned_start_at", "planned_end_at", "version", "created_at", "updated_at")


class PerformanceRunSummarySerializer(serializers.ModelSerializer):
    environment = serializers.CharField(source="environment.code")

    class Meta:
        model = PerformanceRun
        fields = ("id", "code", "scenario", "environment", "workload_profile", "status", "max_rps", "concurrency", "version", "created_at", "updated_at")


class EntryDecisionSummarySerializer(serializers.ModelSerializer):
    environment = serializers.CharField(source="environment.code")

    class Meta:
        model = EntryDecision
        fields = ("id", "code", "environment", "decision", "status", "expires_at", "version", "created_at", "updated_at")
