from rest_framework import status
from rest_framework.views import APIView
from django.db.models import Q

from apps.audit.services import write_operation_log
from apps.common.error_codes import ErrorCode
from apps.common.exceptions import ContractViolation, DataScopeDenied, get_scoped_object_or_404
from apps.common.responses import paginated_data, success_response
from apps.permissions.api_permissions import DeclaredApplicationPermission
from apps.permissions.ui_p7_scopes import filter_api_contracts, filter_assistants

from .models import ApiContract, AssistantDefinition
from .serializers import (
    ApiContractDetailSerializer,
    ApiContractSummarySerializer,
    AssistantDetailSerializer,
    AssistantEvaluationSerializer,
    AssistantSummarySerializer,
    ContractCheckSerializer,
)


def contract_error(message, code, http_status):
    raise ContractViolation(message, error_code=code, status_code=http_status)


def positive_int(value, *, default, maximum=None):
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        contract_error("Pagination values must be integers.", ErrorCode.INVALID_PAGINATION, status.HTTP_400_BAD_REQUEST)
    if parsed < 1 or (maximum is not None and parsed > maximum):
        contract_error("Pagination value is outside the allowed range.", ErrorCode.INVALID_PAGINATION, status.HTTP_400_BAD_REQUEST)
    return parsed


def validate_query(request, allowed):
    unknown = set(request.query_params) - set(allowed)
    if unknown:
        contract_error(f"Unknown query parameters: {', '.join(sorted(unknown))}.", ErrorCode.UNKNOWN_FIELD, status.HTTP_400_BAD_REQUEST)


def require_idempotency_key(request):
    value = request.headers.get("Idempotency-Key", "")
    if not 16 <= len(value) <= 128:
        contract_error("Idempotency-Key length must be between 16 and 128.", ErrorCode.FIELD_VALIDATION_FAILED, status.HTTP_422_UNPROCESSABLE_ENTITY)
    return value


def _contract_violations(contract):
    violations = []
    schemas = {
        "request_fields": {"name", "location", "type", "required", "nullable", "enum_values", "item_type", "schema_ref", "min_length", "max_length", "minimum", "maximum", "pattern", "description"},
        "response_fields": {"field_path", "type", "required", "nullable", "enum_values", "item_type", "schema_ref", "description"},
        "error_codes": {"http_status", "code", "condition", "field", "retryable"},
        "change_history": {"version", "change_type", "summary", "changed_at", "owner", "deprecation_at"},
    }
    for field_name, required_fields in schemas.items():
        values = getattr(contract, field_name)
        if not isinstance(values, list):
            violations.append({"contract_id": contract.id, "field": field_name, "code": "INVALID_ARRAY"})
            continue
        for item in values:
            if not isinstance(item, dict) or set(item) != required_fields:
                violations.append({"contract_id": contract.id, "field": field_name, "code": "SCHEMA_FIELD_MISMATCH"})
                break
    return violations


class ApiContractCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "governance.api.view"

    def get(self, request):
        validate_query(request, {"page", "page_size", "module", "status", "version", "search", "ordering"})
        queryset = ApiContract.objects.filter(Q(tenant__isnull=True) | Q(tenant=request.user.tenant))
        queryset = filter_api_contracts(request.user, queryset, self.read_permission_code)
        for field in ("module", "status", "version"):
            value = request.query_params.get(field, "").strip()
            if value:
                queryset = queryset.filter(**{field: value})
        requested_status = request.query_params.get("status", "").strip()
        if requested_status and requested_status not in ApiContract.Status.values:
            contract_error("Unknown API contract status.", ErrorCode.FIELD_VALIDATION_FAILED, status.HTTP_422_UNPROCESSABLE_ENTITY)
        search = request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(module__icontains=search) | Q(path__icontains=search))
        ordering = request.query_params.get("ordering", "module")
        if ordering not in {"module", "-updated_at"}:
            contract_error("Unsupported ordering.", ErrorCode.FIELD_VALIDATION_FAILED, status.HTTP_422_UNPROCESSABLE_ENTITY)
        queryset = queryset.order_by(ordering, "id")
        page = positive_int(request.query_params.get("page"), default=1)
        page_size = positive_int(request.query_params.get("page_size"), default=20, maximum=100)
        return success_response(paginated_data(request, queryset, ApiContractSummarySerializer, page=page, page_size=page_size))


