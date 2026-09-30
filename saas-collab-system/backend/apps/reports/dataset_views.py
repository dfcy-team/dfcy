from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.common.responses import success_response
from apps.permissions.api_permissions import IsInternalUser
from apps.permissions.ui_p6_scopes import report_type_allowed
from .datasets import DATASETS, dataset_catalog, normalize_config, query_dataset, selected_permission
from .models import SavedReportView
from .permissions import IsReportViewer


@api_view(["GET"])
@permission_classes([IsInternalUser])
def report_datasets(request):
    return success_response({"datasets": dataset_catalog(request.user), "pending": [
        {"name": "广告分析与广告对账", "module": "经营分析 / 财务中心", "reason": "尚未接入广告数据"},
        {"name": "订单利润、结算利润与回款", "module": "财务中心", "reason": "需要完整历史成本、退款、结算费用、汇率和回款链路"},
        {"name": "周转、ABC 与补货预测", "module": "库存管理 / 经营分析", "reason": "需要销售 SKU 关联和完整销量窗口、采购提前期及可靠在途"},
        {"name": "批次库龄与收发存", "module": "库存管理 / 供应链协同", "reason": "需要完整出入库、批次和盘点记录"},
    ]})


@api_view(["POST"])
@permission_classes([IsInternalUser])
def report_query(request):
    return success_response(query_dataset(request, request.data))


def visible_views(user):
    return SavedReportView.objects.filter(tenant=user.tenant).filter(Q(owner=user) | Q(is_shared=True))


def view_data(view, user):
    return {"id": view.pk, "name": view.name, "config": view.config, "is_shared": view.is_shared, "is_owner": view.owner_id == user.pk, "updated_at": view.updated_at}


def validate_view(request):
    data = request.data
    if not isinstance(data, dict) or set(data) - {"name", "config", "is_shared"}:
        raise ValidationError("视图配置格式不正确。")
    name = str(data.get("name") or "").strip()
    if not name or len(name) > 100:
        raise ValidationError({"name": "请输入 1 至 100 个字符的名称。"})
    config = normalize_config(data.get("config"))
    selected_permission(request.user, DATASETS[config["dataset"]])
    shared = data.get("is_shared", False)
    if not isinstance(shared, bool):
        raise ValidationError({"is_shared": "请选择是否共享。"})
    return {"name": name, "config": config, "is_shared": shared}


@api_view(["GET", "POST"])
@permission_classes([IsReportViewer])
def report_view_collection(request):
    if request.method == "POST":
        values = validate_view(request)
        if not report_type_allowed(request.user, "reports.view", DATASETS[values["config"]["dataset"]]["report_type"]):
            raise PermissionDenied("此报表类型不在授权范围内。")
        view = SavedReportView.objects.create(tenant=request.user.tenant, owner=request.user, **values)
        return success_response(view_data(view, request.user), status=201)
    allowed = []
    for view in visible_views(request.user)[:100]:
        try:
            dataset = DATASETS[view.config["dataset"]]
            selected_permission(request.user, dataset)
            if report_type_allowed(request.user, "reports.view", dataset["report_type"]):
                allowed.append(view_data(view, request.user))
        except (PermissionDenied, KeyError):
            continue
    return success_response(allowed)


@api_view(["PUT", "DELETE"])
@permission_classes([IsReportViewer])
def report_view_detail(request, pk):
    view = get_object_or_404(SavedReportView, tenant=request.user.tenant, owner=request.user, pk=pk)
    if request.method == "DELETE":
        view.delete()
        return success_response({"deleted": True})
    values = validate_view(request)
    if not report_type_allowed(request.user, "reports.view", DATASETS[values["config"]["dataset"]]["report_type"]):
        raise PermissionDenied("此报表类型不在授权范围内。")
    for key, value in values.items():
        setattr(view, key, value)
    view.save()
    return success_response(view_data(view, request.user))
