from .models import DataScope, Permission, Role, UserRole


TENANT_ADMIN_ROLE_CODE = "administrator"
TENANT_ADMIN_ROLE_NAME = "管理员"


def user_is_tenant_administrator(user, tenant=None):
    """Return whether ``user`` currently holds the protected admin role."""
    if not user or not getattr(user, "is_active", False):
        return False
    tenant = tenant or getattr(user, "tenant", None)
    if tenant is None:
        return False
    return UserRole.objects.filter(
        tenant=tenant,
        user=user,
        role__tenant=tenant,
        role__code=TENANT_ADMIN_ROLE_CODE,
        role__status=Role.Status.ACTIVE,
    ).exists()


def sync_tenant_administrator_role(tenant):
    """Create or repair the tenant administrator role.

    This is intentionally a tenant role rather than a Django superuser: it can
    operate every registered business capability and delegate roles, while all
    normal tenant isolation, data-scope, audit and separation-of-duty checks
    continue to apply.
    """
    role, _ = Role.objects.update_or_create(
        tenant=tenant,
        code=TENANT_ADMIN_ROLE_CODE,
        defaults={"name": TENANT_ADMIN_ROLE_NAME, "status": Role.Status.ACTIVE},
    )
    role.permissions.set(Permission.objects.all())
    DataScope.objects.filter(tenant=tenant, role=role).exclude(scope_type=DataScope.ScopeType.ALL).delete()
    DataScope.objects.update_or_create(
        tenant=tenant,
        role=role,
        scope_type=DataScope.ScopeType.ALL,
        defaults={"config": {}},
    )
    return role
