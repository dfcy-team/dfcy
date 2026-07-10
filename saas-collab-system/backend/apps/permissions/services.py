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

    return Permission.objects.filter(code=permission_code, roles__id__in=role_ids).exists()


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
