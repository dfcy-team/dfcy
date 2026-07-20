import uuid

from django.utils import timezone
from rest_framework import status
from rest_framework.fields import DateTimeField
from rest_framework.views import APIView

from apps.common.error_codes import ErrorCode
from apps.common.exceptions import ContractViolation, DataScopeDenied, get_scoped_object_or_404
from apps.common.responses import paginated_data, success_response
from apps.permissions.api_permissions import DeclaredApplicationPermission
from apps.permissions.services import check_user_permission
from apps.permissions.ui_p8_scopes import authorize_action, authorize_create, filter_resource_queryset

from .models import EntryDecision, PerformanceRun, PilotEnvironment, SecurityReview, VerificationRun
from .ui_p8_serializers import (
    CancelSerializer,
    EntryDecisionSerializer,
    EntryDecisionSummarySerializer,
    EntryDraftSerializer,
    EntryPatchSerializer,
    PerformanceDraftSerializer,
    PerformancePatchSerializer,
    PerformanceResultSerializer,
    PerformanceRunSerializer,
    PerformanceRunSummarySerializer,
    ReviewSerializer,
    SecurityDraftSerializer,
    SecurityPatchSerializer,
    SecurityReviewSerializer,
    SecurityReviewSummarySerializer,
    VerificationDraftSerializer,
    VerificationPatchSerializer,
    VerificationResultSerializer,
    VerificationRunSerializer,
    VerificationRunSummarySerializer,
    VersionReasonSerializer,
)
from .ui_p8_services import (
    control_room_payload,
    audit_failure,
    create_resource,
    expire_if_needed,
    expire_queryset,
    patch_resource,
    transition_resource,
)


def fail(message, code=ErrorCode.REQUEST_INVALID, http_status=status.HTTP_400_BAD_REQUEST):
    raise ContractViolation(message, error_code=code, status_code=http_status)


def positive_int(value, default, maximum=None):
    if value in (None, ""):
        return default
    try:
        value = int(value)
    except (TypeError, ValueError):
        fail("Pagination values must be integers.")
    if value < 1 or (maximum and value > maximum):
        fail("Pagination values are outside the contract range.")
    return value


def idempotency_key(request):
    value = request.headers.get("Idempotency-Key", "")
    if not 1 <= len(value) <= 160 or not value.isascii() or not value.isprintable():
        fail("Idempotency-Key must contain 1-160 printable ASCII characters.", ErrorCode.VALIDATION_ERROR, status.HTTP_422_UNPROCESSABLE_ENTITY)
    return value


def environment_for(user, permission, code, *, creation=False):
    environment = get_scoped_object_or_404(PilotEnvironment.objects.filter(status="controlled"), code=code)
    if creation:
        authorize_create(user, permission, code)
    return environment


RESOURCE = {
    "security": {
        "model": SecurityReview,
        "scope": "security_review_ids",
        "prefix": "pilot.security_review",
        "serializer": SecurityReviewSerializer,
        "summary": SecurityReviewSummarySerializer,
        "draft": SecurityDraftSerializer,
        "patch": SecurityPatchSerializer,
        "filters": {"review_type", "risk_level"},
        "choices": {"status": set(SecurityReview.Status.values), "review_type": set(SecurityReview.ReviewType.values), "risk_level": {"low", "medium", "high", "critical"}},
    },
    "verification": {
        "model": VerificationRun,
        "scope": "verification_run_ids",
        "prefix": "pilot.verification",
        "serializer": VerificationRunSerializer,
        "summary": VerificationRunSummarySerializer,
        "draft": VerificationDraftSerializer,
        "patch": VerificationPatchSerializer,
        "filters": {"category", "data_class"},
        "choices": {"status": set(VerificationRun.Status.values), "category": {"authentication", "authorization", "browser_e2e", "backup_restore", "failover", "network_isolation", "security_scan"}, "data_class": {"demo", "synthetic", "masked"}},
    },
    "performance": {
        "model": PerformanceRun,
        "scope": "performance_run_ids",
        "prefix": "pilot.performance",
        "serializer": PerformanceRunSerializer,
        "summary": PerformanceRunSummarySerializer,
        "draft": PerformanceDraftSerializer,
        "patch": PerformancePatchSerializer,
        "filters": {"workload_profile"},
        "choices": {"status": set(PerformanceRun.Status.values), "workload_profile": {"demo", "synthetic"}},
    },
    "entry": {
        "model": EntryDecision,
        "scope": "entry_decision_ids",
        "prefix": "pilot.entry",
        "serializer": EntryDecisionSerializer,
        "summary": EntryDecisionSummarySerializer,
        "draft": EntryDraftSerializer,
        "patch": EntryPatchSerializer,
        "filters": {"decision"},
        "choices": {"status": set(EntryDecision.Status.values), "decision": {"go", "no_go"}},
    },
}


