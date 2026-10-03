"""Real report exceptions: server-authorized aggregate lineage, never mock facts."""
import hashlib
import json
from uuid import UUID

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.common.responses import success_response
from apps.workflows.models import BusinessException
from apps.workflows.permissions import IsExceptionManager, IsExceptionViewer, scope_allows_value
from apps.workflows.services import write_workflow_audit
from .datasets import normalize_config, query_dataset
from .permissions import IsReportViewer

MODULES = {"sales": "sales", "sales_skus": "sales", "refunds": "sales", "inventory": "inventory", "inventory_value": "finance", "finance": "finance"}


def _lineage(request, raw_config, group):
    config = normalize_config(raw_config)
    if not isinstance(group, dict) or set(group) != set(config["dimensions"]):
        raise ValidationError("请选择一个完整的已查询分组。")
    # Query rechecks current tenant, dataset permission and source scopes before any cache access.
    result = query_dataset(request, config)
    if not any(all(row.get(key) == value for key, value in group.items()) for row in result["rows"]):
        raise PermissionDenied("来源分组当前不可读取，请重新查询后核查。")
    return result


@api_view(["POST"])
@permission_classes([IsReportViewer, IsExceptionManager])
@transaction.atomic
def report_exception_create(request):
    payload = request.data
    if not isinstance(payload, dict) or set(payload) - {"config", "group", "title", "request_key"}:
        raise ValidationError("核查请求格式不正确。")
    title = payload.get("title", "")
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        raise ValidationError("请输入1至200个字符的核查事项。")
    try:
        request_key = str(UUID(str(payload.get("request_key", ""))))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("核查请求编号无效。")
    result = _lineage(request, payload.get("config"), payload.get("group"))
    config = result["config"]
    module = MODULES[config["dataset"]]
    if not scope_allows_value(request.user, "workflow.exceptions.manage", "exception_modules", module):
        raise PermissionDenied("当前账号无权管理该业务模块的异常。")
    group = payload["group"]
    request_hash = hashlib.sha256(json.dumps([config, group, title.strip()], sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    context = {"config": config, "group": group, "request_hash": request_hash,
        "metric_version": result["metric_version"], "mapping_version": result.get("mapping_version"),
        "refreshed_at": str(result.get("refreshed_at") or ""), "computed_at": str(result["computed_at"])}
    exception, created = BusinessException.objects.get_or_create(
        tenant=request.user.tenant, created_by=request.user, report_request_key=request_key,
        defaults={"module": module, "title": title.strip(), "business_type": "report_group", "business_id": request_hash,
            "report_context": context, "description": "来自真实报表分组的人工核查；来源范围和口径已保存，业务事实未改写。"})
    if not created and exception.report_context.get("request_hash") != request_hash:
        raise ValidationError("该请求编号已用于其他核查事项。")
    if created:
        write_workflow_audit(exception, resource_type="exception", actor=request.user, action="create", to_status=exception.status,
            detail={"source": "report_group", "dataset": config["dataset"], "metric_version": result["metric_version"], "source_hash": request_hash})
    return success_response({"id": exception.pk, "status": exception.status, "created": created}, status=201 if created else 200)


@api_view(["GET"])
@permission_classes([IsReportViewer, IsExceptionViewer])
def report_exception_source(request, pk):
    exception = get_object_or_404(BusinessException, tenant=request.user.tenant, pk=pk, business_type="report_group")
    if not scope_allows_value(request.user, "workflow.exceptions.view", "exception_modules", exception.module):
        raise PermissionDenied("当前账号无权查看该异常。")
    context = exception.report_context
    _lineage(request, context.get("config"), context.get("group"))
    return success_response({"exception_id": exception.pk, "status": exception.status, "source": context})
