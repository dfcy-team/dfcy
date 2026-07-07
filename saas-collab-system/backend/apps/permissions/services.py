from .models import DataScope, Permission, Role, UserRole


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
