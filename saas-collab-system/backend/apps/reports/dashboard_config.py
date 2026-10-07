"""Validation and viewer authorization for saved composite BI dashboards."""
from datetime import date
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.permissions.ui_p6_scopes import report_type_allowed
from .datasets import DATASETS, normalize_config, selected_permission

DASHBOARD_MODULES = {"经营分析", "销售管理", "库存管理", "财务中心"}
MODULE_DATASETS = {
    "经营分析": set(DATASETS),
    "销售管理": {"sales", "sales_skus", "refunds"},
    "库存管理": {"inventory"},
    "财务中心": {"finance", "inventory_value"},
}
DASHBOARD_FILTERS = {"date_from", "date_to", "platform", "store_id", "currency", "warehouse_id", "site_code"}
WIDGET_TYPES = {"card", "table", "bar", "line", "pivot"}


def _allowed_widget_config(module, raw):
    config = normalize_config(raw)
    if config["dataset"] not in MODULE_DATASETS[module]:
        raise ValidationError({"config": "该数据集不属于看板模块。"})
    return config


def normalize_dashboard(raw):
    if not isinstance(raw, dict) or set(raw) != {"kind", "version", "module", "filters", "widgets"}:
        raise ValidationError("看板配置格式不正确。")
    if raw["kind"] != "dashboard" or type(raw["version"]) is not int or raw["version"] != 1 or not isinstance(raw["module"], str) or raw["module"] not in DASHBOARD_MODULES:
        raise ValidationError("看板类型、版本或模块不正确。")
    filters, widgets = raw["filters"], raw["widgets"]
    if not isinstance(filters, dict) or set(filters) - DASHBOARD_FILTERS:
        raise ValidationError({"filters": "存在不支持的看板筛选条件。"})
    if any(not isinstance(value, (str, int, bool)) or len(str(value)) > 300 or "\x00" in str(value) for value in filters.values()):
        raise ValidationError({"filters": "看板筛选值格式不正确。"})
    for key in ("date_from", "date_to"):
        if filters.get(key):
            try:
                date.fromisoformat(str(filters[key]))
            except ValueError as exc:
                raise ValidationError({"filters": "日期格式应为 YYYY-MM-DD。"}) from exc
    if filters.get("date_from") and filters.get("date_to") and str(filters["date_from"]) > str(filters["date_to"]):
        raise ValidationError({"filters": "开始日期不能晚于结束日期。"})
    for key in ("store_id", "warehouse_id"):
        if filters.get(key) and (not str(filters[key]).isascii() or not str(filters[key]).isdigit() or not 0 < int(filters[key]) < 2**63):
            raise ValidationError({"filters": "标识应为正整数。"})
    if not isinstance(widgets, list) or not 1 <= len(widgets) <= 8:
        raise ValidationError({"widgets": "看板须包含 1 至 8 个组件。"})
    normalized = []
    ids = set()
    for widget in widgets:
        if not isinstance(widget, dict) or set(widget) != {"id", "title", "type", "width", "height", "config"}:
            raise ValidationError({"widgets": "组件格式不正确。"})
        widget_id, title = widget["id"], widget["title"]
        if not isinstance(widget_id, str) or not widget_id or len(widget_id) > 100 or widget_id in ids:
            raise ValidationError({"widgets": "组件标识必须唯一。"})
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 100:
            raise ValidationError({"widgets": "组件标题须为 1 至 100 个字符。"})
        if not isinstance(widget["type"], str) or widget["type"] not in WIDGET_TYPES or type(widget["width"]) is not int or widget["width"] not in {6, 12} or not isinstance(widget["height"], int) or isinstance(widget["height"], bool) or not 240 <= widget["height"] <= 720:
            raise ValidationError({"widgets": "组件类型或尺寸不正确。"})
        config = _allowed_widget_config(raw["module"], widget["config"])
        ids.add(widget_id)
        normalized.append({"id": widget_id, "title": title.strip(), "type": widget["type"], "width": widget["width"], "height": widget["height"], "config": config})
    return {"kind": "dashboard", "version": 1, "module": raw["module"], "filters": filters, "widgets": normalized}


def authorize_dashboard(user, dashboard, *, permission_cache=None):
    """Saved dashboards share only JSON; every current viewer is checked per widget."""
    permission_cache = {} if permission_cache is None else permission_cache
    for widget in dashboard["widgets"]:
        dataset = DATASETS[widget["config"]["dataset"]]
        selected_permission(user, dataset, permission_cache=permission_cache)
        if not report_type_allowed(user, "reports.view", dataset["report_type"], cache=permission_cache):
            raise PermissionDenied("此报表类型不在授权范围内。")

