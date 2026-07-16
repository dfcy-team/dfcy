from django.db.models import Q

from apps.permissions.models import DataScope
from apps.permissions.services import get_permission_data_scopes


def _ids(scope, key):
    values = (scope.get("config") or {}).get(key, [])
    if not isinstance(values, list):
        return set()
    return {int(value) for value in values if str(value).isdigit()}


def _values(scope, key):
    values = (scope.get("config") or {}).get(key, [])
    if not isinstance(values, list):
        return set()
    return {str(value) for value in values if str(value)}


def _scopes(user, permission_code):
    return get_permission_data_scopes(user, permission_code)


def _all(scopes):
    return any(scope["scope_type"] == DataScope.ScopeType.ALL for scope in scopes)


def filter_rpa_tasks(user, queryset, permission_code):
    scopes = _scopes(user, permission_code)
    if _all(scopes):
        return queryset
    task_ids = set()
    for scope in scopes:
        if scope["scope_type"] == DataScope.ScopeType.CUSTOM:
            task_ids.update(_ids(scope, "rpa_task_ids"))
    return queryset.filter(pk__in=task_ids)


def filter_rpa_devices(user, queryset, permission_code):
    scopes = _scopes(user, permission_code)
    if _all(scopes):
        return queryset
    device_ids = set()
    for scope in scopes:
        if scope["scope_type"] == DataScope.ScopeType.CUSTOM:
            device_ids.update(_ids(scope, "rpa_device_ids"))
    return queryset.filter(pk__in=device_ids)


def filter_rpa_runs(user, queryset, permission_code):
    scopes = _scopes(user, permission_code)
    if _all(scopes):
        return queryset
    combined_filter = None
    for scope in scopes:
        if scope["scope_type"] == DataScope.ScopeType.CUSTOM:
            task_ids = _ids(scope, "rpa_task_ids")
            device_ids = _ids(scope, "rpa_device_ids")
            scope_filter = None
            if task_ids:
                scope_filter = Q(task_id__in=task_ids)
            if device_ids:
                device_filter = Q(agent_id__in=device_ids)
                scope_filter = scope_filter & device_filter if scope_filter is not None else device_filter
            if scope_filter is not None:
                combined_filter = (
                    combined_filter | scope_filter
                    if combined_filter is not None
                    else scope_filter
                )
    return queryset.filter(combined_filter).distinct() if combined_filter is not None else queryset.none()


def filter_rpa_locks(user, queryset, permission_code):
    scopes = _scopes(user, permission_code)
    if _all(scopes):
        return queryset
    task_ids = set()
    for scope in scopes:
        if scope["scope_type"] == DataScope.ScopeType.CUSTOM:
            task_ids.update(_ids(scope, "rpa_task_ids"))
    return queryset.filter(task_id__in=task_ids)


def filter_rpa_signatures(user, queryset, permission_code):
    scopes = _scopes(user, permission_code)
    if _all(scopes):
        return queryset
    platforms = set()
    for scope in scopes:
        if scope["scope_type"] == DataScope.ScopeType.CUSTOM:
            platforms.update(_values(scope, "rpa_platforms"))
    return queryset.filter(platform__in=platforms)
