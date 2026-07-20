import hashlib
import uuid
from datetime import timedelta

from django.db import IntegrityError
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.fields import DateTimeField
from rest_framework.views import APIView

from apps.audit.services import write_operation_log
from apps.common.error_codes import ErrorCode
from apps.common.exceptions import ContractViolation, StateConflict, get_scoped_object_or_404
from apps.common.responses import paginated_data, success_response
from apps.permissions.api_permissions import DeclaredApplicationPermission
from apps.permissions.ui_p7_scopes import (
    environment_allowed,
    filter_environment_queryset,
    filter_plan_queryset,
    values_allowed,
)

from .models import (
    CapacityObservation,
    PilotEnvironment,
    ReadinessGate,
    RecoveryDrill,
    RecoveryPlan,
    ReleasePlan,
    TopologyService,
)
from .serializers import (
    ApprovalSerializer,
    CapacityObservationSerializer,
    RecoveryCreateSerializer,
    RecoveryDrillSerializer,
    RecoveryPlanSerializer,
    RecoveryResultSerializer,
    ReleaseCreateSerializer,
    ReleasePlanSerializer,
    ReleaseResultSerializer,
    ResumeSerializer,
    RollbackApprovalSerializer,
    RollbackResultSerializer,
    RollbackResumeSerializer,
    ScheduleSerializer,
    TopologyVerifySerializer,
    TopologyServiceSerializer,
    VersionReasonSerializer,
)
from .services import (
    audit_plan_creation_failure,
    audit_plan_creation,
    audit_action_failure,
    key_hash,
    record_recovery_result,
    transition_recovery,
    transition_release,
    validate_release_payload,
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


def _environment_for(request, permission_code, code):
    if not environment_allowed(request.user, permission_code, code):
        from apps.common.exceptions import DataScopeDenied
        raise DataScopeDenied("Environment is outside the authorized data scope.")
    return get_scoped_object_or_404(PilotEnvironment.objects.all(), code=code)


def _gate_payload(gate, now):
    status = gate.status
    if not gate.expires_at or gate.expires_at <= now:
        status = ReadinessGate.Status.EXPIRED
    return {
        "gate_code": gate.code,
        "name": gate.name,
        "status": status,
        "evidence_at": gate.evaluated_at,
        "expires_at": gate.expires_at,
        "blockers": [gate.message] if gate.message and status in {ReadinessGate.Status.FAILED, ReadinessGate.Status.BLOCKED, ReadinessGate.Status.EXPIRED} else [],
        "owner": "architecture",
        "evidence_refs": [gate.evidence_ref] if gate.evidence_ref else [],
    }


class ReadinessView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "pilot.readiness.view"

    def get(self, request):
        validate_query(request, {"environment_id", "gate_code", "status"})
        environment_code = request.query_params.get("environment_id", "controlled-pilot")
        environment = _environment_for(request, self.read_permission_code, environment_code)
        gates = filter_environment_queryset(
            request.user,
            environment.readiness_gates.all(),
            self.read_permission_code,
            gate_field="code",
        )
        gate_code = request.query_params.get("gate_code", "").strip()
        requested_status = request.query_params.get("status", "").strip()
        if requested_status and requested_status not in ReadinessGate.Status.values:
            contract_error("Unknown readiness status.", ErrorCode.FIELD_VALIDATION_FAILED, status.HTTP_422_UNPROCESSABLE_ENTITY)
        if gate_code:
            gates = gates.filter(code=gate_code)
        now = timezone.now()
        payloads = [_gate_payload(gate, now) for gate in gates]
        if requested_status:
            payloads = [gate for gate in payloads if gate["status"] == requested_status]
        statuses = {gate["status"] for gate in payloads}
        if payloads and statuses == {ReadinessGate.Status.PASSED}:
            overall = ReadinessGate.Status.PASSED
        elif statuses & {ReadinessGate.Status.FAILED, ReadinessGate.Status.BLOCKED, ReadinessGate.Status.EXPIRED}:
            overall = ReadinessGate.Status.BLOCKED
        elif statuses:
            overall = ReadinessGate.Status.IN_PROGRESS
        else:
            overall = ReadinessGate.Status.NOT_STARTED
        return success_response({
            "environment_id": environment.code,
            "overall_status": overall,
            "evaluated_at": now,
            "gates": payloads,
            "api_status": "sandbox",
        })


class TopologyView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "pilot.topology.view"

    def get(self, request):
        validate_query(request, {"environment_id", "service_name"})
        environment_code = request.query_params.get("environment_id", "controlled-pilot")
        environment = _environment_for(request, self.read_permission_code, environment_code)
        queryset = TopologyService.objects.filter(environment=environment)
        queryset = filter_environment_queryset(
            request.user,
            queryset,
            self.read_permission_code,
            service_field="service_name",
            network_zone_field="network_zone",
        )
        service_name = request.query_params.get("service_name", "").strip()
        if service_name:
            queryset = queryset.filter(service_name=service_name)
        services = TopologyServiceSerializer(queryset, many=True).data
        return success_response({"environment_id": environment.code, "generated_at": timezone.now(), "services": services, "api_status": "sandbox"})


class TopologyVerifyMockView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    write_permission_code = "pilot.topology.verify"

    def post(self, request):
        require_idempotency_key(request)
        serializer = TopologyVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        _environment_for(request, self.write_permission_code, data["environment_id"])
        violations = []
        for item in data["services"]:
            if not values_allowed(
                request.user,
                self.write_permission_code,
                environment_ids=data["environment_id"],
                service_names=item["service_name"],
                network_zones=item["network_zone"],
            ):
                from apps.common.exceptions import DataScopeDenied
                raise DataScopeDenied("Topology service is outside the authorized data scope.")
            expected_role = "database" if item["service_name"] == "mysql" else "application"
            expected_zone = "controlled_db" if expected_role == "database" else "controlled_app"
            if item["host_role"] != expected_role or item["network_zone"] != expected_zone:
                violations.append({"service_name": item["service_name"], "code": "TOPOLOGY_ROLE_MISMATCH", "message": "Service is assigned to the wrong controlled host role or network zone."})
            if item["service_name"] in {"mysql", "redis", "backend"} and item["exposure"] not in {"loopback", "app_host_only", "none"}:
                violations.append({"service_name": item["service_name"], "code": "TOPOLOGY_EXPOSURE_INVALID", "message": "Internal service exposure is not allowed."})
        write_operation_log(
            tenant=request.user.tenant,
            user=request.user,
            module="pilot",
            action="topology_verify_mock",
            object_type="pilot_environment",
            object_id=data["environment_id"],
            after_data={"valid": not violations, "service_count": len(data["services"])},
        )
        return success_response({"valid": not violations, "violations": violations, "checked_at": timezone.now(), "evidence_status": "fixed_demo", "api_status": "mock"})


class CapacitySummaryView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "pilot.capacity.view"

    def get(self, request):
        validate_query(request, {"environment_id", "window_minutes"})
        environment_code = request.query_params.get("environment_id", "controlled-pilot")
        window = positive_int(request.query_params.get("window_minutes"), default=15, maximum=1440)
        if window not in {5, 15, 60, 1440}:
            contract_error("Window must be 5, 15, 60, or 1440.", ErrorCode.FIELD_VALIDATION_FAILED, status.HTTP_422_UNPROCESSABLE_ENTITY)
        environment = _environment_for(request, self.read_permission_code, environment_code)
        cutoff = timezone.now() - timedelta(minutes=window)
        queryset = CapacityObservation.objects.filter(environment=environment, observed_at__gte=cutoff)
        queryset = filter_environment_queryset(request.user, queryset, self.read_permission_code, service_field="service_name", metric_field="metric_code")
        latest = {}
        for observation in queryset:
            latest.setdefault((observation.service_name, observation.metric_code), observation)
        metrics = CapacityObservationSerializer(list(latest.values()), many=True).data
        statuses = {metric["status"] for metric in metrics}
        quality = "missing" if not metrics else ("partial" if statuses - {"normal"} else "valid")
        return success_response({"environment_id": environment.code, "window_minutes": window, "generated_at": timezone.now(), "quality_status": quality, "metrics": metrics, "api_status": "sandbox"})


class CapacityObservationListView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "pilot.capacity.view"

    def get(self, request):
        validate_query(request, {"page", "page_size", "environment_id", "service_name", "metric_code", "status", "observed_from", "observed_to", "ordering"})
        queryset = CapacityObservation.objects.all()
        queryset = filter_environment_queryset(request.user, queryset, self.read_permission_code, service_field="service_name", metric_field="metric_code")
        requested_metric = request.query_params.get("metric_code", "")
        requested_status = request.query_params.get("status", "")
        if requested_metric and requested_metric not in {"cpu_percent", "memory_percent", "http_rps", "queue_depth", "db_connections"}:
            contract_error("Unknown metric code.", ErrorCode.FIELD_VALIDATION_FAILED, status.HTTP_422_UNPROCESSABLE_ENTITY)
        if requested_status and requested_status not in {"normal", "warning", "critical", "unknown", "stale"}:
            contract_error("Unknown capacity status.", ErrorCode.FIELD_VALIDATION_FAILED, status.HTTP_422_UNPROCESSABLE_ENTITY)
        observed_from = request.query_params.get("observed_from")
        observed_to = request.query_params.get("observed_to")
        try:
            observed_from = DateTimeField().to_internal_value(observed_from) if observed_from else None
            observed_to = DateTimeField().to_internal_value(observed_to) if observed_to else None
        except Exception:
            contract_error("Observation times must be timezone-aware ISO 8601 values.", ErrorCode.FIELD_VALIDATION_FAILED, status.HTTP_422_UNPROCESSABLE_ENTITY)
        filters = {
            "environment__code": request.query_params.get("environment_id"),
            "service_name": request.query_params.get("service_name"),
            "metric_code": request.query_params.get("metric_code"),
            "status": requested_status,
            "observed_at__gte": observed_from,
            "observed_at__lte": observed_to,
        }
        for key, value in filters.items():
            if value:
                queryset = queryset.filter(**{key: value})
        ordering = request.query_params.get("ordering", "-observed_at")
        if ordering not in {"observed_at", "-observed_at"}:
            contract_error("Unsupported ordering.", ErrorCode.FIELD_VALIDATION_FAILED, status.HTTP_422_UNPROCESSABLE_ENTITY)
        page = positive_int(request.query_params.get("page"), default=1)
        page_size = positive_int(request.query_params.get("page_size"), default=20, maximum=100)
        return success_response(paginated_data(request, queryset.order_by(ordering, "id"), CapacityObservationSerializer, page=page, page_size=page_size))


def _recovery_queryset(request, permission_code):
    queryset = RecoveryPlan.objects.filter(tenant=request.user.tenant).select_related("environment", "created_by", "approved_by")
    return filter_plan_queryset(request.user, queryset, permission_code, plan_key="recovery_plan_ids")


def _release_queryset(request, permission_code):
    queryset = ReleasePlan.objects.filter(tenant=request.user.tenant).select_related("environment", "created_by", "approved_by", "rollback_approved_by")
    return filter_plan_queryset(request.user, queryset, permission_code, plan_key="release_plan_ids", channel_field="release_channel")


class RecoveryPlanCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "pilot.recovery.view"
    write_permission_code = "pilot.recovery.plan"

    def get(self, request):
        validate_query(request, {"page", "page_size", "environment_id", "status", "ordering"})
        queryset = _recovery_queryset(request, self.read_permission_code)
        if request.query_params.get("environment_id"):
            queryset = queryset.filter(environment__code=request.query_params["environment_id"])
        requested_status = request.query_params.get("status", "")
        if requested_status:
            if requested_status not in RecoveryPlan.Status.values:
                contract_error("Unknown recovery status.", ErrorCode.FIELD_VALIDATION_FAILED, status.HTTP_422_UNPROCESSABLE_ENTITY)
            queryset = queryset.filter(status=requested_status)
        ordering = request.query_params.get("ordering", "-created_at")
        if ordering not in {"created_at", "-created_at", "scheduled_at"}:
            contract_error("Unsupported ordering.", ErrorCode.FIELD_VALIDATION_FAILED, status.HTTP_422_UNPROCESSABLE_ENTITY)
        page = positive_int(request.query_params.get("page"), default=1)
        page_size = positive_int(request.query_params.get("page_size"), default=20, maximum=100)
        return success_response(paginated_data(request, queryset.order_by(ordering, "id"), RecoveryPlanSerializer, page=page, page_size=page_size))

    def post(self, request):
        audit_idempotency_key = request.headers.get("Idempotency-Key", "").strip() or f"missing:{uuid.uuid4().hex}"
        try:
            idempotency_key = require_idempotency_key(request)
            serializer = RecoveryCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            environment_code = data.pop("environment_id")
            environment = _environment_for(request, self.write_permission_code, environment_code)
            if not values_allowed(request.user, self.write_permission_code, environment_ids=environment_code):
                from apps.common.exceptions import DataScopeDenied
                raise DataScopeDenied("Recovery creation is outside the authorized data scope.")
            digest = key_hash(idempotency_key)
            existing = RecoveryPlan.objects.filter(tenant=request.user.tenant, idempotency_key_hash=digest).first()
            if existing:
                comparable = {key: data[key] for key in ("name", "rpo_minutes", "rto_minutes", "backup_summary", "backup_checksum_masked", "reason")}
                if existing.environment_id != environment.id or any(getattr(existing, key) != value for key, value in comparable.items()):
                    raise StateConflict("Recovery plan idempotency key was used with different data.")
                return success_response(RecoveryPlanSerializer(existing).data)
            try:
                plan = RecoveryPlan.objects.create(tenant=request.user.tenant, environment=environment, created_by=request.user, idempotency_key_hash=digest, **data)
            except IntegrityError as exc:
                raise StateConflict("Recovery plan idempotency conflict.") from exc
        except APIException as exc:
            audit_plan_creation_failure(
                actor=request.user,
                object_type="recovery_plan",
                permission_code=self.write_permission_code,
                payload=request.data,
                idempotency_key=audit_idempotency_key,
                exc=exc,
            )
            raise
        audit_plan_creation(plan, actor=request.user, permission_code=self.write_permission_code, idempotency_key=idempotency_key)
        return success_response(RecoveryPlanSerializer(plan).data, status=201)


class RecoveryPlanDetailView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "pilot.recovery.view"

    def get(self, request, pk):
        return success_response(RecoveryPlanSerializer(get_scoped_object_or_404(_recovery_queryset(request, self.read_permission_code), pk=pk)).data)


RECOVERY_ACTION_CONTRACT = {
    "submit-review": ("pilot.recovery.plan", ApprovalSerializer),
    "approve": ("pilot.recovery.review", ApprovalSerializer),
    "reject": ("pilot.recovery.review", VersionReasonSerializer),
    "schedule": ("pilot.recovery.plan", ScheduleSerializer),
    "start": ("pilot.recovery.record", VersionReasonSerializer),
    "resume": ("pilot.recovery.record", ResumeSerializer),
    "cancel": ("pilot.recovery.plan", VersionReasonSerializer),
}


class RecoveryPlanActionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    action_name = None

    def get_permissions(self):
        self.write_permission_code = RECOVERY_ACTION_CONTRACT[self.action_name][0]
        return super().get_permissions()

    def post(self, request, pk):
        idempotency_key = require_idempotency_key(request)
        permission_code, serializer_class = RECOVERY_ACTION_CONTRACT[self.action_name]
        plan = get_scoped_object_or_404(_recovery_queryset(request, permission_code), pk=pk)
        try:
            serializer = serializer_class(data=request.data)
            serializer.is_valid(raise_exception=True)
            plan, drill, replay = transition_recovery(plan=plan, actor=request.user, action=self.action_name, payload=serializer.validated_data, idempotency_key=idempotency_key, permission_code=permission_code)
        except APIException as exc:
            audit_action_failure(
                plan,
                actor=request.user,
                action=self.action_name,
                permission_code=permission_code,
                payload=getattr(serializer, "validated_data", request.data),
                idempotency_key=idempotency_key,
                exc=exc,
            )
            raise
        data = RecoveryPlanSerializer(plan).data
        if drill:
            data["drill"] = RecoveryDrillSerializer(drill).data
        data["idempotent_replay"] = replay
        return success_response(data)


class RecoveryDrillListView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "pilot.recovery.view"

    def get(self, request):
        validate_query(request, {"page", "page_size", "environment_id", "recovery_plan_id", "status", "ordering"})
        plans = _recovery_queryset(request, self.read_permission_code)
        queryset = RecoveryDrill.objects.filter(tenant=request.user.tenant, recovery_plan__in=plans).select_related("recovery_plan__environment")
        requested_status = request.query_params.get("status", "")
        if requested_status and requested_status not in {
            RecoveryPlan.Status.RUNNING, RecoveryPlan.Status.SUCCESS, RecoveryPlan.Status.FAILED,
            RecoveryPlan.Status.MANUAL_REQUIRED, RecoveryPlan.Status.CANCELLED,
        }:
            contract_error("Unknown recovery drill status.", ErrorCode.FIELD_VALIDATION_FAILED, status.HTTP_422_UNPROCESSABLE_ENTITY)
        filters = {
            "recovery_plan__environment__code": request.query_params.get("environment_id"),
            "recovery_plan_id": request.query_params.get("recovery_plan_id"),
            "status": requested_status,
        }
        for key, value in filters.items():
            if value:
                queryset = queryset.filter(**{key: value})
        ordering = request.query_params.get("ordering", "-started_at")
        if ordering not in {"started_at", "-started_at"}:
            contract_error("Unsupported ordering.", ErrorCode.FIELD_VALIDATION_FAILED, status.HTTP_422_UNPROCESSABLE_ENTITY)
        page = positive_int(request.query_params.get("page"), default=1)
        page_size = positive_int(request.query_params.get("page_size"), default=20, maximum=100)
        return success_response(paginated_data(request, queryset.order_by(ordering, "id"), RecoveryDrillSerializer, page=page, page_size=page_size))


class RecoveryDrillResultView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    write_permission_code = "pilot.recovery.record"

    def post(self, request, pk):
        idempotency_key = require_idempotency_key(request)
        plans = _recovery_queryset(request, self.write_permission_code)
        drill = get_scoped_object_or_404(RecoveryDrill.objects.filter(tenant=request.user.tenant, recovery_plan__in=plans), pk=pk)
        plan_for_audit = drill.recovery_plan
        try:
            serializer = RecoveryResultSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            drill, plan, replay = record_recovery_result(drill=drill, actor=request.user, payload=serializer.validated_data, idempotency_key=idempotency_key, permission_code=self.write_permission_code)
        except APIException as exc:
            audit_action_failure(
                plan_for_audit,
                actor=request.user,
                action="record-result",
                permission_code=self.write_permission_code,
                payload=getattr(serializer, "validated_data", request.data),
                idempotency_key=idempotency_key,
                exc=exc,
            )
            raise
        return success_response({"drill": RecoveryDrillSerializer(drill).data, "plan": RecoveryPlanSerializer(plan).data, "idempotent_replay": replay})


class ReleasePlanCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "pilot.release.view"
    write_permission_code = "pilot.release.plan"

    def get(self, request):
        validate_query(request, {"page", "page_size", "environment_id", "release_channel", "status", "ordering"})
        queryset = _release_queryset(request, self.read_permission_code)
        requested_channel = request.query_params.get("release_channel", "")
        requested_status = request.query_params.get("status", "")
        if requested_channel and requested_channel not in {"demo", "controlled_pilot"}:
            contract_error("Unknown release channel.", ErrorCode.FIELD_VALIDATION_FAILED, status.HTTP_422_UNPROCESSABLE_ENTITY)
        if requested_status and requested_status not in ReleasePlan.Status.values:
            contract_error("Unknown release status.", ErrorCode.FIELD_VALIDATION_FAILED, status.HTTP_422_UNPROCESSABLE_ENTITY)
        for key, field in (("environment_id", "environment__code"), ("release_channel", "release_channel"), ("status", "status")):
            if request.query_params.get(key):
                queryset = queryset.filter(**{field: request.query_params[key]})
        ordering = request.query_params.get("ordering", "-created_at")
        if ordering not in {"created_at", "-created_at", "scheduled_at"}:
            contract_error("Unsupported ordering.", ErrorCode.FIELD_VALIDATION_FAILED, status.HTTP_422_UNPROCESSABLE_ENTITY)
        page = positive_int(request.query_params.get("page"), default=1)
        page_size = positive_int(request.query_params.get("page_size"), default=20, maximum=100)
        return success_response(paginated_data(request, queryset.order_by(ordering, "id"), ReleasePlanSerializer, page=page, page_size=page_size))

    def post(self, request):
        audit_idempotency_key = request.headers.get("Idempotency-Key", "").strip() or f"missing:{uuid.uuid4().hex}"
        try:
            idempotency_key = require_idempotency_key(request)
            serializer = ReleaseCreateSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            validate_release_payload(data)
            data["tag"] = data.get("tag") or ""
            environment_code = data.pop("environment_id")
            environment = _environment_for(request, self.write_permission_code, environment_code)
            if not values_allowed(request.user, self.write_permission_code, environment_ids=environment_code, release_channels=data["release_channel"]):
                from apps.common.exceptions import DataScopeDenied
                raise DataScopeDenied("Release channel is outside the authorized data scope.")
            digest = hashlib.sha256(idempotency_key.encode()).hexdigest()
            existing = ReleasePlan.objects.filter(tenant=request.user.tenant, idempotency_key_hash=digest).first()
            if existing:
                comparable = {
                    key: data[key]
                    for key in (
                        "release_channel", "commit_sha", "tag", "demo_tenant_refs", "observation_minutes",
                        "stop_conditions", "rollback_point", "database_compatibility", "reason",
                    )
                }
                if existing.environment_id != environment.id or any(getattr(existing, key) != value for key, value in comparable.items()):
                    raise StateConflict("Release plan idempotency key was used with different data.")
                return success_response(ReleasePlanSerializer(existing).data)
            try:
                plan = ReleasePlan.objects.create(tenant=request.user.tenant, environment=environment, created_by=request.user, idempotency_key_hash=digest, **data)
            except IntegrityError as exc:
                raise StateConflict("Release plan idempotency conflict.") from exc
        except APIException as exc:
            audit_plan_creation_failure(
                actor=request.user,
                object_type="release_plan",
                permission_code=self.write_permission_code,
                payload=request.data,
                idempotency_key=audit_idempotency_key,
                exc=exc,
            )
            raise
        audit_plan_creation(plan, actor=request.user, permission_code=self.write_permission_code, idempotency_key=idempotency_key)
        return success_response(ReleasePlanSerializer(plan).data, status=201)


class ReleasePlanDetailView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "pilot.release.view"

    def get(self, request, pk):
        return success_response(ReleasePlanSerializer(get_scoped_object_or_404(_release_queryset(request, self.read_permission_code), pk=pk)).data)


RELEASE_ACTION_CONTRACT = {
    "submit-review": ("pilot.release.plan", ApprovalSerializer),
    "approve": ("pilot.release.review", ApprovalSerializer),
    "reject": ("pilot.release.review", VersionReasonSerializer),
    "schedule": ("pilot.release.plan", ScheduleSerializer),
    "start": ("pilot.release.record", VersionReasonSerializer),
    "resume": ("pilot.release.record", ResumeSerializer),
    "cancel": ("pilot.release.plan", VersionReasonSerializer),
    "record-result": ("pilot.release.record", ReleaseResultSerializer),
    "approve-rollback": ("pilot.release.rollback", RollbackApprovalSerializer),
    "resume-rollback": ("pilot.release.rollback", RollbackResumeSerializer),
    "record-rollback": ("pilot.release.rollback", RollbackResultSerializer),
}


class ReleasePlanActionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    action_name = None

    def get_permissions(self):
        self.write_permission_code = RELEASE_ACTION_CONTRACT[self.action_name][0]
        return super().get_permissions()

    def post(self, request, pk):
        idempotency_key = require_idempotency_key(request)
        permission_code, serializer_class = RELEASE_ACTION_CONTRACT[self.action_name]
        plan = get_scoped_object_or_404(_release_queryset(request, permission_code), pk=pk)
        try:
            serializer = serializer_class(data=request.data)
            serializer.is_valid(raise_exception=True)
            plan, replay = transition_release(plan=plan, actor=request.user, action=self.action_name, payload=serializer.validated_data, idempotency_key=idempotency_key, permission_code=permission_code)
        except APIException as exc:
            audit_action_failure(
                plan,
                actor=request.user,
                action=self.action_name,
                permission_code=permission_code,
                payload=getattr(serializer, "validated_data", request.data),
                idempotency_key=idempotency_key,
                exc=exc,
            )
            raise
        data = ReleasePlanSerializer(plan).data
        data["idempotent_replay"] = replay
        return success_response(data)
