from .models import DataScope, Permission, Role, UserRole


FINANCE_PERMISSION_CODES = (
    "finance.view",
    "finance.export",
    "finance.reconcile",
    "finance.import",
    "finance.exception.handle",
)

FINANCE_ROLE_CODES = {"finance", "finance_admin", "finance_manager"}
INTEGRATION_PERMISSION_CODES = (
    "integrations.manage",
    "integrations.view",
    "integrations.rotate",
    "integrations.run",
    "integrations.run_live_readonly",
    "integrations.store.view",
    "integrations.store.authorize",
    "integrations.store.revoke",
    "integrations.store.sync",
    "integrations.store.retry",
    "integrations.store_mapping.view",
    "integrations.store_mapping.manage",
    "integrations.product_mapping.view",
    "integrations.product_mapping.manage",
    "integrations.product_mapping.confirm",
    "integrations.warehouse.view",
    "integrations.warehouse.authorize",
    "integrations.warehouse.revoke",
    "integrations.credential.rotate",
    "integrations.config.view",
    "integrations.config.create",
    "integrations.config.update",
    "integrations.config.verify",
    "integrations.config.disable",
    "integrations.credential.clear",
    "integrations.audit.view",
)

INTEGRATION_ROLE_CODES = {"integration_admin", "tech_admin", "admin"}
MENU_ACTION_FALLBACKS = {
    "menu.system.security_operations.view": ("security.operations.view",),
}


def _is_view_permission(permission_code):
    return str(permission_code or "").endswith(".view")


def _cache_value(cache, key, factory):
    if cache is None:
        return factory()
    if key not in cache:
        cache[key] = factory()
    return cache[key]


def _active_role_ids(user, cache=None):
    key = ("active_role_ids", user.pk, user.tenant_id)
    return _cache_value(cache, key, lambda: list(
        UserRole.objects.filter(
            tenant_id=user.tenant_id,
            user=user,
            role__status=Role.Status.ACTIVE,
        ).values_list("role_id", flat=True)
    ))


def _menu_implied_view_role_ids(user, permission_code, role_ids, cache=None):
    """Return roles whose menu grant explicitly exposes a view action.

    Menu grants are intentionally read-only.  The generated menu registry
    stores the action codes behind each menu entry; only ``*.view`` actions
    are allowed to flow through this compatibility bridge.
    """
    if not _is_view_permission(permission_code) or not role_ids:
        return set()
    normalized_role_ids = tuple(sorted(role_ids))
    key = ("menu_implied_view_role_ids", permission_code, normalized_role_ids)
    return _cache_value(cache, key, lambda: {
        row["roles__id"]
        for row in Permission.objects.filter(
            permission_type=Permission.PermissionType.MENU,
            roles__id__in=normalized_role_ids,
        ).values("roles__id", "metadata", "code")
        if permission_code in _menu_action_codes(row)
    })


def _menu_implied_view_codes(user, role_ids=None):
    role_ids = _active_role_ids(user) if role_ids is None else role_ids
    if not role_ids:
        return set()
    rows = Permission.objects.filter(
        permission_type=Permission.PermissionType.MENU,
        roles__id__in=role_ids,
    ).values("metadata", "code")
    return {
        code
        for row in rows
        for code in _menu_action_codes(row)
        if _is_view_permission(code)
    }


def _menu_action_codes(row):
    metadata = row.get("metadata") or {}
    action_codes = metadata.get("action_codes") or []
    if action_codes:
        return action_codes
    # Older split-surface migrations did not yet persist the generated
    # registry's action_codes.  Preserve read-only compatibility for those
    # rows while keeping operation permissions explicit.
    menu_code = metadata.get("code") or row.get("code") or ""
    return MENU_ACTION_FALLBACKS.get(menu_code, (str(menu_code).removeprefix("menu."),))