def scoped_queryset(request, config, permission):
    queryset = config["model"].objects.select_related("environment", "creator", "owner", "reviewer")
    queryset = filter_resource_queryset(request.user, queryset, permission, config["scope"])
    return expire_queryset(queryset)


def validate_list_query(request, config):
    common = {"page", "page_size", "status", "environment", "created_from", "created_to", "ordering"}
    unknown = set(request.query_params) - common - config["filters"]
    if unknown:
        fail(f"Unknown query parameters: {', '.join(sorted(unknown))}.")
    created_from = request.query_params.get("created_from")
    created_to = request.query_params.get("created_to")
    field = DateTimeField()
    try:
        start = field.to_internal_value(created_from) if created_from else None
        end = field.to_internal_value(created_to) if created_to else None
    except Exception:
        fail("List date filters must be ISO 8601 datetimes.")
    if start and end and start > end:
        fail("created_from cannot be later than created_to.")
    ordering = request.query_params.get("ordering", "-created_at")
    if ordering not in {"created_at", "-created_at", "updated_at", "-updated_at", "code", "-code", "status", "-status"}:
        fail("Unsupported ordering.")
    for key, choices in config["choices"].items():
        value = request.query_params.get(key)
        if value and value not in choices:
            fail(f"Invalid {key} filter value.")
    return start, end, ordering


class UIP8FailureAuditMixin:
    def handle_exception(self, exc):
        if getattr(exc, "status_code", None) in {403, 409, 422}:
            request = self.request
            config = RESOURCE.get(getattr(self, "resource", None))
            pk = self.kwargs.get("pk")
            instance = None
            if config and pk and getattr(request.user, "tenant_id", None):
                instance = config["model"].objects.filter(tenant=request.user.tenant, pk=pk).only("status").first()
            action = getattr(self, "action_name", None) or (
                "create" if request.method == "POST" else "patch" if request.method == "PATCH" else "read"
            )
            permission = getattr(self, "write_permission_code", None) or getattr(self, "read_permission_code", None)
            raw_version = request.data.get("version", 0) if isinstance(request.data, dict) else 0
            try:
                version = int(raw_version)
            except (TypeError, ValueError):
                version = 0
            try:
                audit_failure(
                    user=request.user,
                    object_type=config["prefix"].removeprefix("pilot.") if config else "control_room",
                    object_id=pk or "collection",
                    action=action,
                    permission=permission,
                    exc=exc,
                    request_id=request.headers.get("X-Request-ID") or str(uuid.uuid4()),
                    idempotency_key=request.headers.get("Idempotency-Key", ""),
                    version=version,
                    from_status=instance.status if instance else "",
                )
            except Exception:
                # Audit persistence must never replace the original authorization or contract error.
                pass
        return super().handle_exception(exc)


