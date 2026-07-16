from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.views import APIView

from apps.accounts.models import CustomUser
from apps.audit.services import write_operation_log
from apps.common.exceptions import BusinessRuleViolation, StateConflict
from apps.common.responses import paginated_data, success_response
from apps.permissions.api_permissions import DeclaredApplicationPermission
from apps.rpa.internal_scope import (
    filter_rpa_devices,
    filter_rpa_locks,
    filter_rpa_runs,
    filter_rpa_signatures,
    filter_rpa_tasks,
)
from apps.rpa.internal_serializers import (
    RPAAccountLockSerializer,
    RPADeviceSerializer,
    RPAPageSignatureSerializer,
    RPARunSerializer,
    RPATaskDetailSerializer,
    RPATaskListSerializer,
)
from apps.rpa.models import RPAAccountLock, RPAAgent, RPAPageSignature, RPATask, RPATaskAttempt
from apps.rpa.stability_services import release_account_lock


def _page_params(request):
    try:
        page = max(1, int(request.query_params.get("page", 1)))
        page_size = min(100, max(1, int(request.query_params.get("page_size", 20))))
    except (TypeError, ValueError) as exc:
        raise ValidationError({"pagination": "page and page_size must be integers."}) from exc
    return page, page_size


def _audit(request, action, object_type, object_id, after_data):
    return write_operation_log(
        tenant=request.user.tenant,
        user=request.user,
        module="rpa_management",
        action=action,
        object_type=object_type,
        object_id=object_id,
        after_data=after_data,
        ip_address=request.META.get("REMOTE_ADDR"),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
    )


class TaskCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "rpa.tasks.view"

    def get(self, request):
        queryset = RPATask.objects.filter(tenant=request.user.tenant).select_related("claimed_by", "manual_assignee")
        queryset = filter_rpa_tasks(request.user, queryset, self.read_permission_code)
        if request.query_params.get("status"):
            queryset = queryset.filter(status=request.query_params["status"])
        if request.query_params.get("task_type"):
            queryset = queryset.filter(task_type=request.query_params["task_type"])
        page, page_size = _page_params(request)
        return success_response(paginated_data(request, queryset, RPATaskListSerializer, page=page, page_size=page_size))


class TaskDetailView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "rpa.tasks.view"

    def get(self, request, task_id):
        queryset = RPATask.objects.filter(tenant=request.user.tenant).select_related("claimed_by", "manual_assignee")
        queryset = filter_rpa_tasks(request.user, queryset, self.read_permission_code)
        task = get_object_or_404(queryset, pk=task_id)
        return success_response(RPATaskDetailSerializer(task).data)


class RunCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "rpa.tasks.view"

    def get(self, request):
        queryset = RPATaskAttempt.objects.filter(tenant=request.user.tenant).select_related("task", "agent")
        queryset = filter_rpa_runs(request.user, queryset, self.read_permission_code)
        if request.query_params.get("status"):
            queryset = queryset.filter(status=request.query_params["status"])
        page, page_size = _page_params(request)
        return success_response(paginated_data(request, queryset, RPARunSerializer, page=page, page_size=page_size))


class RunDetailView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "rpa.tasks.view"

    def get(self, request, run_id):
        queryset = RPATaskAttempt.objects.filter(tenant=request.user.tenant).select_related("task", "agent")
        run = get_object_or_404(filter_rpa_runs(request.user, queryset, self.read_permission_code), pk=run_id)
        return success_response(RPARunSerializer(run).data)


class DeviceCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "rpa.devices.view"

    def get(self, request):
        queryset = RPAAgent.objects.filter(tenant=request.user.tenant).select_related("user")
        queryset = filter_rpa_devices(request.user, queryset, self.read_permission_code)
        page, page_size = _page_params(request)
        return success_response(paginated_data(request, queryset, RPADeviceSerializer, page=page, page_size=page_size))


class DeviceDetailView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "rpa.devices.view"

    def get(self, request, device_id):
        queryset = RPAAgent.objects.filter(tenant=request.user.tenant).select_related("user")
        device = get_object_or_404(filter_rpa_devices(request.user, queryset, self.read_permission_code), pk=device_id)
        return success_response(RPADeviceSerializer(device).data)


class DeviceDryRunView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    write_permission_code = "rpa.devices.dry_run"

    def post(self, request, device_id):
        queryset = RPAAgent.objects.filter(tenant=request.user.tenant)
        device = get_object_or_404(filter_rpa_devices(request.user, queryset, self.write_permission_code), pk=device_id)
        if device.status != RPAAgent.Status.ACTIVE:
            raise StateConflict("Disabled devices cannot run a dry-run check.")
        if device.execution_mode not in {RPAAgent.ExecutionMode.MOCK, RPAAgent.ExecutionMode.DRY_RUN}:
            raise BusinessRuleViolation("Only mock or dry-run devices are executable in UI-P3.")
        checks = {
            "agent_binding": bool(device.user_id),
            "execution_mode": device.execution_mode,
            "platform_connection": "not_attempted",
            "browser_automation": "not_attempted",
            "result": "pass" if device.user_id else "warning",
        }
        _audit(request, "device.dry_run", "RPAAgent", device.id, checks)
        return success_response({"device_id": device.id, "status": "dry_run", "checks": checks})


