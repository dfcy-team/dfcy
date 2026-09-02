"""HTTP endpoints for real, asynchronous assistant evaluations."""

import hashlib
import json

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.conf import settings
from rest_framework import status
from rest_framework.views import APIView

from apps.audit.services import write_operation_log
from apps.common.error_codes import ErrorCode
from apps.common.exceptions import ContractViolation, DataScopeDenied, StateConflict, get_scoped_object_or_404
from apps.common.responses import paginated_data, success_response
from apps.permissions.api_permissions import DeclaredApplicationPermission
from apps.permissions.ui_p7_scopes import filter_assistants

from .execution import _save_job
from .models import AssistantDefinition, AssistantEvaluationJob
from .serializers import (
    AssistantEvaluationJobSerializer,
    AssistantEvaluationRequestSerializer,
)
from .tasks import run_assistant_evaluation


def _require_idempotency_key(request):
    value = request.headers.get("Idempotency-Key", "").strip()
    if not 16 <= len(value) <= 128:
        raise ContractViolation(
            "Idempotency-Key length must be between 16 and 128.",
            error_code=ErrorCode.FIELD_VALIDATION_FAILED,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return value


def _fingerprint(assistant, data):
    canonical = {
        "assistant_id": assistant.pk,
        "assistant_version": assistant.version,
        "scenario": data["scenario"],
        "input": data["input"],
        "expected_output": data["expected_output"],
        "version": data["version"],
        "reason": data["reason"],
    }
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _assistant_queryset(request, permission_code):
    queryset = AssistantDefinition.objects.filter(Q(tenant__isnull=True) | Q(tenant=request.user.tenant))
    return filter_assistants(request.user, queryset, permission_code)


def _enqueue(job_id):
    """Submit a durable task and record only its public Celery id."""

    try:
        result = run_assistant_evaluation.apply_async(args=[job_id])
    except Exception:
        # The job remains queryable and explicitly failed rather than being
        # reported as queued when the broker is unavailable.
        job = AssistantEvaluationJob.objects.get(pk=job_id)
        if job.status == AssistantEvaluationJob.Status.QUEUED:
            job.status = AssistantEvaluationJob.Status.FAILED
            job.error_code = "QUEUE_UNAVAILABLE"
            job.error_message = "Evaluation queue is unavailable."
            _save_job(job, ["status", "error_code", "error_message"])
        return None
    job = AssistantEvaluationJob.objects.get(pk=job_id)
    if not job.celery_task_id:
        job.celery_task_id = str(result.id)
        _save_job(job, ["celery_task_id"])
    return result


class AssistantEvaluateView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    write_permission_code = "governance.assistants.evaluate"

    def post(self, request, pk):
        idempotency_key = _require_idempotency_key(request)
        assistant = get_scoped_object_or_404(_assistant_queryset(request, self.write_permission_code), pk=pk)
        serializer = AssistantEvaluationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data["version"] != assistant.version:
            error = StateConflict("Assistant version changed; refresh before evaluating.")
            error.error_code = ErrorCode.VERSION_CONFLICT
            raise error
        if assistant.status != AssistantDefinition.Status.SANDBOX:
            error = StateConflict("Only sandbox-approved assistants can be evaluated by the production provider.")
            error.error_code = ErrorCode.POLICY_VIOLATION
            raise error
        allowed_data_classes = {
            str(value).strip()
            for value in (getattr(settings, "GOVERNANCE_EVALUATION_DATA_CLASSES", ("public_demo",)) or ())
            if str(value).strip()
        }
        if assistant.data_class not in allowed_data_classes:
            error = StateConflict("Only explicitly allow-listed public-demo assistants can be evaluated.")
            error.error_code = ErrorCode.POLICY_VIOLATION
            raise error

        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        fingerprint = _fingerprint(assistant, data)
        with transaction.atomic():
            existing = AssistantEvaluationJob.objects.select_for_update().filter(
                tenant=request.user.tenant,
                idempotency_key_hash=digest,
            ).first()
            if existing:
                if existing.request_fingerprint != fingerprint:
                    error = StateConflict("Idempotency key was reused with different evaluation data.")
                    error.error_code = ErrorCode.IDEMPOTENCY_CONFLICT
                    raise error
                replay = True
                job = existing
            else:
                try:
                    job = AssistantEvaluationJob.objects.create(
                        tenant=request.user.tenant,
                        assistant=assistant,
                        requested_by=request.user,
                        scenario=data["scenario"],
                        demo_input_ref="synthetic-input",
                        test_input=data["input"],
                        expected_output=data["expected_output"],
                        reason=data["reason"],
                        assistant_version=assistant.version,
                        idempotency_key_hash=digest,
                        request_fingerprint=fingerprint,
                    )
                except IntegrityError as exc:
                    raise StateConflict("Evaluation idempotency conflict.") from exc
                write_operation_log(
                    tenant=request.user.tenant,
                    user=request.user,
                    module="governance",
                    action="assistant_evaluate_queued",
                    object_type="assistant_evaluation_job",
                    object_id=job.id,
                    after_data={
                        "status": job.status,
                        "assistant_id": assistant.id,
                        "assistant_version": assistant.version,
                        "scenario": job.scenario,
                    },
                )
                replay = False
                transaction.on_commit(lambda job_id=job.id: _enqueue(job_id))
        payload = AssistantEvaluationJobSerializer(job).data
        payload["idempotent_replay"] = replay
        return success_response(payload, status=status.HTTP_200_OK if replay else status.HTTP_202_ACCEPTED)


class AssistantEvaluationJobDetailView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "governance.assistants.view"

    def get(self, request, pk):
        queryset = AssistantEvaluationJob.objects.filter(
            tenant=request.user.tenant,
            assistant__in=_assistant_queryset(request, self.read_permission_code),
        ).select_related("assistant")
        job = get_scoped_object_or_404(queryset, pk=pk)
        return success_response(AssistantEvaluationJobSerializer(job).data)


class AssistantEvaluationJobCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "governance.assistants.view"

    def get(self, request):
        unknown = set(request.query_params) - {"page", "page_size", "assistant_id", "status"}
        if unknown:
            raise ContractViolation(
                f"Unknown query parameters: {', '.join(sorted(unknown))}.",
                error_code=ErrorCode.UNKNOWN_FIELD,
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        queryset = AssistantEvaluationJob.objects.filter(
            tenant=request.user.tenant,
            assistant__in=_assistant_queryset(request, self.read_permission_code),
        ).select_related("assistant")
        assistant_id = request.query_params.get("assistant_id")
        if assistant_id:
            try:
                queryset = queryset.filter(assistant_id=int(assistant_id))
            except (TypeError, ValueError):
                raise ContractViolation(
                    "assistant_id must be an integer.",
                    error_code=ErrorCode.FIELD_VALIDATION_FAILED,
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
        requested_status = request.query_params.get("status", "")
        if requested_status:
            if requested_status not in AssistantEvaluationJob.Status.values:
                raise ContractViolation(
                    "Unknown evaluation job status.",
                    error_code=ErrorCode.FIELD_VALIDATION_FAILED,
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                )
            queryset = queryset.filter(status=requested_status)
        try:
            page = max(1, int(request.query_params.get("page", 1)))
            page_size = min(100, max(1, int(request.query_params.get("page_size", 20))))
        except (TypeError, ValueError):
            raise ContractViolation(
                "Pagination values must be integers.",
                error_code=ErrorCode.INVALID_PAGINATION,
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        return success_response(paginated_data(request, queryset, AssistantEvaluationJobSerializer, page=page, page_size=page_size))