class ControlRoomView(UIP8FailureAuditMixin, APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "pilot.control.view"

    def get(self, request):
        unknown = set(request.query_params) - {"environment", "as_of"}
        if unknown or not request.query_params.get("environment"):
            fail("environment is required and no unknown query parameters are accepted.")
        environment = environment_for(request.user, self.read_permission_code, request.query_params["environment"], creation=True)
        try:
            as_of = DateTimeField().to_internal_value(request.query_params["as_of"]) if request.query_params.get("as_of") else timezone.now()
        except Exception:
            fail("as_of must be an ISO 8601 datetime.")
        data = control_room_payload(user=request.user, environment=environment, as_of=as_of)
        if not check_user_permission(request.user, "finance.view"):
            data["gate_summary"].append({
                "code": "finance", "name": "Finance boundary", "status": "restricted", "source_type": "permission",
                "source_id": None, "refreshed_at": as_of, "expires_at": None,
            })
            data["readiness_status"] = "blocked"
        return success_response(data)


class ResourceCollectionView(UIP8FailureAuditMixin, APIView):
    permission_classes = [DeclaredApplicationPermission]
    resource = None

    def get_permissions(self):
        prefix = RESOURCE[self.resource]["prefix"]
        self.read_permission_code = f"{prefix}.view"
        self.write_permission_code = f"{prefix}.plan"
        return super().get_permissions()

    def get(self, request):
        config = RESOURCE[self.resource]
        start, end, ordering = validate_list_query(request, config)
        queryset = scoped_queryset(request, config, self.read_permission_code)
        for key in {"status", "environment", *config["filters"]}:
            value = request.query_params.get(key)
            if value:
                queryset = queryset.filter(**{"environment__code" if key == "environment" else key: value})
        if start:
            queryset = queryset.filter(created_at__gte=start)
        if end:
            queryset = queryset.filter(created_at__lte=end)
        page = positive_int(request.query_params.get("page"), 1)
        page_size = positive_int(request.query_params.get("page_size"), 20, 100)
        data = paginated_data(request, queryset.order_by(ordering, "id"), config["summary"], page=page, page_size=page_size)
        return success_response(data)

    def post(self, request):
        config = RESOURCE[self.resource]
        serializer = config["draft"](data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        environment = environment_for(request.user, self.write_permission_code, data.pop("environment"), creation=True)
        instance, replay = create_resource(
            config["model"], actor=request.user, environment=environment, data=data,
            idempotency_key=idempotency_key(request), permission=self.write_permission_code,
        )
        payload = config["serializer"](instance).data
        payload["idempotent_replay"] = replay
        return success_response(payload, status=200 if replay else 201)


class ResourceDetailView(UIP8FailureAuditMixin, APIView):
    permission_classes = [DeclaredApplicationPermission]
    resource = None

    def get_permissions(self):
        prefix = RESOURCE[self.resource]["prefix"]
        self.read_permission_code = f"{prefix}.view"
        self.write_permission_code = f"{prefix}.plan"
        return super().get_permissions()

    def get(self, request, pk):
        config = RESOURCE[self.resource]
        instance = get_scoped_object_or_404(scoped_queryset(request, config, self.read_permission_code), pk=pk)
        instance, _ = expire_if_needed(instance)
        return success_response(config["serializer"](instance).data)

    def patch(self, request, pk):
        config = RESOURCE[self.resource]
        instance = get_scoped_object_or_404(scoped_queryset(request, config, self.write_permission_code), pk=pk)
        serializer = config["patch"](data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        target_environment = data.get("environment")
        authorize_action(
            request.user, instance, self.write_permission_code, config["scope"],
            source_environment=instance.environment.code if target_environment else None,
            target_environment=target_environment,
        )
        if target_environment:
            data["environment"] = environment_for(request.user, self.write_permission_code, target_environment)
        instance = patch_resource(instance, actor=request.user, data=data, permission=self.write_permission_code)
        return success_response(config["serializer"](instance).data)


ACTION_PERMISSIONS = {
    "submit": "plan",
    "approve": "review",
    "reject": "review",
    "record-result": "record",
    "cancel": "cancel",
}


class ResourceActionView(UIP8FailureAuditMixin, APIView):
    permission_classes = [DeclaredApplicationPermission]
    resource = None
    action_name = None

    def get_permissions(self):
        config = RESOURCE[self.resource]
        suffix = ACTION_PERMISSIONS[self.action_name]
        self.write_permission_code = f"{config['prefix']}.{suffix}"
        return super().get_permissions()

    def post(self, request, pk):
        config = RESOURCE[self.resource]
        instance = get_scoped_object_or_404(scoped_queryset(request, config, self.write_permission_code), pk=pk)
        authorize_action(request.user, instance, self.write_permission_code, config["scope"])
        serializer_class = {
            "submit": VersionReasonSerializer,
            "approve": ReviewSerializer,
            "reject": ReviewSerializer,
            "cancel": CancelSerializer,
            "record-result": VerificationResultSerializer if self.resource == "verification" else PerformanceResultSerializer,
        }[self.action_name]
        serializer = serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance, replay = transition_resource(
            instance, actor=request.user, action=self.action_name, data=serializer.validated_data,
            permission=self.write_permission_code, idempotency_key=idempotency_key(request),
        )
        payload = config["serializer"](instance).data
        payload["idempotent_replay"] = replay
        return success_response(payload)