class ManualQueueView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "rpa.tasks.view"

    def get(self, request):
        queryset = RPATask.objects.filter(
            tenant=request.user.tenant,
            status=RPATask.Status.MANUAL_REQUIRED,
        ).select_related("claimed_by", "manual_assignee")
        queryset = filter_rpa_tasks(request.user, queryset, self.read_permission_code)
        page, page_size = _page_params(request)
        return success_response(paginated_data(request, queryset, RPATaskListSerializer, page=page, page_size=page_size))


class AssignManualView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    write_permission_code = "rpa.tasks.manage"

    @transaction.atomic
    def post(self, request, task_id):
        queryset = RPATask.objects.select_for_update().filter(tenant=request.user.tenant)
        task = get_object_or_404(filter_rpa_tasks(request.user, queryset, self.write_permission_code), pk=task_id)
        if task.status != RPATask.Status.MANUAL_REQUIRED:
            raise StateConflict("Only manual_required tasks can be assigned to a person.")
        assignee_id = request.data.get("assignee_id") or request.user.id
        assignee = get_object_or_404(
            CustomUser.objects.filter(
                tenant=request.user.tenant,
                user_type=CustomUser.UserType.INTERNAL,
                is_active=True,
            ),
            pk=assignee_id,
        )
        task.manual_assignee = assignee
        task.manual_reason = str(request.data.get("reason") or "Manual inspection assigned.")[:1000]
        task.manual_assigned_at = timezone.now()
        task.save(update_fields=["manual_assignee", "manual_reason", "manual_assigned_at", "updated_at"])
        _audit(request, "task.assign_manual", "RPATask", task.id, {"assignee_id": assignee.id})
        return success_response(RPATaskListSerializer(task).data)


class RetryMockView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    write_permission_code = "rpa.tasks.manage"

    @transaction.atomic
    def post(self, request, task_id):
        queryset = RPATask.objects.select_for_update().filter(tenant=request.user.tenant)
        task = get_object_or_404(filter_rpa_tasks(request.user, queryset, self.write_permission_code), pk=task_id)
        if task.status not in {RPATask.Status.FAILED, RPATask.Status.MANUAL_REQUIRED}:
            raise StateConflict("Mock retry is only allowed for failed or manual_required tasks.")
        if task.retry_count >= task.max_retry_count:
            raise BusinessRuleViolation("The task has reached its maximum retry count.")
        before = task.status
        release_account_lock(task)
        task.status = RPATask.Status.RETRYING
        task.claimed_by = None
        task.claimed_at = None
        task.started_at = None
        task.finished_at = None
        task.manual_assignee = None
        task.manual_reason = ""
        task.manual_assigned_at = None
        task.save(update_fields=[
            "status", "claimed_by", "claimed_at", "started_at", "finished_at",
            "manual_assignee", "manual_reason", "manual_assigned_at", "updated_at",
        ])
        _audit(request, "task.retry_mock", "RPATask", task.id, {"from": before, "to": task.status})
        return success_response(RPATaskListSerializer(task).data)


class AccountLockCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "rpa.stability.view"

    def get(self, request):
        queryset = RPAAccountLock.objects.filter(tenant=request.user.tenant).select_related("task")
        queryset = filter_rpa_locks(request.user, queryset, self.read_permission_code)
        page, page_size = _page_params(request)
        return success_response(paginated_data(request, queryset, RPAAccountLockSerializer, page=page, page_size=page_size))


class PageSignatureCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "rpa.stability.view"

    def get(self, request):
        queryset = RPAPageSignature.objects.filter(tenant=request.user.tenant)
        queryset = filter_rpa_signatures(request.user, queryset, self.read_permission_code)
        page, page_size = _page_params(request)
        return success_response(paginated_data(request, queryset, RPAPageSignatureSerializer, page=page, page_size=page_size))


class StabilityDashboardView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "rpa.stability.view"

    def get(self, request):
        tasks = filter_rpa_tasks(
            request.user,
            RPATask.objects.filter(tenant=request.user.tenant),
            self.read_permission_code,
        )
        runs = filter_rpa_runs(
            request.user,
            RPATaskAttempt.objects.filter(tenant=request.user.tenant),
            self.read_permission_code,
        )
        return success_response({
            "task_states": list(tasks.values("status").annotate(count=Count("id")).order_by("status")),
            "run_states": list(runs.values("status").annotate(count=Count("id")).order_by("status")),
            "manual_required": tasks.filter(status=RPATask.Status.MANUAL_REQUIRED).count(),
            "boundary": "internal_read_only_no_agent_execution",
        })