def check_user_permission(user, permission_code, *, cache=None):
    if not user or not getattr(user, "is_active", False):
        return False

    if getattr(user, "is_superuser", False):
        return True

    key = ("permission_allowed", user.pk, user.tenant_id, permission_code)

    def resolve():
        role_ids = _active_role_ids(user, cache)

        # Endpoint declarations represent API operations.  A menu grant can only
        # satisfy the corresponding read/view action; mutations remain explicit.
        if Permission.objects.filter(
            code=permission_code,
            permission_type=Permission.PermissionType.ACTION,
            roles__id__in=role_ids,
        ).exists():
            return True
        return bool(_menu_implied_view_role_ids(user, permission_code, role_ids, cache))

    return _cache_value(cache, key, resolve)


def get_user_permission_codes(user, permission_type=None):
    """Return the active permission codes granted to ``user``.

    The legacy ``permissions`` list is intentionally still the union of all
    types.  Callers that render a particular authorization surface should pass
    ``permission_type`` so menu and field grants cannot accidentally be used
    as action grants.
    """
    if not user or not getattr(user, "is_active", False):
        return []
    queryset = Permission.objects.filter(
        roles__user_roles__user=user,
        roles__user_roles__tenant=user.tenant,
        roles__status=Role.Status.ACTIVE,
        roles__tenant=user.tenant,
    )
    if permission_type:
        queryset = queryset.filter(permission_type=permission_type)
    return list(queryset.order_by("code").values_list("code", flat=True).distinct())


def get_user_all_scope_permission_codes(user):
    """Return effective permissions granted through an all-tenant role.

    The result follows the same menu compatibility rule as runtime checks:
    menu grants may contribute only their explicitly declared ``*.view``
    actions. This keeps ``/auth/me`` capability data and delegation decisions
    aligned with the permissions the actor can actually exercise.
    """
    if not user or not getattr(user, "is_active", False):
        return set()
    if getattr(user, "is_superuser", False):
        return set(Permission.objects.values_list("code", flat=True))

    all_scope_role_ids = list(DataScope.objects.filter(
        tenant=user.tenant,
        role__tenant=user.tenant,
        role__status=Role.Status.ACTIVE,
        role__user_roles__tenant=user.tenant,
        role__user_roles__user=user,
        scope_type=DataScope.ScopeType.ALL,
    ).values_list("role_id", flat=True))
    codes = set(
        Permission.objects.filter(
            roles__tenant=user.tenant,
            roles__status=Role.Status.ACTIVE,
            roles__id__in=all_scope_role_ids,
        )
        .values_list("code", flat=True)
        .distinct()
    )
    codes.update(_menu_implied_view_codes(user, all_scope_role_ids))
    return codes


def get_user_delegable_permission_codes(user):
    """Return permissions that ``user`` may safely delegate to another role.

    A role manager's own ``system.roles.manage`` grant is not an implicit
    grant of every permission in the catalog.  Delegation is limited to
    permissions the actor already holds through an active role whose scope
    is ``all``.  Requiring an all-tenant scope here is deliberately
    conservative: a department/own/custom grant cannot be copied to a new
    role without first defining how its resource-specific scope should be
    intersected.

    Platform superusers are principals outside tenant roles and may operate
    on an explicitly selected tenant, so they retain the complete catalog.
    """
    return get_user_all_scope_permission_codes(user)


def get_undelegable_role_permission_codes(user, roles):
    """Return target-role permissions the actor is not allowed to delegate.

    This is deliberately usable by both assignment and activation paths.  A
    disabled role can contain privileges that a manager cannot create, and
    re-enabling it is equivalent to assigning those privileges to every bound
    user.
    """
    roles = list(roles)
    if not roles:
        return set()
    target_codes = set(
        Permission.objects.filter(roles__in=roles).values_list("code", flat=True).distinct()
    )
    return target_codes - get_user_delegable_permission_codes(user)


