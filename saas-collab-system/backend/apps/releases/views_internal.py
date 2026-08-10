from rest_framework.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.common.responses import success_response

from .models import ReleaseContract
from .permissions import (
    IsReleaseApprover,
    IsReleaseExecutor,
    IsReleaseManager,
    IsReleaseViewer,
    filter_release_scope,
)
from .serializers import (
    ReleaseActionSerializer,
    ReleaseApprovalDecisionSerializer,
    ReleaseApprovalSerializer,
    ReleaseArtifactSerializer,
    ReleaseBuildSerializer,
    ReleaseContractCreateSerializer,
    ReleaseContractDetailSerializer,
    ReleaseContractSummarySerializer,
    ReleaseGateRecordSerializer,
    ReleaseGateResultSerializer,
)
from .services import (
    confirm_release_build,
    create_release_contract,
    decide_release_approval,
    record_gate_result,
    submit_release_contract,
    transition_release,
)


def _idempotency_key(request):
    value = request.headers.get("Idempotency-Key", "").strip()
    if len(value) < 8 or len(value) > 120:
        raise ValidationError({"idempotency_key": "Idempotency-Key header must contain 8 to 120 characters."})
    return value


def _contracts(user, permission_code):
    return filter_release_scope(
        user,
        permission_code,
        ReleaseContract.objects.select_related("tenant", "created_by")
        .prefetch_related("gate_results", "approvals", "audit_events"),
    )


class ReleaseContractCollectionView(APIView):
    def get_permissions(self):
        permission = IsReleaseManager if self.request.method == "POST" else IsReleaseViewer
        return [IsAuthenticated(), permission()]

    def get(self, request):
        queryset = _contracts(request.user, "release.contract.view")
        status = request.query_params.get("status")
        environment = request.query_params.get("environment")
        if status:
            queryset = queryset.filter(status=status)
        if environment:
            queryset = queryset.filter(environment=environment)
        rows = queryset[:100]
        return success_response(
            {
                "count": queryset.count(),
                "results": ReleaseContractSummarySerializer(rows, many=True).data,
            }
        )

    def post(self, request):
        serializer = ReleaseContractCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        contract, replayed = create_release_contract(
            actor=request.user,
            payload=serializer.validated_data,
            idempotency_key=_idempotency_key(request),
        )
        return success_response(
            {
                "replayed": replayed,
                "contract": ReleaseContractDetailSerializer(contract).data,
            },
            status=200 if replayed else 201,
        )


class ReleaseContractDetailView(APIView):
    permission_classes = [IsAuthenticated, IsReleaseViewer]

    def get(self, request, pk):
        contract = get_object_or_404(_contracts(request.user, "release.contract.view"), pk=pk)
        return success_response(ReleaseContractDetailSerializer(contract).data)


class ReleaseGateRecordView(APIView):
    permission_classes = [IsAuthenticated, IsReleaseManager]

    def post(self, request, pk):
        contract = get_object_or_404(_contracts(request.user, "release.contract.manage"), pk=pk)
        serializer = ReleaseGateRecordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        gate, replayed = record_gate_result(
            contract=contract,
            actor=request.user,
            payload=serializer.validated_data,
            idempotency_key=_idempotency_key(request),
        )
        return success_response(
            {"replayed": replayed, "gate": ReleaseGateResultSerializer(gate).data},
            status=200 if replayed else 201,
        )


class ReleaseApprovalDecisionView(APIView):
    permission_classes = [IsAuthenticated, IsReleaseApprover]

    def post(self, request, pk):
        contract = get_object_or_404(_contracts(request.user, "release.contract.approve"), pk=pk)
        serializer = ReleaseApprovalDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        approval, contract, replayed = decide_release_approval(
            contract=contract,
            actor=request.user,
            payload=serializer.validated_data,
            idempotency_key=_idempotency_key(request),
        )
        return success_response(
            {
                "replayed": replayed,
                "approval": ReleaseApprovalSerializer(approval).data,
                "contract": ReleaseContractSummarySerializer(contract).data,
            },
            status=200 if replayed else 201,
        )


class ReleaseBuildConfirmView(APIView):
    permission_classes = [IsAuthenticated, IsReleaseExecutor]

    def post(self, request, pk):
        contract = get_object_or_404(_contracts(request.user, "release.contract.execute"), pk=pk)
        serializer = ReleaseBuildSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        artifact, contract, replayed = confirm_release_build(
            contract=contract,
            actor=request.user,
            payload=serializer.validated_data,
            idempotency_key=_idempotency_key(request),
        )
        return success_response(
            {
                "replayed": replayed,
                "artifact": ReleaseArtifactSerializer(artifact).data,
                "contract": ReleaseContractSummarySerializer(contract).data,
            },
            status=200 if replayed else 201,
        )


class ReleaseActionView(APIView):
    def get_permissions(self):
        permission = (
            IsReleaseManager
            if self.kwargs.get("action") in {"submit-review", "cancel"}
            else IsReleaseExecutor
        )
        return [IsAuthenticated(), permission()]

    def post(self, request, pk, action):
        permission_code = (
            "release.contract.manage"
            if action in {"submit-review", "cancel"}
            else "release.contract.execute"
        )
        contract = get_object_or_404(_contracts(request.user, permission_code), pk=pk)
        serializer = ReleaseActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if action == "submit-review":
            contract, replayed = submit_release_contract(
                contract=contract,
                actor=request.user,
                version=serializer.validated_data["version"],
                reason=serializer.validated_data["reason"],
                idempotency_key=_idempotency_key(request),
            )
        else:
            contract, replayed = transition_release(
                contract=contract,
                actor=request.user,
                action=action,
                payload=serializer.validated_data,
                idempotency_key=_idempotency_key(request),
            )
        return success_response(
            {
                "replayed": replayed,
                "contract": ReleaseContractDetailSerializer(contract).data,
            }
        )
