from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.common.responses import success_response
from .datasets import DATASETS, dataset_catalog, normalize_config, query_dataset, selected_permission
from .dashboard_config import authorize_dashboard, normalize_dashboard
from .models import SavedReportView, SavedReportViewRevision
from .permissions import IsReportViewer


@api_view(["GET"])
@permission_classes([IsReportViewer])
def report_datasets(request):
    return success_response({"datasets": dataset_catalog(request.user, permission_cache=request._permission_resolution_cache), "pending": [
        {"name": "广告费用对账", "module": "财务中心", "status": "pending", "reason": "广告自助分析已接入店铺日报；费用对账仍需平台扣费账单及入账关联"},
        {"name": "订单利润", "module": "财务中心", "status": "pending", "reason": "需要订单商品关联、完整历史成本、退款、费用分摊及汇率；流水净额不代替利润"},
        {"name": "结算利润与实际回款", "module": "财务中心", "status": "pending", "reason": "需要完整结算账单、提现、银行到账和对账关联"},
        {"name": "销售 ABC 与库存周转", "module": "库存管理 / 经营分析", "status": "pending", "reason": "需要可靠销售 SKU 关联、完整销量窗口及同口径平均库存"},
        {"name": "补货建议", "module": "库存管理", "status": "pending", "reason": "需要仓库需求分配、采购提前期、安全库存及可靠在途"},
        {"name": "批次库龄", "module": "库存管理", "status": "pending", "reason": "需要批次标识及真实入库日期；库存快照日期不等于入库日期"},
        {"name": "收发存", "module": "库存管理 / 供应链协同", "status": "pending", "reason": "需要完整出入库和盘点记录；快照差额不等于出入库流水"},
    ]})


@api_view(["POST"])
@permission_classes([IsReportViewer])
def report_query(request):
    return success_response(query_dataset(request, request.data))


@api_view(["POST"])
@permission_classes([IsReportViewer])
def report_filter_options(request):
    from .identity_options import store_options
    return success_response(store_options(request, request.data))


def visible_views(user):
    return SavedReportView.objects.filter(tenant=user.tenant, is_archived=False).filter(Q(owner=user) | Q(is_shared=True))


def view_data(view, user):
    return {"id": view.pk, "name": view.name, "config": view.config, "is_shared": view.is_shared, "is_owner": view.owner_id == user.pk, "owner_id": view.owner_id, "version": view.version, "updated_at": view.updated_at}


def validate_view(request):
    data = request.data
    if not isinstance(data, dict) or set(data) - {"name", "config", "is_shared", "expected_version"}:
        raise ValidationError("视图配置格式不正确。")
    name = str(data.get("name") or "").strip()
    if not name or len(name) > 100:
        raise ValidationError({"name": "请输入 1 至 100 个字符的名称。"})
    raw_config = data.get("config")
    if isinstance(raw_config, dict) and raw_config.get("kind") == "dashboard":
        config = normalize_dashboard(raw_config)
        authorize_dashboard(request.user, config, permission_cache=getattr(request, "_permission_resolution_cache", None))
    else:
        config = normalize_config(raw_config)
        selected_permission(request.user, DATASETS[config["dataset"]], permission_cache=getattr(request, "_permission_resolution_cache", None))
    shared = data.get("is_shared", False)
    if not isinstance(shared, bool):
        raise ValidationError({"is_shared": "请选择是否共享。"})
    expected = data.get("expected_version")
    if expected is not None and (type(expected) is not int or expected < 1):
        raise ValidationError({"expected_version": "版本号格式不正确。"})
    return {"name": name, "config": config, "is_shared": shared, "expected_version": expected}


@api_view(["GET", "POST"])
@permission_classes([IsReportViewer])
def report_view_collection(request):
    if request.method == "POST":
        values = validate_view(request)
        if values["config"].get("kind") == "dashboard":
            authorize_dashboard(request.user, values["config"], permission_cache=getattr(request, "_permission_resolution_cache", None))
        from .view_revision_service import create_view
        values.pop("expected_version", None)
        view = create_view(tenant=request.user.tenant, owner=request.user, actor=request.user, **values)
        return success_response(view_data(view, request.user), status=201)
    allowed = []
    permission_cache = request._permission_resolution_cache
    for view in visible_views(request.user)[:100]:
        try:
            if view.config.get("kind") == "dashboard":
                authorize_dashboard(request.user, view.config, permission_cache=permission_cache)
                allowed.append(view_data(view, request.user))
            else:
                dataset = DATASETS[view.config["dataset"]]
                selected_permission(request.user, dataset, permission_cache=permission_cache)
                allowed.append(view_data(view, request.user))
        except (PermissionDenied, ValidationError, KeyError):
            continue
    return success_response(allowed)


@api_view(["PUT", "DELETE"])
@permission_classes([IsReportViewer])
def report_view_detail(request, pk):
    view = get_object_or_404(SavedReportView, tenant=request.user.tenant, owner=request.user, pk=pk, is_archived=False)
    if request.method == "DELETE":
        from .view_revision_service import archive_view
        archive_view(view, request.user)
        return success_response({"deleted": True})
    values = validate_view(request)
    if values["config"].get("kind") == "dashboard":
        authorize_dashboard(request.user, values["config"], permission_cache=getattr(request, "_permission_resolution_cache", None))
    from .view_revision_service import update_view
    expected = values.pop("expected_version")
    try:
        view = update_view(view.pk, request.user, values, expected_version=expected)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    return success_response(view_data(view, request.user))


@api_view(["GET"])
@permission_classes([IsReportViewer])
def report_view_history(request, pk):
    view = get_object_or_404(SavedReportView, tenant=request.user.tenant, owner=request.user, pk=pk)
    revisions = list(SavedReportViewRevision.objects.filter(view=view))
    for item in revisions:
        if item.config.get("kind") == "dashboard":
            authorize_dashboard(request.user, item.config, permission_cache=getattr(request, "_permission_resolution_cache", None))
        else:
            dataset = DATASETS.get(item.config.get("dataset"))
            if dataset is None:
                raise PermissionDenied("当前无权查看此数据集。")
            selected_permission(request.user, dataset, permission_cache=getattr(request, "_permission_resolution_cache", None))
    history = [{"version": item.version, "config": item.config, "name": item.name, "is_shared": item.is_shared,
                "action": item.action, "actor_id": item.actor_id, "created_at": item.created_at}
               for item in revisions]
    return success_response(history)
