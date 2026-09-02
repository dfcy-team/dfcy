"""Production execution endpoints for the governed pilot workflows."""

from django.db import transaction
from django.db.models import Q
from rest_framework.permissions import BasePermission
from rest_framework.views import APIView
from rest_framework import status

from apps.common.error_codes import ErrorCode
from apps.common.exceptions import ContractViolation, DataScopeDenied, get_scoped_object_or_404
from apps.common.responses import paginated_data, success_response
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from apps.permissions.api_permissions import DeclaredApplicationPermission
from apps.permissions.ui_p7_scopes import filter_plan_queryset
from apps.permissions.ui_p8_scopes import filter_resource_queryset
from apps.accounts.models import CustomUser

from .execution import (
    _finish_execution,
    _save_execution,
    create_pilot_execution,
)
from .models import PerformanceRun, PilotExecution, RecoveryPlan, ReleasePlan
from .serializers import (
    PilotExecutionSerializer,
    ProductionExecutionSerializer,
    ProductionRollbackExecutionSerializer,
)
from .tasks import execute_pilot_execution


def _idempotency_key(request):
    value = request.headers.get("Idempotency-Key", "").strip()
    if not 16 <= len(value) <= 128:
        raise ContractViolation(
            "Idempotency-Key length must be between 16 and 128.",
            error_code=ErrorCode.FIELD_VALIDATION_FAILED,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return value


def _enqueue(execution_id):
    try:
        result = execute_pilot_execution.apply_async(args=[execution_id])
    except Exception:
        # Source plans already entered a controlled running state for deploy or
        # recovery.  Finish through the same state service so a broker outage
        # cannot leave an apparently running operation without intervention.
        _finish_execution(
            execution_id,
            {
                "status": "failed",
                "runner_job_id": "",
                "runner_reference": "",
                "result_metrics": {},
                "evidence_refs": [],
                "result_summary": "Execution queue is unavailable.",
            },
            error_code_override="QUEUE_UNAVAILABLE",
        )
        return None
    execution = PilotExecution.objects.get(pk=execution_id)
    if not execution.celery_task_id:
        execution.celery_task_id = str(result.id)
        _save_execution(execution, ["celery_task_id"])
    return result


def _filtered_performance(request, permission):
    return filter_resource_queryset(
        request.user,
        PerformanceRun.objects.select_related("environment", "reviewer"),
        permission,
        "performance_run_ids",
    )


def _filtered_recovery(request, permission):
    return filter_plan_queryset(
        request.user,
        RecoveryPlan.objects.select_related("environment", "created_by", "approved_by"),
        permission,
        plan_key="recovery_plan_ids",
    )


def _filtered_release(request, permission):
    return filter_plan_queryset(
        request.user,
        ReleasePlan.objects.select_related("environment", "created_by", "approved_by", "rollback_approved_by"),
        permission,
        plan_key="release_plan_ids",
        channel_field="release_channel",
    )


class _ExecutionEndpoint(APIView):
    permission_classes = [DeclaredApplicationPermission]
    execution_type = None
    permission_code = None
    serializer_class = ProductionExecutionSerializer

    def get_permissions(self):
        self.write_permission_code = self.permission_code
        return super().get_permissions()

    def _source(self, request, pk):
        raise NotImplementedError

    def post(self, request, pk):
        source = self._source(request, pk)
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        key = _idempotency_key(request)
        execution, replay = create_pilot_execution(
            actor=request.user,
            source=source,
            execution_type=self.execution_type,
            payload=serializer.validated_data,
            idempotency_key=key,
        )
        if not replay:
            transaction.on_commit(lambda execution_id=execution.id: _enqueue(execution_id))
        payload = PilotExecutionSerializer(execution).data
        payload["idempotent_replay"] = replay
        return success_response(payload, status=status.HTTP_200_OK if replay else status.HTTP_202_ACCEPTED)


class PerformanceExecutionView(_ExecutionEndpoint):
    execution_type = PilotExecution.ExecutionType.PERFORMANCE
    permission_code = "pilot.performance.execute"

    def _source(self, request, pk):
        return get_scoped_object_or_404(_filtered_performance(request, self.permission_code), pk=pk)


class RecoveryExecutionView(_ExecutionEndpoint):
    execution_type = PilotExecution.ExecutionType.RECOVERY
    permission_code = "pilot.recovery.execute"

    def _source(self, request, pk):
        return get_scoped_object_or_404(_filtered_recovery(request, self.permission_code), pk=pk)


class ReleaseExecutionView(_ExecutionEndpoint):
    execution_type = PilotExecution.ExecutionType.DEPLOY
    permission_code = "pilot.release.execute"

    def _source(self, request, pk):
        return get_scoped_object_or_404(_filtered_release(request, self.permission_code), pk=pk)


class ReleaseRollbackExecutionView(_ExecutionEndpoint):
    execution_type = PilotExecution.ExecutionType.ROLLBACK
    permission_code = "pilot.release.rollback.execute"
    serializer_class = ProductionRollbackExecutionSerializer

    def _source(self, request, pk):
        return get_scoped_object_or_404(_filtered_release(request, self.permission_code), pk=pk)


class PilotExecutionReadPermission(BasePermission):
    """Read requires the source-specific view permission and its scope."""

    codes = (
        "pilot.performance.view",
        "pilot.recovery.view",
        "pilot.release.view",
    )

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.user_type == CustomUser.UserType.INTERNAL
            and any(check_user_permission(request.user, code) and get_permission_data_scopes(request.user, code) for code in self.codes)
        )


