from django.db.models import Q
from rest_framework.exceptions import PermissionDenied

from .models import DataScope
from .services import get_permission_data_scopes


MASTER_DATA_SCOPE_KEYS = {
    "platforms": "platform_ids",
    "stores": "store_ids",
    "warehouses": "warehouse_ids",
    "suppliers": "supplier_ids",
}


def _permission_scopes(user, permission_code):
    return get_permission_data_scopes(user, permission_code)


def _has_all_scope(scopes):
    return any(scope["scope_type"] == DataScope.ScopeType.ALL for scope in scopes)


def _configured_ids(scope, key):
    values = (scope.get("config") or {}).get(key, [])
    if not isinstance(values, list):
        return set()
    return {int(value) for value in values if str(value).isdigit()}


def _current_department_id(user):
    profile = getattr(user, "internal_profile", None)
    return getattr(profile, "department_id", None)


def require_all_scope(user, permission_code):
    scopes = _permission_scopes(user, permission_code)
    if not _has_all_scope(scopes):
        raise PermissionDenied("This operation requires all-tenant data scope for the declared permission.")


def filter_system_users(user, queryset, permission_code):
    scopes = _permission_scopes(user, permission_code)
    if _has_all_scope(scopes):
        return queryset

    allowed = Q(pk__in=[])
    department_id = _current_department_id(user)
    for scope in scopes:
        scope_type = scope["scope_type"]
        if scope_type == DataScope.ScopeType.OWN:
            allowed |= Q(pk=user.pk)
        elif scope_type == DataScope.ScopeType.DEPARTMENT and department_id:
            allowed |= Q(internal_profile__department_id=department_id)
        elif scope_type == DataScope.ScopeType.CUSTOM:
            user_ids = _configured_ids(scope, "user_ids")
            department_ids = _configured_ids(scope, "department_ids")
            if user_ids:
                allowed |= Q(pk__in=user_ids)
            if department_ids:
                allowed |= Q(internal_profile__department_id__in=department_ids)
    return queryset.filter(allowed).distinct()


def filter_departments(user, queryset, permission_code):
    scopes = _permission_scopes(user, permission_code)
    if _has_all_scope(scopes):
        return queryset

    allowed_ids = set()
    department_id = _current_department_id(user)
    for scope in scopes:
        if scope["scope_type"] in {DataScope.ScopeType.OWN, DataScope.ScopeType.DEPARTMENT}:
            if department_id:
                allowed_ids.add(department_id)
        elif scope["scope_type"] == DataScope.ScopeType.CUSTOM:
            allowed_ids.update(_configured_ids(scope, "department_ids"))
    return queryset.filter(pk__in=allowed_ids)


def filter_roles(user, queryset, permission_code):
    scopes = _permission_scopes(user, permission_code)
    if _has_all_scope(scopes):
        return queryset

    allowed = Q(pk__in=[])
    department_id = _current_department_id(user)
    for scope in scopes:
        scope_type = scope["scope_type"]
        if scope_type == DataScope.ScopeType.OWN:
            allowed |= Q(user_roles__tenant=user.tenant, user_roles__user=user)
        elif scope_type == DataScope.ScopeType.DEPARTMENT and department_id:
            allowed |= Q(
                user_roles__tenant=user.tenant,
                user_roles__user__internal_profile__department_id=department_id,
            )
        elif scope_type == DataScope.ScopeType.CUSTOM:
            role_ids = _configured_ids(scope, "role_ids")
            if role_ids:
                allowed |= Q(pk__in=role_ids)
    return queryset.filter(allowed).distinct()


def filter_assignable_roles(user, queryset, permission_code):
    """Limit role binding to explicitly authorized tenant roles.

    An all scope may assign any tenant role. A custom scope must declare
    role_ids. Own and department scopes control target users, but do not by
    themselves grant privilege-escalating role assignment rights.
    """
    scopes = _permission_scopes(user, permission_code)
    if _has_all_scope(scopes):
        return queryset

    role_ids = set()
    for scope in scopes:
        if scope["scope_type"] == DataScope.ScopeType.CUSTOM:
            role_ids.update(_configured_ids(scope, "role_ids"))
    return queryset.filter(pk__in=role_ids)


def filter_master_data(user, queryset, permission_code, resource):
    scopes = _permission_scopes(user, permission_code)
    if _has_all_scope(scopes):
        return queryset

    key = MASTER_DATA_SCOPE_KEYS[resource]
    allowed_ids = set()
    for scope in scopes:
        if scope["scope_type"] == DataScope.ScopeType.CUSTOM:
            allowed_ids.update(_configured_ids(scope, key))
    return queryset.filter(pk__in=allowed_ids)


def require_department_create_scope(user, permission_code, parent_id):
    scopes = _permission_scopes(user, permission_code)
    if _has_all_scope(scopes):
        return
    if not parent_id:
        raise PermissionDenied("Creating a root department requires all-tenant data scope.")

    from apps.tenants.models import Department

    queryset = Department.objects.filter(tenant=user.tenant, pk=parent_id)
    if not filter_departments(user, queryset, permission_code).exists():
        raise PermissionDenied("The parent department is outside the permitted data scope.")


def require_user_create_scope(user, permission_code, department_id):
    scopes = _permission_scopes(user, permission_code)
    if _has_all_scope(scopes):
        return
    if not department_id:
        raise PermissionDenied("Creating a user without a department requires all-tenant data scope.")

    from apps.tenants.models import Department

    queryset = Department.objects.filter(tenant=user.tenant, pk=department_id)
    if not filter_departments(user, queryset, permission_code).exists():
        raise PermissionDenied("The target department is outside the permitted data scope.")