def get_user_permission_categories(user):
    """Return the role-derived permission sets used by ``/auth/me``.

    Superusers are platform principals rather than tenant roles, but exposing
    the complete trusted catalog keeps the client deterministic and enables
    platform-only menu/field definitions.  Ordinary users retain explicit
    role-derived categories.
    """
    if not user or not getattr(user, "is_active", False):
        return {"menu": [], "action": [], "field": []}
    if getattr(user, "is_superuser", False):
        permissions = Permission.objects.order_by("code")
        return {
            "menu": list(permissions.filter(permission_type=Permission.PermissionType.MENU).values_list("code", flat=True)),
            "action": list(permissions.filter(permission_type=Permission.PermissionType.ACTION).values_list("code", flat=True)),
            "field": list(permissions.filter(permission_type=Permission.PermissionType.FIELD).values_list("code", flat=True)),
        }
    role_ids = _active_role_ids(user)
    action_codes = set(
        Permission.objects.filter(
            permission_type=Permission.PermissionType.ACTION,
            roles__id__in=role_ids,
        ).values_list("code", flat=True)
    )
    action_codes.update(_menu_implied_view_codes(user, role_ids))
    return {
        "menu": get_user_permission_codes(user, Permission.PermissionType.MENU),
        "action": sorted(action_codes),
        "field": get_user_permission_codes(user, Permission.PermissionType.FIELD),
    }


def get_field_permission_map(user, permission_codes, *, default=True):
    """Resolve a group of field policies with two bounded catalog queries."""
    permission_codes = tuple(dict.fromkeys(permission_codes))
    if not permission_codes:
        return {}
    if not user or not getattr(user, "is_active", False):
        return {code: False for code in permission_codes}
    if getattr(user, "is_superuser", False):
        return {code: True for code in permission_codes}

    requested_rows = {
        row["code"]: row.get("metadata") or {}
        for row in Permission.objects.filter(
            code__in=permission_codes,
            permission_type=Permission.PermissionType.FIELD,
        ).values("code", "metadata")
    }

    def requested_resource(permission_code):
        metadata = requested_rows.get(permission_code) or {}
        resource = metadata.get("resource") if isinstance(metadata, dict) else None
        if resource:
            return resource
        parts = str(permission_code or "").split(".")
        return parts[2] if len(parts) > 2 and parts[0] == "field" else ""

    granted_rows = list(
        Permission.objects.filter(
            roles__user_roles__user=user,
            roles__user_roles__tenant_id=user.tenant_id,
            roles__tenant_id=user.tenant_id,
            roles__status=Role.Status.ACTIVE,
            permission_type=Permission.PermissionType.FIELD,
        )
        .values("code", "metadata")
        .distinct()
    )
    all_granted = {row["code"] for row in granted_rows}
    granted_by_resource = {}
    for row in granted_rows:
        metadata = row.get("metadata") or {}
        resource = metadata.get("resource") if isinstance(metadata, dict) else None
        if resource:
            granted_by_resource.setdefault(resource, set()).add(row["code"])

    result = {}
    for permission_code in permission_codes:
        resource = requested_resource(permission_code)
        granted = granted_by_resource.get(resource, set()) if resource else all_granted
        result[permission_code] = permission_code in granted if granted else default
    return result


def has_field_permission(user, permission_code, *, default=True):
    """Check a field grant with an explicit legacy compatibility policy.

    Field permissions were introduced after existing roles.  If no field
    grants exist for a user, the caller receives ``default`` (normally allow)
    so existing screens do not suddenly lose columns.  Once a role carries a
    field grant, the list is treated as an allow-list for that field.
    """
    return get_field_permission_map(user, [permission_code], default=default)[permission_code]


def get_permission_data_scopes(user, permission_code, *, cache=None):
    """Return scopes from active roles that actually grant one permission."""
    if not user or not getattr(user, "is_active", False) or not permission_code:
        return []

    if getattr(user, "is_superuser", False):
        return [{"scope_type": DataScope.ScopeType.ALL, "config": {"all": True}, "role_id": None}]

    key = ("permission_data_scopes", user.pk, user.tenant_id, permission_code)

    def resolve():
        role_ids = set(
            UserRole.objects.filter(
                tenant_id=user.tenant_id,
                user=user,
                role__status=Role.Status.ACTIVE,
                role__permissions__code=permission_code,
                role__permissions__permission_type=Permission.PermissionType.ACTION,
            ).values_list("role_id", flat=True)
        )
        role_ids.update(_menu_implied_view_role_ids(
            user,
            permission_code,
            role_ids=_active_role_ids(user, cache),
            cache=cache,
        ))

        return list(
            DataScope.objects.filter(
                tenant_id=user.tenant_id,
                role_id__in=role_ids,
                role__status=Role.Status.ACTIVE,
            )
            .distinct()
            .values("scope_type", "config", "role_id")
        )

    return _cache_value(cache, key, resolve)