def _execution_in_scope(request, execution):
    if execution.execution_type == PilotExecution.ExecutionType.PERFORMANCE and execution.performance_run_id:
        return _filtered_performance(request, "pilot.performance.view").filter(pk=execution.performance_run_id).exists()
    if execution.execution_type == PilotExecution.ExecutionType.RECOVERY and execution.recovery_plan_id:
        return _filtered_recovery(request, "pilot.recovery.view").filter(pk=execution.recovery_plan_id).exists()
    if execution.release_plan_id:
        return _filtered_release(request, "pilot.release.view").filter(pk=execution.release_plan_id).exists()
    return False


class PilotExecutionDetailView(APIView):
    permission_classes = [PilotExecutionReadPermission]

    def get(self, request, pk):
        execution = get_scoped_object_or_404(
            PilotExecution.objects.select_related(
                "performance_run", "recovery_plan", "recovery_drill", "release_plan",
            ).filter(tenant=request.user.tenant),
            pk=pk,
        )
        if not _execution_in_scope(request, execution):
            raise DataScopeDenied("Execution is outside the authorized data scope.")
        return success_response(PilotExecutionSerializer(execution).data)


class PilotExecutionCollectionView(APIView):
    permission_classes = [PilotExecutionReadPermission]

    def get(self, request):
        unknown = set(request.query_params) - {"page", "page_size", "execution_type", "status"}
        if unknown:
            raise ContractViolation(
                f"Unknown query parameters: {', '.join(sorted(unknown))}.",
                error_code=ErrorCode.UNKNOWN_FIELD,
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        queryset = PilotExecution.objects.filter(tenant=request.user.tenant).select_related(
            "performance_run", "recovery_plan", "recovery_drill", "release_plan",
        )
        visible = Q(pk__in=[])
        if check_user_permission(request.user, "pilot.performance.view") and get_permission_data_scopes(request.user, "pilot.performance.view"):
            visible |= Q(performance_run__in=_filtered_performance(request, "pilot.performance.view"))
        if check_user_permission(request.user, "pilot.recovery.view") and get_permission_data_scopes(request.user, "pilot.recovery.view"):
            visible |= Q(recovery_plan__in=_filtered_recovery(request, "pilot.recovery.view"))
        if check_user_permission(request.user, "pilot.release.view") and get_permission_data_scopes(request.user, "pilot.release.view"):
            visible |= Q(release_plan__in=_filtered_release(request, "pilot.release.view"))
        queryset = queryset.filter(visible)
        execution_type = request.query_params.get("execution_type")
        if execution_type:
            if execution_type not in PilotExecution.ExecutionType.values:
                raise ContractViolation(
                    "Unknown execution type.",
                    error_code=ErrorCode.FIELD_VALIDATION_FAILED,
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
            queryset = queryset.filter(execution_type=execution_type)
        execution_status = request.query_params.get("status")
        if execution_status:
            if execution_status not in PilotExecution.Status.values:
                raise ContractViolation(
                    "Unknown execution status.",
                    error_code=ErrorCode.FIELD_VALIDATION_FAILED,
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
            queryset = queryset.filter(status=execution_status)
        try:
            page = max(1, int(request.query_params.get("page", 1)))
            page_size = min(100, max(1, int(request.query_params.get("page_size", 20))))
        except (TypeError, ValueError):
            raise ContractViolation(
                "Pagination values must be integers.",
                error_code=ErrorCode.INVALID_PAGINATION,
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        return success_response(paginated_data(request, queryset, PilotExecutionSerializer, page=page, page_size=page_size))
