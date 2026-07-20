import json
import unicodedata

from rest_framework import serializers, status

from apps.common.error_codes import ErrorCode
from apps.common.exceptions import ContractViolation

from .models import ApiContract, AssistantDefinition


class ApiContractSummarySerializer(serializers.ModelSerializer):
    permission = serializers.CharField(source="permission_code")
    scope_keys = serializers.ListField(source="data_scope_keys")
    response_schema_version = serializers.SerializerMethodField()
    evidence_status = serializers.SerializerMethodField()

    class Meta:
        model = ApiContract
        fields = (
            "id", "module", "name", "path", "method", "owner", "status", "version",
            "permission", "scope_keys", "response_schema_version", "evidence_status", "updated_at",
        )

    def get_response_schema_version(self, obj):
        return obj.version

    def get_evidence_status(self, obj):
        if obj.status in {ApiContract.Status.MOCK, ApiContract.Status.SANDBOX, ApiContract.Status.CONNECTED}:
            return "valid"
        if obj.status == ApiContract.Status.STALE:
            return "stale"
        if obj.status == ApiContract.Status.DEGRADED:
            return "failed"
        return "missing"


class ApiContractDetailSerializer(ApiContractSummarySerializer):
    class Meta(ApiContractSummarySerializer.Meta):
        fields = ApiContractSummarySerializer.Meta.fields + (
            "request_fields", "response_fields", "error_codes", "change_history",
        )


class AssistantSummarySerializer(serializers.ModelSerializer):
    capability_declarations = serializers.ListField(source="output_types")
    data_classes = serializers.SerializerMethodField()
    tool_allowlist = serializers.ListField(source="allowed_tools")

    class Meta:
        model = AssistantDefinition
        fields = (
            "id", "code", "name", "status", "capability_declarations", "data_classes",
            "tool_allowlist", "human_confirmation_required", "updated_at",
        )

    def get_data_classes(self, obj):
        return [obj.data_class]


class AssistantDetailSerializer(AssistantSummarySerializer):
    input_policy = serializers.SerializerMethodField()
    output_policy = serializers.SerializerMethodField()
    review_owner = serializers.SerializerMethodField()
    reviewed_at = serializers.SerializerMethodField()

    class Meta(AssistantSummarySerializer.Meta):
        fields = AssistantSummarySerializer.Meta.fields + (
            "input_policy", "output_policy", "limitations", "review_owner", "reviewed_at",
        )

    def get_input_policy(self, obj):
        return "Demo references only; credentials and raw business data are forbidden."

    def get_output_policy(self, obj):
        return "Advisory output only; human confirmation is required."

    def get_review_owner(self, obj):
        return "architecture"

    def get_reviewed_at(self, obj):
        return None


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


class ContractCheckSerializer(StrictSerializer):
    contract_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), min_length=1, max_length=50,
    )
    sample_case = serializers.ChoiceField(choices=("success", "pagination", "400", "401", "403", "404", "409", "422"))


class AssistantEvaluationSerializer(StrictSerializer):
    scenario = serializers.ChoiceField(choices=("catalog_review", "readiness_summary", "risk_summary"))
    demo_input_ref = serializers.RegexField(r"^demo-[a-z0-9-]{1,100}$")
    version = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(min_length=1, max_length=500)