def user_has_finance_access(user):
    if not user or not getattr(user, "is_active", False):
        return False

    if getattr(user, "is_superuser", False):
        return True

    # A menu grant is sufficient to open a read-only finance page.  Mutating
    # finance actions still require their explicit action permission below.
    if check_user_permission(user, "finance.view"):
        return True

    role_ids = UserRole.objects.filter(
        tenant=user.tenant,
        user=user,
        role__status=Role.Status.ACTIVE,
    ).values("role_id")

    has_finance_permission = Permission.objects.filter(
        code__in=FINANCE_PERMISSION_CODES,
        permission_type=Permission.PermissionType.ACTION,
        roles__id__in=role_ids,
    ).exists()
    if has_finance_permission:
        return True

    return Role.objects.filter(
        id__in=role_ids,
        tenant=user.tenant,
        code__in=FINANCE_ROLE_CODES,
        status=Role.Status.ACTIVE,
    ).exists()


def user_has_finance_permission(user, permission_code):
    if not user or not getattr(user, "is_active", False):
        return False

    if getattr(user, "is_superuser", False):
        return True

    if check_user_permission(user, permission_code):
        return True

    role_ids = UserRole.objects.filter(
        tenant=user.tenant,
        user=user,
        role__status=Role.Status.ACTIVE,
    ).values("role_id")
    if Permission.objects.filter(
        code=permission_code,
        permission_type=Permission.PermissionType.ACTION,
        roles__id__in=role_ids,
    ).exists():
        return True

    return Role.objects.filter(
        id__in=role_ids,
        tenant=user.tenant,
        code__in=FINANCE_ROLE_CODES,
        status=Role.Status.ACTIVE,
    ).exists()


def user_has_integration_access(user):
    if not user or not getattr(user, "is_active", False):
        return False

    if getattr(user, "is_superuser", False):
        return True

    if check_user_permission(user, "integrations.view"):
        return True

    role_ids = UserRole.objects.filter(
        tenant=user.tenant,
        user=user,
        role__status=Role.Status.ACTIVE,
    ).values("role_id")

    has_integration_permission = Permission.objects.filter(
        code__in=INTEGRATION_PERMISSION_CODES,
        permission_type=Permission.PermissionType.ACTION,
        roles__id__in=role_ids,
    ).exists()
    if has_integration_permission:
        return True

    return Role.objects.filter(
        id__in=role_ids,
        tenant=user.tenant,
        code__in=INTEGRATION_ROLE_CODES,
        status=Role.Status.ACTIVE,
    ).exists()


def user_has_integration_permission(user, permission_code):
    if not user or not getattr(user, "is_active", False):
        return False

    if getattr(user, "is_superuser", False):
        return True

    if check_user_permission(user, permission_code):
        return True

    role_ids = UserRole.objects.filter(
        tenant=user.tenant,
        user=user,
        role__status=Role.Status.ACTIVE,
    ).values("role_id")
    if Permission.objects.filter(
        code=permission_code,
        permission_type=Permission.PermissionType.ACTION,
        roles__id__in=role_ids,
    ).exists():
        return True

    return Role.objects.filter(
        id__in=role_ids,
        tenant=user.tenant,
        code__in=INTEGRATION_ROLE_CODES,
        status=Role.Status.ACTIVE,
    ).exists()


def get_user_data_scope(user):
    if not user or not getattr(user, "is_active", False):
        return []

    return list(
        DataScope.objects.filter(
            tenant=user.tenant,
            role__user_roles__user=user,
            role__user_roles__tenant=user.tenant,
            role__status=Role.Status.ACTIVE,
        )
        .distinct()
        .values("scope_type", "config", "role_id")
    )
