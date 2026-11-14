from rest_framework.exceptions import PermissionDenied

from apps.masterdata.models import StoreMaster
from apps.permissions.services import check_user_permission, get_permission_data_scopes


PREFIX = "marketing.flash_sales."


def visible_stores(user, action="view"):
    code = PREFIX + action
    if not (user and user.is_active and user.tenant_id and user.user_type == "internal"
            and check_user_permission(user, code)):
        raise PermissionDenied("没有此闪购操作权限。")
    queryset = StoreMaster.objects.filter(tenant_id=user.tenant_id)
    scopes = get_permission_data_scopes(user, code, resource_code="marketing.flash_sales")
    if any(scope["scope_type"] == "all" for scope in scopes):
        return queryset
    ids = set()
    for scope in scopes:
        config = scope.get("config") or {}
        if scope["scope_type"] != "custom" or set(config) - {"store_ids"}:
            continue
        values = config.get("store_ids", [])
        if isinstance(values, list):
            ids.update(value for value in values if type(value) is int and value > 0)
    return queryset.filter(pk__in=ids)


def require_stores(user, ids, action):
    if not isinstance(ids, list) or not ids or any(type(value) is not int or value < 1 for value in ids):
        raise PermissionDenied("请选择有效店铺。")
    rows = list(visible_stores(user, action).filter(pk__in=ids).select_related("platform", "operator"))
    if len(rows) != len(set(ids)):
        raise PermissionDenied("所选店铺超出当前租户或操作范围。")
    return rows


def require_global(user):
    visible_stores(user, "notifications")
    scopes = get_permission_data_scopes(user, PREFIX + "notifications", resource_code="marketing.flash_sales")
    if not any(scope["scope_type"] == "all" for scope in scopes):
        raise PermissionDenied("全局兜底设置需要全租户通知管理范围。")
