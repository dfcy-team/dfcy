from django.db.models import Q
from rest_framework.exceptions import PermissionDenied

from .models import DataScope
from .services import get_permission_data_scopes


MASTER_DATA_SCOPE_KEYS = {
    "platforms": "platform_ids",
    "stores": "store_ids",
    "sites": "site_ids",
    "platform-sites": "platform_site_ids",
    "warehouses": "warehouse_ids",
    "suppliers": "supplier_ids",
}


def _permission_scopes(user, permission_code, permission_cache=None):
    return get_permission_data_scopes(user, permission_code, cache=permission_cache)


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


def department_tree_ids(queryset, root_ids):
    """Return tenant-local roots and descendants without trusting tree shape."""
    rows = list(queryset.values("id", "parent_id"))
    known_ids = {row["id"] for row in rows}
    children = {}
    for row in rows:
        parent_id = row["parent_id"]
        if parent_id in known_ids:
            children.setdefault(parent_id, set()).add(row["id"])
    result = {int(value) for value in root_ids if value in known_ids}
    pending = list(result)
    while pending:
        current = pending.pop()
        for child_id in children.get(current, ()):
            if child_id not in result:
                result.add(child_id)
                pending.append(child_id)
    return result


def require_all_scope(user, permission_code, permission_cache=None):
    scopes = _permission_scopes(user, permission_code, permission_cache)
    if not _has_all_scope(scopes):
        raise PermissionDenied("This operation requires all-tenant data scope for the declared permission.")


def filter_system_users(user, queryset, permission_code, permission_cache=None):
    scopes = _permission_scopes(user, permission_code, permission_cache)
    if _has_all_scope(scopes):
        return queryset

    allowed = Q(pk__in=[])
    department_id = _current_department_id(user)
    allowed_department_ids = set()
    for scope in scopes:
        scope_type = scope["scope_type"]
        if scope_type == DataScope.ScopeType.OWN:
            allowed |= Q(pk=user.pk)
        elif scope_type == DataScope.ScopeType.DEPARTMENT and department_id:
            allowed_department_ids.add(department_id)
        elif scope_type == DataScope.ScopeType.DEPARTMENT_TREE and department_id:
            from apps.tenants.models import Department

            allowed_department_ids.update(department_tree_ids(
                Department.objects.filter(tenant=user.tenant),
                {department_id},
            ))
        elif scope_type == DataScope.ScopeType.CUSTOM:
            user_ids = _configured_ids(scope, "user_ids")
            department_ids = _configured_ids(scope, "department_ids")
            if user_ids:
                allowed |= Q(pk__in=user_ids)
            if department_ids:
                allowed_department_ids.update(department_ids)
    if allowed_department_ids:
        allowed |= (
            Q(internal_profile__department_id__in=allowed_department_ids)
            | Q(internal_profile__departments__id__in=allowed_department_ids)
        )
    return queryset.filter(allowed).distinct()


def filter_departments(user, queryset, permission_code, permission_cache=None):
    scopes = _permission_scopes(user, permission_code, permission_cache)
    if _has_all_scope(scopes):
        return queryset

    allowed_ids = set()
    department_id = _current_department_id(user)
    for scope in scopes:
        if scope["scope_type"] in {DataScope.ScopeType.OWN, DataScope.ScopeType.DEPARTMENT}:
            if department_id:
                allowed_ids.add(department_id)
        elif scope["scope_type"] == DataScope.ScopeType.DEPARTMENT_TREE:
            if department_id:
                from apps.tenants.models import Department

                allowed_ids.update(
                    department_tree_ids(
                        Department.objects.filter(tenant=user.tenant),
                        {department_id},
                    )
                )
        elif scope["scope_type"] == DataScope.ScopeType.CUSTOM:
            allowed_ids.update(_configured_ids(scope, "department_ids"))
    return queryset.filter(pk__in=allowed_ids)


