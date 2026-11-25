"""Tenant-local store bounds for shared financial calculations."""
import hashlib
import json
from contextvars import ContextVar
from functools import wraps
from django.db.models import Q
from rest_framework.exceptions import PermissionDenied
from apps.masterdata.models import StoreMaster, PlatformMaster, PlatformSiteMaster
from apps.permissions.services import check_user_permission, get_permission_data_scopes


_request_access = ContextVar('finance_summary_request_access', default=None)


def request_access(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        token = _request_access.set({'user': request.user, 'permissions': {}, 'memo': {}})
        try:
            return view(request, *args, **kwargs)
        finally:
            _request_access.reset(token)
    return wrapped


def request_context(user):
    context = _request_access.get()
    if context is None or context['user'] is not user:
        return None
    flags = (user.pk, user.tenant_id, user.is_active, user.is_superuser)
    if context.get('flags') != flags:
        context['permissions'].clear()
        context['memo'].clear()
        context['flags'] = flags
    return context


def request_memo(user, key, factory):
    context = request_context(user)
    if context is None:
        return factory()
    # Mutable actor flags must not be hidden by request-local memoization.
    key = (user.pk, user.tenant_id, user.is_active, user.is_superuser, key)
    if key not in context['memo']:
        context['memo'][key] = factory()
    return context['memo'][key]


def permission_allowed(user, code):
    def resolve():
        context = request_context(user)
        return check_user_permission(user, code, cache=context['permissions'] if context else None)
    return request_memo(user, ('allowed', code), resolve)


def permission_scopes(user, code):
    def resolve():
        context = request_context(user)
        return get_permission_data_scopes(user, code, cache=context['permissions'] if context else None)
    return request_memo(user, ('scopes', code), resolve)


def store_ids(user):
    return request_memo(user, 'visible_stores', lambda: resolve_store_ids(user))


def resolve_store_ids(user):
    from .summary_service import READ_PERMISSIONS, require_access
    require_access(user)
    stores=StoreMaster.objects.filter(tenant=user.tenant)
    allowed=set(stores.values_list('pk',flat=True))
    dimensions={'store_ids':('pk',StoreMaster),'platform_ids':('platform_id',PlatformMaster),'site_ids':('platform_site_id',PlatformSiteMaster)}
    for code in READ_PERMISSIONS:
        scopes=permission_scopes(user,code)
        if user.is_superuser or any(s['scope_type']=='all' for s in scopes):
            continue
        branches=Q(pk__in=[])
        for scope in scopes:
            config=scope.get('config') or {}
            if scope['scope_type']!='custom' or not isinstance(config,dict) or not config:
                continue
            if set(config)-set(dimensions)-{'platforms','regions'}:
                continue
            branch=Q()
            for key,values in config.items():
                if not isinstance(values,list) or not values:
                    raise PermissionDenied('平台账单的数据范围配置无效。')
                if key in dimensions:
                    field,model=dimensions[key]
                    if any(type(v)is not int or v<=0 for v in values) or model.objects.filter(tenant=user.tenant,pk__in=set(values)).count()!=len(set(values)):
                        raise PermissionDenied('平台账单范围包含无效或跨租户标识。')
                    branch &= Q(**{field+'__in':values})
                else:
                    field={'platforms':'platform__platform_type','regions':'country_code'}[key]
                    if any(not isinstance(v,str) or not v for v in values):
                        raise PermissionDenied('平台账单的数据范围配置无效。')
                    branch &= Q(**{field+'__in':values})
            branches |= branch
        allowed &= set(stores.filter(branches).values_list('pk',flat=True))
    if not allowed:
        raise PermissionDenied('当前权限没有共同可查看的店铺范围，请管理员核对财务、订单和成本权限。')
    return sorted(allowed)


def full_reader(user):
    from .summary_service import READ_PERMISSIONS,has_full_scope
    return request_memo(user, 'full_reader', lambda: all(has_full_scope(user,code) for code in READ_PERMISSIONS))


def signature(user, ids):
    return hashlib.sha256(json.dumps([str(user.tenant_id),ids,full_reader(user)],separators=(',',':')).encode()).hexdigest()


def scoped_payload(user,payload):
    if full_reader(user):
        return payload
    ids=store_ids(user)
    filters=dict(payload.get('filters') or {})
    if filters.get('store') and str(filters['store']) not in {str(pk) for pk in ids}:
        raise PermissionDenied('店铺不在当前授权范围内。')
    filters['_stores']=[str(pk) for pk in ids]
    return {**payload,'filters':filters}


def check_job_scope(row,user):
    if row.kind!='query':
        if not full_reader(user):raise PermissionDenied('完整批次任务仅对具有完整查看范围的用户开放。')
        return
    requested=(row.request.get('filters') or {}).get('_stores')
    if requested is None:
        if not full_reader(user):raise PermissionDenied('该任务包含超出当前授权范围的数据，请重新查询。')
    elif not set(map(str,requested)).issubset(map(str,store_ids(user))):
        raise PermissionDenied('任务涉及的店铺已超出当前授权范围，请重新查询。')
