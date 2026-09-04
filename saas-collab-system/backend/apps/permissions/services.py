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


def check_user_permission(user, permission_code):
    if not user or not getattr(user, "is_active", False):
        return False

    if getattr(user, "is_superuser", False):
        return True

    role_ids = UserRole.objects.filter(
        tenant=user.tenant,
        user=user,
        role__status=Role.Status.ACTIVE,
    ).values("role_id")

    # Endpoint declarations represent button/API operations.  A menu or
    # field grant can never satisfy an action authorization check.
    return Permission.objects.filter(
        code=permission_code,
        permission_type=Permission.PermissionType.ACTION,
        roles__id__in=role_ids,
    ).exists()


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
    return {
        "menu": get_user_permission_codes(user, Permission.PermissionType.MENU),
        "action": get_user_permission_codes(user, Permission.PermissionType.ACTION),
        "field": get_user_permission_codes(user, Permission.PermissionType.FIELD),
    }


def has_field_permission(user, permission_code, *, default=True):
    """Check a field grant with an explicit legacy compatibility policy.

    Field permissions were introduced after existing roles.  If no field
    grants exist for a user, the caller receives ``default`` (normally allow)
    so existing screens do not suddenly lose columns.  Once a role carries a
    field grant, the list is treated as an allow-list for that field.
    """
    if not user or not getattr(user, "is_active", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    requested = Permission.objects.filter(
        code=permission_code,
        permission_type=Permission.PermissionType.FIELD,
    ).values_list("metadata", flat=True).first() or {}
    resource = requested.get("resource") if isinstance(requested, dict) else None
    if not resource:
        parts = str(permission_code or "").split(".")
        resource = parts[2] if len(parts) > 2 and parts[0] == "field" else ""

    # Field policies are resource-local.  A user who was explicitly granted
    # one users field must not accidentally lose all tenant fields, and a
    # users grant must never affect roles or tenants.
    granted_queryset = Permission.objects.filter(
        roles__user_roles__user=user,
        roles__user_roles__tenant=user.tenant,
        roles__tenant=user.tenant,
        roles__status=Role.Status.ACTIVE,
        permission_type=Permission.PermissionType.FIELD,
    )
    if resource:
        granted_queryset = granted_queryset.filter(metadata__resource=resource)
    granted = set(granted_queryset.values_list("code", flat=True).distinct())
    return permission_code in granted if granted else default


def get_permission_data_scopes(user, permission_code):
    """Return scopes from active roles that actually grant one permission."""
    if not user or not getattr(user, "is_active", False) or not permission_code:
        return []

    if getattr(user, "is_superuser", False):
        return [{"scope_type": DataScope.ScopeType.ALL, "config": {"all": True}, "role_id": None}]

    role_ids = UserRole.objects.filter(
        tenant=user.tenant,
        user=user,
        role__status=Role.Status.ACTIVE,
        role__permissions__code=permission_code,
        role__permissions__permission_type=Permission.PermissionType.ACTION,
    ).values("role_id")

    return list(
        DataScope.objects.filter(
            tenant=user.tenant,
            role_id__in=role_ids,
            role__status=Role.Status.ACTIVE,
        )
        .distinct()
        .values("scope_type", "config", "role_id")
    )

def user_has_finance_access(user):
    if not user or not getattr(user, "is_active", False):
        return False

    if getattr(user, "is_superuser", False):
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