def filter_roles(user, queryset, permission_code, permission_cache=None):
    scopes = _permission_scopes(user, permission_code, permission_cache)
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
            ) | Q(
                user_roles__tenant=user.tenant,
                user_roles__user__internal_profile__departments__id=department_id,
            )
        elif scope_type == DataScope.ScopeType.DEPARTMENT_TREE and department_id:
            from apps.tenants.models import Department

            allowed_department_ids = department_tree_ids(
                Department.objects.filter(tenant=user.tenant),
                {department_id},
            )
            allowed |= Q(
                user_roles__tenant=user.tenant,
                user_roles__user__internal_profile__department_id__in=allowed_department_ids,
            ) | Q(
                user_roles__tenant=user.tenant,
                user_roles__user__internal_profile__departments__id__in=allowed_department_ids,
            )
        elif scope_type == DataScope.ScopeType.CUSTOM:
            role_ids = _configured_ids(scope, "role_ids")
            if role_ids:
                allowed |= Q(pk__in=role_ids)
    return queryset.filter(allowed).distinct()


def filter_assignable_roles(user, queryset, permission_code, permission_cache=None):
    """Limit role binding to explicitly authorized tenant roles.

    An all scope may assign any tenant role. A custom scope must declare
    role_ids. Own and department scopes control target users, but do not by
    themselves grant privilege-escalating role assignment rights.
    """
    scopes = _permission_scopes(user, permission_code, permission_cache)
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
    platform_ids = set()
    platform_site_ids = set()
    site_ids = set()
    for scope in scopes:
        if scope["scope_type"] == DataScope.ScopeType.CUSTOM:
            allowed_ids.update(_configured_ids(scope, key))
            platform_ids.update(_configured_ids(scope, "platform_ids"))
            platform_site_ids.update(_configured_ids(scope, "platform_site_ids"))
            site_ids.update(_configured_ids(scope, "site_ids"))

    # Business master-data scopes are hierarchical.  A parent selection must
    # include tenant-local descendants so users do not need to enumerate every
    # store/warehouse manually.  Direct IDs remain valid for every resource.
    if resource in {"platform-sites", "stores"} and platform_ids:
        from apps.masterdata.models import PlatformSiteMaster, StoreMaster

        if resource == "platform-sites":
            allowed_ids.update(
                PlatformSiteMaster.objects.filter(
                    tenant=user.tenant, platform_id__in=platform_ids
                ).values_list("pk", flat=True)
            )
        else:
            allowed_ids.update(
                StoreMaster.objects.filter(
                    tenant=user.tenant, platform_id__in=platform_ids
                ).values_list("pk", flat=True)
            )
    if resource == "platform-sites" and site_ids:
        from apps.masterdata.models import CountrySiteMaster, PlatformSiteMaster

        country_codes = set(
            CountrySiteMaster.objects.filter(
                tenant=user.tenant, pk__in=site_ids
            ).values_list("country_code", flat=True)
        )
        allowed_ids.update(
            PlatformSiteMaster.objects.filter(
                tenant=user.tenant, country_code__in=country_codes
            ).values_list("pk", flat=True)
        )
    if resource == "stores" and platform_site_ids:
        from apps.masterdata.models import StoreMaster

        allowed_ids.update(
            StoreMaster.objects.filter(
                tenant=user.tenant, platform_site_id__in=platform_site_ids
            ).values_list("pk", flat=True)
        )
    if resource == "warehouses" and platform_ids:
        from apps.masterdata.models import WarehouseMaster

        allowed_ids.update(
            WarehouseMaster.objects.filter(
                tenant=user.tenant, service_platform_id__in=platform_ids
            ).values_list("pk", flat=True)
        )
    if resource in {"stores", "warehouses"} and site_ids:
        from apps.masterdata.models import CountrySiteMaster, StoreMaster, WarehouseMaster

        country_codes = set(
            CountrySiteMaster.objects.filter(
                tenant=user.tenant, pk__in=site_ids
            ).values_list("country_code", flat=True)
        )
        model = StoreMaster if resource == "stores" else WarehouseMaster
        allowed_ids.update(
            model.objects.filter(
                tenant=user.tenant, country_code__in=country_codes
            ).values_list("pk", flat=True)
        )
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
