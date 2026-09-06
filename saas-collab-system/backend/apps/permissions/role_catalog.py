from .models import DataScope, Permission, Role, UserRole


TENANT_ADMIN_ROLE_CODE = "administrator"
TENANT_ADMIN_ROLE_NAME = "租户管理员"

# Stable built-in role identifiers.  The code values are part of existing
# migrations and API payloads, so only the display labels are corrected here.
BUILTIN_ROLE_DISPLAY_NAMES = {
    TENANT_ADMIN_ROLE_CODE: TENANT_ADMIN_ROLE_NAME,
    "operations": "业务运营人员",
    "product_developer": "产品开发人员",
    "002": "达人运营管理员",
}

BUILTIN_ROLE_DESCRIPTIONS = {
    TENANT_ADMIN_ROLE_CODE: "租户内置管理员，拥有当前租户全部已登记权限并负责角色委派。",
    "operations": "负责已授权业务模块的日常运营协同。",
    "product_developer": "负责产品开发、商品档案及相关生命周期工作。",
    "002": "负责达人档案、建联和送样履约等达人运营工作。",
}


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
        defaults={
            "name": TENANT_ADMIN_ROLE_NAME,
            "description": BUILTIN_ROLE_DESCRIPTIONS[TENANT_ADMIN_ROLE_CODE],
            "role_type": Role.RoleType.BUILTIN,
            "is_protected": True,
            "status": Role.Status.ACTIVE,
        },
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
