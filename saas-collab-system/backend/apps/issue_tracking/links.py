"""Business links reuse each domain's existing read scope; no business mutations."""
import re
from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from apps.permissions.menu_registry import load_menu_registry
from apps.permissions.services import check_user_permission


def _matches(path, pattern, exact=False):
    expression = re.sub(r':[A-Za-z_][A-Za-z0-9_]*', r'[^/]+', pattern.rstrip('/'))
    return bool(re.fullmatch(expression if exact else expression + r'(?:/.*)?', path.rstrip('/')))


def can_access_page(user, path):
    if not path:
        return True
    if not user.is_active or user.user_type != 'internal':
        return False
    if not path.startswith('/') or path.startswith('//') or any(c in path for c in ('?', '#', '\\', '%')):
        return False
    registry = load_menu_registry()
    routes = sorted(registry.get('routes', []), key=lambda row: len(row.get('path', '')), reverse=True)
    route = next((row for row in routes if _matches(path, row['path'], row.get('exact', False))), None)
    if not route or route.get('superuserOnly') and not user.is_superuser:
        return False
    if route.get('userTypes') and user.user_type not in route['userTypes']:
        return False
    for key in ('allPermissions',):
        if any(not check_user_permission(user, code) for code in route.get(key, [])):
            return False
    codes = route.get('permissions', [])
    if codes and not any(check_user_permission(user, code) for code in codes):
        return False
    return True


RECORD_PAGES = {
    'approval': '/workflow/approvals', 'exception': '/workflow/exceptions',
    'purchase_order': '/supply-chain/purchase-orders',
    'supplier_shipment': '/supply-chain/supplier-shipments',
    'dispatch_batch': '/supply-chain/logistics', 'inbound_order': '/supply-chain/logistics',
}


def can_access_record(user, record_type, record_id):
    if record_type not in RECORD_PAGES or not str(record_id).isdigit():
        return False
    try:
        if record_type in ('approval', 'exception'):
            code = 'workflow.approvals.view' if record_type == 'approval' else 'workflow.exceptions.view'
            if not check_user_permission(user, code):
                return False
            from apps.workflows.views import visible_approvals, visible_exceptions
            queryset = visible_approvals(user) if record_type == 'approval' else visible_exceptions(user)
            return queryset.filter(pk=record_id).exists()
        from apps.supply_chain.permissions import VIEW
        if record_type == 'purchase_order':
            from apps.supply_chain.services import _order
            _order(user, record_id, VIEW)
        elif record_type == 'supplier_shipment':
            from apps.supply_chain.shipments import shipment_for
            shipment_for(user, record_id, VIEW)
        else:
            from apps.supply_chain.logistics import batch_for, inbound_for
            (batch_for if record_type == 'dispatch_batch' else inbound_for)(user, record_id, VIEW)
        return True
    except (APIException, ObjectDoesNotExist, Http404, ValueError, TypeError):
        return False


def validate_context(user, data, *, assignee=None):
    menu = data.get('menu_key', '')
    path = data.get('page_path', '')
    kind, identity = data.get('record_type', ''), data.get('record_id', '')
    if bool(kind) != bool(identity):
        raise ValidationError('关联业务类型和记录ID必须同时填写')
    if path and not menu:
        raise ValidationError('关联页面必须指定菜单')
    if menu and not path:
        raise ValidationError('关联菜单必须指定页面')
    if menu:
        paths = {row.get('metadata', {}).get('path') for row in load_menu_registry().get('menus', [])}
        if menu not in paths:
            raise ValidationError('必须选择已注册的业务菜单')
    if menu and not can_access_page(user, menu):
        raise PermissionDenied('无此菜单的访问权限')
    if path and not can_access_page(user, path):
        raise PermissionDenied('无关联页面的访问权限')
    if menu and path and not _matches(path, menu):
        raise ValidationError('关联页面不属于指定菜单')
    if assignee and menu and not can_access_page(assignee, menu):
        raise ValidationError('处理人无此菜单的访问权限')
    if kind:
        expected = RECORD_PAGES.get(kind)
        if not expected or menu != expected or not _matches(path, expected):
            raise ValidationError('此业务关联尚未配置或与菜单不匹配')
        if kind in ('approval', 'exception') and path != expected:
            suffix = path[len(expected):].strip('/')
            if suffix != str(identity):
                raise ValidationError('详情页面与关联记录ID不一致')
        if not can_access_record(user, kind, identity):
            raise PermissionDenied('无关联业务记录的访问权限')
        if assignee and not can_access_record(assignee, kind, identity):
            raise ValidationError('处理人无关联业务记录的访问权限')