class ApiContractDetailView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "governance.api.view"

    def get(self, request, pk):
        queryset = ApiContract.objects.filter(Q(tenant__isnull=True) | Q(tenant=request.user.tenant))
        queryset = filter_api_contracts(request.user, queryset, self.read_permission_code)
        contract = get_scoped_object_or_404(queryset, pk=pk)
        return success_response(ApiContractDetailSerializer(contract).data)


class ApiContractCheckMockView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    write_permission_code = "governance.api.check"

    def post(self, request):
        require_idempotency_key(request)
        serializer = ContractCheckSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        queryset = ApiContract.objects.filter(
            Q(tenant__isnull=True) | Q(tenant=request.user.tenant),
            pk__in=serializer.validated_data["contract_ids"],
        )
        queryset = filter_api_contracts(request.user, queryset, self.write_permission_code)
        contracts = list(queryset)
        if len(contracts) != len(set(serializer.validated_data["contract_ids"])):
            raise DataScopeDenied("One or more contracts are outside the authorized scope.")
        violations = [item for contract in contracts for item in _contract_violations(contract)]
        write_operation_log(
            tenant=request.user.tenant,
            user=request.user,
            module="governance",
            action="check_mock",
            object_type="api_contract",
            after_data={"sample_case": serializer.validated_data["sample_case"], "checked_count": len(contracts)},
        )
        return success_response({
            "checked_count": len(contracts),
            "passed_count": len(contracts) - len({item["contract_id"] for item in violations}),
            "violations": violations,
            "evidence_status": "fixed_demo",
            "api_status": "mock",
        })


class AssistantCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "governance.assistants.view"

    def get(self, request):
        validate_query(request, {"page", "page_size", "status", "data_class", "search", "ordering"})
        queryset = AssistantDefinition.objects.filter(Q(tenant__isnull=True) | Q(tenant=request.user.tenant))
        queryset = filter_assistants(request.user, queryset, self.read_permission_code)
        for field in ("status", "data_class"):
            value = request.query_params.get(field, "").strip()
            if value:
                queryset = queryset.filter(**{field: value})
        requested_status = request.query_params.get("status", "").strip()
        if requested_status and requested_status not in AssistantDefinition.Status.values:
            contract_error("Unknown assistant status.", ErrorCode.FIELD_VALIDATION_FAILED, status.HTTP_422_UNPROCESSABLE_ENTITY)
        search = request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(code__icontains=search))
        ordering = request.query_params.get("ordering", "code")
        if ordering not in {"code", "-updated_at"}:
            contract_error("Unsupported ordering.", ErrorCode.FIELD_VALIDATION_FAILED, status.HTTP_422_UNPROCESSABLE_ENTITY)
        page = positive_int(request.query_params.get("page"), default=1)
        page_size = positive_int(request.query_params.get("page_size"), default=20, maximum=100)
        return success_response(paginated_data(request, queryset.order_by(ordering, "id"), AssistantSummarySerializer, page=page, page_size=page_size))


class AssistantDetailView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "governance.assistants.view"

    def get(self, request, pk):
        queryset = AssistantDefinition.objects.filter(Q(tenant__isnull=True) | Q(tenant=request.user.tenant))
        queryset = filter_assistants(request.user, queryset, self.read_permission_code)
        assistant = get_scoped_object_or_404(queryset, pk=pk)
        return success_response(AssistantDetailSerializer(assistant).data)


class AssistantEvaluateMockView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    write_permission_code = "governance.assistants.evaluate"

    def post(self, request, pk):
        require_idempotency_key(request)
        queryset = AssistantDefinition.objects.filter(Q(tenant__isnull=True) | Q(tenant=request.user.tenant))
        queryset = filter_assistants(request.user, queryset, self.write_permission_code)
        assistant = get_scoped_object_or_404(queryset, pk=pk)
        serializer = AssistantEvaluationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data["version"] != assistant.version:
            from apps.common.exceptions import StateConflict
            raise StateConflict("Assistant version changed; refresh before evaluating.")
        write_operation_log(
            tenant=request.user.tenant,
            user=request.user,
            module="governance",
            action="assistant_evaluate_mock",
            object_type="assistant",
            object_id=assistant.pk,
            after_data={"scenario": serializer.validated_data["scenario"], "demo_input_ref": serializer.validated_data["demo_input_ref"]},
        )
        return success_response({
            "assistant_id": assistant.id,
            "recommendation": "Demo-only governance recommendation; human review is required.",
            "limitations": assistant.limitations or ["No external model", "No tool calls", "No business writes"],
            "confidence": 0.5,
            "human_confirmation_required": True,
            "tool_calls": [],
            "business_writes": [],
            "api_status": "mock",
        })
