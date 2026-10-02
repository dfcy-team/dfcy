from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import BasePermission
from rest_framework.exceptions import PermissionDenied, ValidationError
from apps.common.responses import success_response
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from .history_sync import batch_action, batch_data, create_history_batch, scoped_jobs, shop_name
from .models import HistorySyncBatch


class HistoryBatchPermission(BasePermission):
    read_permission_code = "integrations.history.view"
    write_permission_code = "integrations.history.manage"
    permission_codes = ("integrations.run_live_readonly",)
    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated and user.is_active and user.user_type == "internal"):
            return False
        codes = ["integrations.history.view"] if request.method == "GET" else [
            "integrations.history.manage", "integrations.run_live_readonly",
        ]
        return all(check_user_permission(user, code) and get_permission_data_scopes(user, code) for code in codes)


def manageable_ids(user):
    codes = ["integrations.history.manage", "integrations.run_live_readonly"]
    if not all(check_user_permission(user, code) and get_permission_data_scopes(user, code) for code in codes):
        return []
    return list(scoped_jobs(user, codes).values_list("pk", flat=True))


@api_view(["GET", "POST"])
@permission_classes([HistoryBatchPermission])
def collection(request):
    code = "integrations.history.view" if request.method == "GET" else "integrations.history.manage"
    jobs = scoped_jobs(request.user, [code])
    ids = list(jobs.values_list("pk", flat=True))
    editable_ids = manageable_ids(request.user)
    if request.method == "POST":
        batch = create_history_batch(request.user, request.data)
        return success_response(batch_data(batch, ids, editable_ids))
    batches = HistorySyncBatch.objects.filter(tenant_id=request.user.tenant_id,
        segments__sync_job_id__in=ids).distinct().order_by("-id")[:50]
    eligible = jobs.filter(integration_config__platform="shopee",
        resource_type__in=["sales_order", "refund_return", "settlement_bill"], store_authorization__isnull=False)
    options = []
    for job in eligible[:300]:
        reason = ""
        if not job.is_enabled or job.status == "disabled":
            reason = "请先启用同步任务"
        # Preflight only reads configuration; never requests provider data/token.
        elif job.integration_config.environment not in {"pilot", "production"}:
            reason = "仅支持试运行或生产配置"
        options.append({"id": job.pk, "shop_name": shop_name(job), "resource_type": job.resource_type,
            "is_enabled": job.is_enabled, "blocked_reason": reason})
    return success_response({"batches": [batch_data(batch, ids, editable_ids) for batch in batches], "jobs": options})


@api_view(["POST"])
@permission_classes([HistoryBatchPermission])
def action(request, pk):
    if not isinstance(request.data, dict):
        raise ValidationError("历史补采操作参数无效。")
    fields = {"action", "start_date", "end_date", "expected_revision"} if request.data.get("action") == "adjust_range" else {"action"}
    if set(request.data) != fields:
        raise ValidationError("历史补采操作参数无效。")
    batch = HistorySyncBatch.objects.filter(pk=pk, tenant_id=request.user.tenant_id).first()
    if not batch:
        raise PermissionDenied("批次不存在或超出当前租户。")
    payload = {key: value for key, value in request.data.items() if key != "action"}
    batch = batch_action(batch, request.user, request.data["action"], payload)
    ids = list(scoped_jobs(request.user, ["integrations.history.manage"]).values_list("pk", flat=True))
    return success_response(batch_data(batch, ids, manageable_ids(request.user)))
