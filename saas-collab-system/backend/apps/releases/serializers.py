from rest_framework import serializers

from .models import ReleaseApproval, ReleaseArtifact, ReleaseAuditEvent, ReleaseContract, ReleaseGateResult
from .services import REQUIRED_GATE_CODES, gate_status


class ReleaseArtifactSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReleaseArtifact
        fields = (
            "build_no",
            "commit_sha",
            "artifact_hash",
            "config_version",
            "manifest",
            "recorded_by_id",
            "created_at",
        )


class ReleaseGateResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReleaseGateResult
        fields = (
            "code",
            "category",
            "status",
            "evidence_ref",
            "evaluated_at",
            "expires_at",
            "recorded_by_id",
            "version",
            "updated_at",
        )


class ReleaseApprovalSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReleaseApproval
        fields = (
            "approval_type",
            "decision",
            "reason",
            "decided_by_id",
            "decided_at",
        )


class ReleaseAuditEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReleaseAuditEvent
        fields = (
            "action",
            "actor_id",
            "from_status",
            "to_status",
            "outcome",
            "reason",
            "evidence_refs",
            "request_id",
            "contract_version",
            "created_at",
        )


class ReleaseContractSummarySerializer(serializers.ModelSerializer):
    gate_summary = serializers.SerializerMethodField()

    class Meta:
        model = ReleaseContract
        fields = (
            "id",
            "contract_no",
            "application_code",
            "environment",
            "commit_sha",
            "risk_level",
            "status",
            "scheduled_at",
            "version",
            "gate_summary",
            "updated_at",
        )

    def get_gate_summary(self, obj):
        return gate_status(obj)


class ReleaseContractDetailSerializer(serializers.ModelSerializer):
    artifact = ReleaseArtifactSerializer(read_only=True)
    gate_results = ReleaseGateResultSerializer(many=True, read_only=True)
    approvals = ReleaseApprovalSerializer(many=True, read_only=True)
    audit_events = ReleaseAuditEventSerializer(many=True, read_only=True)
    gate_summary = serializers.SerializerMethodField()

    class Meta:
        model = ReleaseContract
        fields = (
            "id",
            "contract_no",
            "application_code",
            "environment",
            "commit_sha",
            "api_contract_version",
            "scope",
            "risk_level",
            "rollback_version",
            "rollback_point",
            "stop_conditions",
            "observation_minutes",
            "status",
            "scheduled_at",
            "completed_at",
            "created_by_id",
            "version",
            "artifact",
            "gate_results",
            "approvals",
            "audit_events",
            "gate_summary",
            "created_at",
            "updated_at",
        )

    def get_gate_summary(self, obj):
        return gate_status(obj)


class ReleaseContractCreateSerializer(serializers.Serializer):
    application_code = serializers.SlugField(max_length=80)
    environment = serializers.ChoiceField(choices=ReleaseContract.Environment.choices)
    commit_sha = serializers.CharField(min_length=7, max_length=64)
    api_contract_version = serializers.CharField(min_length=1, max_length=40)
    scope = serializers.ListField(child=serializers.CharField(max_length=160), min_length=1, max_length=100)
    risk_level = serializers.ChoiceField(choices=ReleaseContract.RiskLevel.choices)
    rollback_version = serializers.CharField(min_length=1, max_length=120)
    rollback_point = serializers.CharField(min_length=1, max_length=200)
    stop_conditions = serializers.ListField(child=serializers.JSONField(), min_length=1, max_length=30)
    observation_minutes = serializers.IntegerField(min_value=5, max_value=1440)


class ReleaseGateRecordSerializer(serializers.Serializer):
    version = serializers.IntegerField(min_value=1)
    code = serializers.ChoiceField(choices=REQUIRED_GATE_CODES)
    category = serializers.CharField(min_length=1, max_length=40)
    status = serializers.ChoiceField(choices=ReleaseGateResult.Status.choices)
    evidence_ref = serializers.CharField(min_length=1, max_length=240)
    evaluated_at = serializers.DateTimeField()
    expires_at = serializers.DateTimeField()


class ReleaseApprovalDecisionSerializer(serializers.Serializer):
    version = serializers.IntegerField(min_value=1)
    approval_type = serializers.ChoiceField(choices=ReleaseApproval.ApprovalType.choices)
    decision = serializers.ChoiceField(choices=ReleaseApproval.Decision.choices)
    reason = serializers.CharField(min_length=3, max_length=500)


class ReleaseBuildSerializer(serializers.Serializer):
    version = serializers.IntegerField(min_value=1)
    build_no = serializers.CharField(min_length=1, max_length=80)
    commit_sha = serializers.CharField(min_length=7, max_length=64)
    artifact_hash = serializers.CharField(min_length=64, max_length=64)
    config_version = serializers.CharField(min_length=1, max_length=80)
    manifest = serializers.JSONField(required=False, default=dict)
    reason = serializers.CharField(min_length=3, max_length=500)


class ReleaseActionSerializer(serializers.Serializer):
    version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(min_length=3, max_length=500)
    result_status = serializers.CharField(max_length=30, required=False)
    scheduled_at = serializers.DateTimeField(required=False)
    evidence_refs = serializers.ListField(
        child=serializers.CharField(max_length=240),
        required=False,
        default=list,
        max_length=30,
    )
