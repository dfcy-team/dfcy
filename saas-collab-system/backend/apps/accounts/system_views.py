from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.views import APIView

from apps.audit.models import OperationLog
from apps.audit.services import write_operation_log
from apps.common.exceptions import StateConflict
from apps.common.responses import paginated_data, success_response
from apps.integrations.models import PlatformIntegrationConfig
from apps.permissions.api_permissions import DeclaredApplicationPermission
from apps.permissions.api_permissions import InternalSuperuserPermission
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.permissions.role_catalog import (
    TENANT_ADMIN_ROLE_CODE,
    sync_tenant_administrator_role,
    user_is_tenant_administrator,
)
from apps.permissions.ui_p2_scopes import (
    filter_assignable_roles,
    filter_departments,
    filter_roles,
    filter_system_users,
    require_all_scope,
    require_department_create_scope,
    require_user_create_scope,
)
from apps.tenants.models import Department, Tenant

from .models import CustomUser
from .system_serializers import (
    DepartmentAdminSerializer,
    PermissionAdminSerializer,
    RoleAdminSerializer,
    RoleOptionSerializer,
    RolePermissionUpdateSerializer,
    UserAdminSerializer,
    UserPasswordResetSerializer,
    UserProfileUpdateSerializer,
    UserRoleUpdateSerializer,
    TenantAdminSerializer,
)


def positive_int(value, default, maximum=100):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValidationError("Pagination values must be integers.")
    if parsed < 1 or parsed > maximum:
        raise ValidationError(f"Pagination value must be between 1 and {maximum}.")
    return parsed


def pagination(request):
    return (
        positive_int(request.query_params.get("page", 1), 1),
        positive_int(request.query_params.get("page_size", 20), 20),
    )


def _is_platform_superuser(user):
    return bool(
        user
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and getattr(user, "user_type", None) == CustomUser.UserType.INTERNAL
        and getattr(user, "is_superuser", False)
    )


def requested_tenant(request, *, allow_missing=True):
    """Resolve the tenant context for system-management requests.

    Tenant users are intentionally rejected (rather than silently falling
    back) when they submit ``tenant_id``.  This makes an attempted cross-
    tenant operation visible to clients and avoids confusing audit context.
    Platform superusers may omit the parameter to operate on their own tenant
    or provide any existing tenant id.
    """
    raw_tenant_id = request.query_params.get("tenant_id")
    if raw_tenant_id in (None, ""):
        if allow_missing:
            return request.user.tenant
        raise ValidationError({"tenant_id": "tenant_id is required for this operation."})
    if not _is_platform_superuser(request.user):
        raise PermissionDenied("Only an internal platform superuser may select a target tenant.")
    try:
        tenant_id = int(raw_tenant_id)
    except (TypeError, ValueError):
        raise ValidationError({"tenant_id": "tenant_id must be a positive integer."})
    if tenant_id < 1:
        raise ValidationError({"tenant_id": "tenant_id must be a positive integer."})
    return get_object_or_404(Tenant, pk=tenant_id)


def role_target(request, pk=None):
    """Resolve role target and tenant while preserving cross-tenant context."""
    tenant = requested_tenant(request)
    if pk is None:
        return tenant
    # The explicit tenant_id is the only way for a platform user to switch
    # context.  Without it, role identifiers remain scoped to the actor's
    # current tenant just like ordinary tenant users.
    queryset = Role.objects.filter(pk=pk, tenant=tenant)
    role = queryset.first()
    if role is None:
        # Keep role identifiers tenant-safe for ordinary users and for a
        # superuser whose explicit context does not contain this role.
        from rest_framework.exceptions import NotFound

        raise NotFound("Role does not exist in the target tenant.")
    return role


def audit_context(request, target_tenant):
    """Stable non-secret actor/target context for cross-tenant audit rows."""
    return {
        "actor_tenant_id": getattr(request.user, "tenant_id", None),
        "target_tenant_id": getattr(target_tenant, "pk", None),
        "cross_tenant": getattr(request.user, "tenant_id", None) != getattr(target_tenant, "pk", None),
    }


def ensure_admin_role_assignment_allowed(request, target_tenant, role_codes, before_role_codes=None):
    after_codes = set(role_codes or ())
    before_codes = set(before_role_codes or ())
    administrator_changed = (TENANT_ADMIN_ROLE_CODE in after_codes) != (
        TENANT_ADMIN_ROLE_CODE in before_codes
    )
    # A create request has no previous assignment; granting administrator is
    # therefore always a protected transition.
    if before_role_codes is None and TENANT_ADMIN_ROLE_CODE in after_codes:
        administrator_changed = True
    if administrator_changed and not (
        _is_platform_superuser(request.user)
        or user_is_tenant_administrator(request.user, target_tenant)
    ):
        raise PermissionDenied("只有平台超级管理员或目标租户管理员可以授予管理员角色。")


def ensure_not_last_tenant_administrator(target_tenant, target_user, role_codes=None, is_active=None):
    """Protect the last enabled tenant administrator during replacement."""
    current_admin = UserRole.objects.filter(
        tenant=target_tenant,
        role__tenant=target_tenant,
        role__code=TENANT_ADMIN_ROLE_CODE,
        role__status=Role.Status.ACTIVE,
        user__is_active=True,
    ).filter(user=target_user).exists()
    if not current_admin:
        return
    retaining_role = TENANT_ADMIN_ROLE_CODE in set(role_codes or ()) if role_codes is not None else True
    retaining_active = target_user.is_active if is_active is None else bool(is_active)
    if not retaining_role or not retaining_active:
        enabled_count = UserRole.objects.filter(
            tenant=target_tenant,
            role__tenant=target_tenant,
            role__code=TENANT_ADMIN_ROLE_CODE,
            role__status=Role.Status.ACTIVE,
            user__is_active=True,
        ).values("user_id").distinct().count()
        if enabled_count <= 1:
            raise StateConflict("租户至少需要保留一名启用中的管理员。")


class TenantCollectionView(APIView):
    """Platform tenant directory, intentionally separate from tenant data APIs."""

    permission_classes = [InternalSuperuserPermission]

    def get(self, request):
        queryset = Tenant.objects.all()
        search = request.query_params.get("search", "").strip()
        status = request.query_params.get("status", "").strip()
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(code__icontains=search))
        if status in {choice.value for choice in Tenant.Status}:
            queryset = queryset.filter(status=status)
        page, page_size = pagination(request)
        return success_response(
            paginated_data(request, queryset, TenantAdminSerializer, page=page, page_size=page_size),
        )

    @transaction.atomic
    def post(self, request):
        serializer = TenantAdminSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tenant = serializer.save()
        sync_tenant_administrator_role(tenant)
        write_operation_log(
            tenant=tenant,
            user=request.user,
            module="system",
            action="tenant_create",
            object_type="tenant",
            object_id=tenant.pk,
            after_data={**audit_context(request, tenant), "name": tenant.name, "code": tenant.code, "status": tenant.status},
        )
        return success_response(TenantAdminSerializer(tenant).data, status=201)


class TenantDetailView(APIView):
    permission_classes = [InternalSuperuserPermission]

    @transaction.atomic
    def patch(self, request, pk):
        tenant = get_object_or_404(Tenant.objects.select_for_update(), pk=pk)
        serializer = TenantAdminSerializer(tenant, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        before = {"name": tenant.name, "code": tenant.code, "status": tenant.status}
        tenant = serializer.save()
        # Keep all pre-existing tenants repairable from the platform surface.
        sync_tenant_administrator_role(tenant)
        write_operation_log(
            tenant=tenant,
            user=request.user,
            module="system",
            action="tenant_update",
            object_type="tenant",
            object_id=tenant.pk,
            before_data={**audit_context(request, tenant), **before},
            after_data={**audit_context(request, tenant), "name": tenant.name, "code": tenant.code, "status": tenant.status},
        )
        return success_response(TenantAdminSerializer(tenant).data)


class DepartmentCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "system.organization.view"
    write_permission_code = "system.organization.manage"

    def get(self, request):
        queryset = Department.objects.filter(tenant=request.user.tenant).select_related("parent")
        queryset = filter_departments(request.user, queryset, self.read_permission_code)
        search = request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(name__icontains=search)
        page, page_size = pagination(request)
        return success_response(
            paginated_data(request, queryset, DepartmentAdminSerializer, page=page, page_size=page_size)
        )

    def post(self, request):
        serializer = DepartmentAdminSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        require_department_create_scope(
            request.user,
            self.write_permission_code,
            serializer.validated_data.get("parent_id"),
        )
        department = serializer.save(tenant=request.user.tenant)
        write_operation_log(
            tenant=request.user.tenant, user=request.user, module="system", action="department_create",
            object_type="department", object_id=department.pk, after_data={"name": department.name},
        )
        return success_response(DepartmentAdminSerializer(department).data, status=201)


class DepartmentDetailView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "system.organization.view"
    write_permission_code = "system.organization.manage"

    @transaction.atomic
    def patch(self, request, pk):
        queryset = Department.objects.filter(tenant=request.user.tenant).select_related("parent").select_for_update()
        department = get_object_or_404(
            filter_departments(request.user, queryset, self.write_permission_code), pk=pk
        )
        serializer = DepartmentAdminSerializer(
            department,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        if "parent_id" in serializer.validated_data:
            parent_id = serializer.validated_data["parent_id"]
            if parent_id is None and department.parent_id is not None:
                require_all_scope(request.user, self.write_permission_code)
            elif parent_id is not None:
                require_department_create_scope(request.user, self.write_permission_code, parent_id)
        before_data = {
            "name": department.name,
            "parent_id": department.parent_id,
            "status": department.status,
        }
        department = serializer.save()
        write_operation_log(
            tenant=request.user.tenant, user=request.user, module="system", action="department_update",
            object_type="department", object_id=department.pk, before_data=before_data,
            after_data={"name": department.name, "parent_id": department.parent_id, "status": department.status},
        )
        return success_response(DepartmentAdminSerializer(department).data)

    @transaction.atomic
    def delete(self, request, pk):
        queryset = Department.objects.filter(tenant=request.user.tenant).select_for_update()
        queryset = filter_departments(request.user, queryset, self.write_permission_code)
        department = get_object_or_404(queryset, pk=pk)
        if department.internal_profiles.exists() or department.assigned_internal_profiles.exists():
            raise StateConflict("部门内存在人员，不能删除。")
        if department.children.exists():
            raise StateConflict("部门下存在下级部门，请先删除下级部门。")
        before_data = {"name": department.name, "parent_id": department.parent_id}
        department_id = department.pk
        department.delete()
        write_operation_log(
            tenant=request.user.tenant, user=request.user, module="system", action="department_delete",
            object_type="department", object_id=department_id, before_data=before_data,
        )
        return success_response({"deleted": True, "id": department_id})


class UserCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "system.users.view"
    write_permission_code = "system.users.manage"

    def get(self, request):
        queryset = CustomUser.objects.filter(tenant=request.user.tenant).select_related(
            "internal_profile__department",
        ).prefetch_related(
            "user_roles__role",
            "internal_profile__departments",
        )
        queryset = filter_system_users(request.user, queryset, self.read_permission_code)
        search = request.query_params.get("search", "").strip()
        status = request.query_params.get("status", "").strip()
        if search:
            queryset = queryset.filter(Q(username__icontains=search) | Q(email__icontains=search))
        if status in {"active", "inactive"}:
            queryset = queryset.filter(is_active=status == "active")
        page, page_size = pagination(request)
        return success_response(
            paginated_data(
                request,
                queryset,
                UserAdminSerializer,
                page=page,
                page_size=page_size,
                serializer_context={"request": request},
            )
        )

    def post(self, request):
        serializer = UserAdminSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        ensure_admin_role_assignment_allowed(
            request,
            request.user.tenant,
            serializer.validated_data.get("role_codes", []),
        )
        require_user_create_scope(
            request.user,
            self.write_permission_code,
            serializer.validated_data.get("department_id"),
        )
        try:
            user = serializer.save()
        except IntegrityError as exc:
            raise ValidationError({"username": "该用户名已存在。"}) from exc
        write_operation_log(
            tenant=request.user.tenant, user=request.user, module="system", action="user_create",
            object_type="user", object_id=user.pk, after_data={"username": user.username, "is_active": user.is_active},
        )
        return success_response(UserAdminSerializer(user, context={"request": request}).data, status=201)


class UserDetailView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "system.users.view"
    write_permission_code = "system.users.manage"

    @transaction.atomic
    def patch(self, request, pk):
        queryset = CustomUser.objects.filter(tenant=request.user.tenant)
        user = get_object_or_404(
            filter_system_users(request.user, queryset, self.write_permission_code).select_for_update(),
            pk=pk,
        )
        serializer = UserProfileUpdateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        if "department_ids" in serializer.validated_data and user.user_type != CustomUser.UserType.INTERNAL:
            raise ValidationError({"department_ids": "只有内部用户可以配置部门归属。"})
        before = {
            "full_name": user.full_name,
            "department_ids": list(user.internal_profile.departments.values_list("id", flat=True))
            if hasattr(user, "internal_profile") else [],
        }
        if "full_name" in serializer.validated_data:
            user.full_name = serializer.validated_data["full_name"]
            user.save(update_fields=["full_name", "updated_at"])
        if "department_ids" in serializer.validated_data:
            department_ids = serializer.validated_data["department_ids"]
            profile = user.internal_profile
            profile.departments.set(department_ids)
            profile.department_id = department_ids[0] if department_ids else None
            profile.save(update_fields=["department", "updated_at"])
        write_operation_log(
            tenant=request.user.tenant, user=request.user, module="system", action="user_profile_update",
            object_type="user", object_id=user.pk, before_data=before,
            after_data={
                "full_name": user.full_name,
                "department_ids": list(user.internal_profile.departments.values_list("id", flat=True))
                if hasattr(user, "internal_profile") else [],
            },
        )
        return success_response(UserAdminSerializer(user, context={"request": request}).data)


class UserStatusView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "system.users.view"
    write_permission_code = "system.users.manage"

    @transaction.atomic
    def post(self, request, pk):
        target_tenant = requested_tenant(request)
        queryset = CustomUser.objects.filter(tenant=target_tenant)
        user = get_object_or_404(
            (
                queryset
                if _is_platform_superuser(request.user)
                else filter_system_users(request.user, queryset, self.write_permission_code)
            ).select_for_update(),
            pk=pk,
        )
        is_active = request.data.get("is_active")
        if not isinstance(is_active, bool):
            raise ValidationError({"is_active": "A boolean value is required."})
        if user.pk == request.user.pk and not is_active:
            raise StateConflict("The current user cannot deactivate their own account.")
        ensure_not_last_tenant_administrator(target_tenant, user, is_active=is_active)
        before = user.is_active
        user.is_active = is_active
        user.save(update_fields=["is_active", "updated_at"])
        write_operation_log(
            tenant=target_tenant, user=request.user, module="system", action="user_status_change",
            object_type="user", object_id=user.pk,
            before_data={**audit_context(request, target_tenant), "is_active": before},
            after_data={**audit_context(request, target_tenant), "is_active": is_active},
        )
        return success_response(UserAdminSerializer(user, context={"request": request}).data)


class UserPasswordResetView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "system.users.view"
    write_permission_code = "system.users.manage"

    @transaction.atomic
    def post(self, request, pk):
        queryset = CustomUser.objects.filter(tenant=request.user.tenant)
        user = get_object_or_404(
            filter_system_users(request.user, queryset, self.write_permission_code).select_for_update(),
            pk=pk,
        )
        serializer = UserPasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password", "updated_at"])
        write_operation_log(
            tenant=request.user.tenant,
            user=request.user,
            module="system",
            action="user_password_reset",
            object_type="user",
            object_id=user.pk,
            after_data={"username": user.username, "password_reset": True},
        )
        return success_response({"id": user.pk, "username": user.username, "password_reset": True})


class UserRoleView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "system.users.view"
    write_permission_code = "system.users.manage"

    @transaction.atomic
    def put(self, request, pk):
        target_tenant = requested_tenant(request)
        queryset = CustomUser.objects.filter(tenant=target_tenant)
        user = get_object_or_404(
            (
                queryset
                if _is_platform_superuser(request.user)
                else filter_system_users(request.user, queryset, self.write_permission_code)
            ).select_for_update(),
            pk=pk,
        )
        serializer = UserRoleUpdateSerializer(
            data=request.data,
            context={"request": request, "target_tenant": target_tenant},
        )
        serializer.is_valid(raise_exception=True)
        role_codes = serializer.validated_data["role_codes"]
        assignable_roles = filter_assignable_roles(
            request.user,
            Role.objects.filter(tenant=target_tenant, status=Role.Status.ACTIVE),
            self.write_permission_code,
        )
        if _is_platform_superuser(request.user):
            assignable_roles = Role.objects.filter(tenant=target_tenant, status=Role.Status.ACTIVE)
        roles = list(assignable_roles.filter(code__in=role_codes))
        allowed_codes = {role.code for role in roles}
        denied_codes = sorted(set(role_codes) - allowed_codes)
        if denied_codes:
            raise PermissionDenied(f"Roles outside the assignable data scope: {', '.join(denied_codes)}")
        before = list(user.user_roles.filter(tenant=target_tenant).values_list("role__code", flat=True))
        ensure_admin_role_assignment_allowed(
            request,
            target_tenant,
            role_codes,
            before_role_codes=before,
        )
        ensure_not_last_tenant_administrator(target_tenant, user, role_codes=role_codes)
        UserRole.objects.filter(tenant=target_tenant, user=user).delete()
        for role in roles:
            UserRole.objects.create(tenant=target_tenant, user=user, role=role)
        write_operation_log(
            tenant=target_tenant, user=request.user, module="system", action="user_roles_update",
            object_type="user", object_id=user.pk,
            before_data={**audit_context(request, target_tenant), "roles": before},
            after_data={**audit_context(request, target_tenant), "roles": role_codes},
        )
        return success_response(UserAdminSerializer(user, context={"request": request}).data)


class UserRoleOptionCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "system.users.manage"
    write_permission_code = "system.users.manage"

    def get(self, request):
        target_tenant = requested_tenant(request)
        queryset = Role.objects.filter(
            tenant=target_tenant,
            status=Role.Status.ACTIVE,
        )
        if _is_platform_superuser(request.user):
            queryset = queryset
        else:
            queryset = filter_assignable_roles(request.user, queryset, self.read_permission_code)
            if not user_is_tenant_administrator(request.user, target_tenant):
                queryset = queryset.exclude(code=TENANT_ADMIN_ROLE_CODE)
        search = request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(code__icontains=search))
        page, page_size = pagination(request)
        return success_response(
            paginated_data(request, queryset, RoleOptionSerializer, page=page, page_size=page_size)
        )


class RoleCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "system.roles.view"
    write_permission_code = "system.roles.manage"

    def get(self, request):
        target_tenant = requested_tenant(request)
        queryset = Role.objects.filter(tenant=target_tenant).prefetch_related("permissions", "data_scopes")
        if _is_platform_superuser(request.user):
            # Platform superusers can inspect every role in the selected
            # tenant; they are not constrained by the actor tenant's scopes.
            pass
        else:
            queryset = filter_roles(request.user, queryset, self.read_permission_code)
        search = request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(code__icontains=search))
        page, page_size = pagination(request)
        payload = paginated_data(
            request,
            queryset,
            RoleAdminSerializer,
            page=page,
            page_size=page_size,
            serializer_context={"request": request, "target_tenant": target_tenant},
        )
        payload["tenant"] = TenantAdminSerializer(target_tenant).data
        return success_response(payload)

    def post(self, request):
        target_tenant = requested_tenant(request)
        require_all_scope(request.user, self.write_permission_code)
        serializer = RoleAdminSerializer(
            data=request.data,
            context={"request": request, "target_tenant": target_tenant},
        )
        serializer.is_valid(raise_exception=True)
        try:
            role = serializer.save(tenant=target_tenant)
        except IntegrityError as exc:
            # Serializer validation closes the normal duplicate path.  Keep a
            # concurrent create from leaking a database 500 when the unique
            # tenant/code constraint wins the race.
            raise ValidationError({"code": "Role code must be unique within the current tenant."}) from exc
        write_operation_log(
            tenant=target_tenant, user=request.user, module="system", action="role_create",
            object_type="role", object_id=role.pk,
            after_data={**audit_context(request, target_tenant), "code": role.code, "status": role.status},
        )
        return success_response(RoleAdminSerializer(role, context={"request": request}).data, status=201)


class RoleScopeOptionsView(APIView):
    """Return tenant-scoped options needed to configure a custom role scope.

    This uses the role-management permission and all scope so administrators
    do not need unrelated user/organization read permissions merely to define
    a role's explicit scope.  All option querysets are tenant-filtered before
    serialization.
    """

    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "system.roles.manage"
    write_permission_code = "system.roles.manage"

    def get(self, request):
        require_all_scope(request.user, self.read_permission_code)
        tenant = requested_tenant(request)
        departments = Department.objects.filter(tenant=tenant).select_related("parent")
        users = CustomUser.objects.filter(tenant=tenant).select_related(
            "internal_profile__department",
        ).prefetch_related(
            "user_roles__role",
            "internal_profile__departments",
        )
        roles = Role.objects.filter(tenant=tenant, status=Role.Status.ACTIVE)
        return success_response({
            "departments": DepartmentAdminSerializer(departments, many=True).data,
            "users": UserAdminSerializer(users, many=True, context={"request": request}).data,
            "roles": RoleOptionSerializer(roles, many=True).data,
        })


class RolePermissionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "system.roles.view"
    write_permission_code = "system.roles.manage"

    @transaction.atomic
    def put(self, request, pk):
        require_all_scope(request.user, self.write_permission_code)
        role = role_target(request, pk)
        role = Role.objects.select_for_update().get(pk=role.pk)
        target_tenant = role.tenant
        if role.code == TENANT_ADMIN_ROLE_CODE:
            raise StateConflict("The built-in administrator role is synchronized from the permission catalog.")
        serializer = RolePermissionUpdateSerializer(
            data=request.data,
            context={"request": request, "target_tenant": target_tenant},
        )
        serializer.is_valid(raise_exception=True)
        before = list(role.permissions.values_list("code", flat=True))
        before_scopes = list(role.data_scopes.values("scope_type", "config"))
        permission_codes = serializer.validated_data["permission_codes"]
        role.permissions.set(Permission.objects.filter(code__in=permission_codes))
        DataScope.objects.filter(tenant=target_tenant, role=role).delete()
        DataScope.objects.create(
            tenant=target_tenant,
            role=role,
            scope_type=serializer.validated_data["scope_type"],
            config=serializer.validated_data["scope_config"],
        )
        write_operation_log(
            tenant=target_tenant, user=request.user, module="system", action="role_permissions_update",
            object_type="role", object_id=role.pk,
            before_data={**audit_context(request, target_tenant), "permissions": before, "data_scopes": before_scopes},
            after_data={
                **audit_context(request, target_tenant),
                "permissions": permission_codes,
                "menu_permissions": serializer.validated_data.get("menu_permission_codes", []),
                "action_permissions": serializer.validated_data.get("action_permission_codes", []),
                "field_permissions": serializer.validated_data.get("field_permission_codes", []),
                "data_scopes": [{
                    "scope_type": serializer.validated_data["scope_type"],
                    "config": serializer.validated_data["scope_config"],
                }],
            },
        )
        return success_response(RoleAdminSerializer(role, context={"request": request}).data)


class RoleDetailView(APIView):
    """Maintain the safe lifecycle of tenant roles.

    Roles are soft-disabled through ``status``.  Hard deletion is deliberately
    available only while no user is bound to the role and is never available
    for the catalog-managed tenant administrator role.
    """

    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "system.roles.view"
    write_permission_code = "system.roles.manage"

    @transaction.atomic
    def patch(self, request, pk):
        require_all_scope(request.user, self.write_permission_code)
        role_ref = role_target(request, pk)
        role = Role.objects.select_for_update().prefetch_related("permissions", "data_scopes").get(pk=role_ref.pk)
        target_tenant = role.tenant
        if role.code == TENANT_ADMIN_ROLE_CODE:
            raise StateConflict("The built-in administrator role is synchronized from the permission catalog.")
        serializer = RoleAdminSerializer(
            role,
            data=request.data,
            partial=True,
            context={"request": request, "target_tenant": target_tenant},
        )
        serializer.is_valid(raise_exception=True)
        before_data = {"name": role.name, "code": role.code, "status": role.status}
        try:
            role = serializer.save()
        except IntegrityError as exc:
            raise ValidationError({"code": "Role code must be unique within the current tenant."}) from exc
        write_operation_log(
            tenant=target_tenant, user=request.user, module="system", action="role_update",
            object_type="role", object_id=role.pk,
            before_data={**audit_context(request, target_tenant), **before_data},
            after_data={**audit_context(request, target_tenant), "name": role.name, "code": role.code, "status": role.status},
        )
        return success_response(RoleAdminSerializer(role, context={"request": request}).data)

    @transaction.atomic
    def delete(self, request, pk):
        require_all_scope(request.user, self.write_permission_code)
        role_ref = role_target(request, pk)
        role = Role.objects.select_for_update().get(pk=role_ref.pk)
        target_tenant = role.tenant
        if role.code == TENANT_ADMIN_ROLE_CODE:
            raise StateConflict("The built-in administrator role cannot be deleted.")
        if role.user_roles.filter(tenant=target_tenant).exists():
            raise StateConflict("角色仍绑定用户，不能删除；请先停用并解除角色绑定。")
        before_data = {"name": role.name, "code": role.code, "status": role.status}
        role_id = role.pk
        role.delete()
        write_operation_log(
            tenant=target_tenant, user=request.user, module="system", action="role_delete",
            object_type="role", object_id=role_id,
            before_data={**audit_context(request, target_tenant), **before_data},
        )
        return success_response({"deleted": True, "id": role_id})


class RoleStatusView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "system.roles.view"
    write_permission_code = "system.roles.manage"

    @transaction.atomic
    def post(self, request, pk):
        require_all_scope(request.user, self.write_permission_code)
        role_ref = role_target(request, pk)
        role = Role.objects.select_for_update().prefetch_related("permissions", "data_scopes").get(pk=role_ref.pk)
        target_tenant = role.tenant
        if role.code == TENANT_ADMIN_ROLE_CODE:
            raise StateConflict("The built-in administrator role cannot be disabled.")
        status = request.data.get("status")
        if status is None and isinstance(request.data.get("is_active"), bool):
            status = Role.Status.ACTIVE if request.data["is_active"] else Role.Status.INACTIVE
        if status not in {Role.Status.ACTIVE, Role.Status.INACTIVE}:
            raise ValidationError({"status": "status must be active or inactive."})
        if role.status == status:
            raise StateConflict("Role is already in the requested status.")
        before = role.status
        role.status = status
        role.save(update_fields=["status", "updated_at"])
        write_operation_log(
            tenant=target_tenant, user=request.user, module="system", action="role_status_change",
            object_type="role", object_id=role.pk,
            before_data={**audit_context(request, target_tenant), "status": before},
            after_data={**audit_context(request, target_tenant), "status": role.status},
        )
        return success_response(RoleAdminSerializer(role, context={"request": request}).data)


class PermissionCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "system.roles.view"
    write_permission_code = "system.roles.manage"

    def get(self, request):
        if request.query_params.get("tenant_id") not in (None, ""):
            # Permission catalog is global; accepting tenant_id here would
            # imply a tenant-specific catalog and make client context unsafe.
            requested_tenant(request)
        queryset = Permission.objects.all()
        module = request.query_params.get("module", "").strip()
        permission_type = request.query_params.get("permission_type", "").strip()
        if module:
            queryset = queryset.filter(module=module)
        if permission_type in {choice.value for choice in Permission.PermissionType}:
            queryset = queryset.filter(permission_type=permission_type)
        page, page_size = pagination(request)
        return success_response(
            paginated_data(request, queryset, PermissionAdminSerializer, page=page, page_size=page_size)
        )


class SecurityOperationsView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "security.operations.view"
    write_permission_code = "security.operations.view"

    def get(self, request):
        require_all_scope(request.user, self.read_permission_code)
        credentials = PlatformIntegrationConfig.objects.filter(tenant=request.user.tenant).values(
            "id", "platform", "account_alias", "environment", "status", "credential_fingerprint",
            "credential_key_version", "last_verified_at", "updated_at",
        )
        audit = OperationLog.objects.filter(tenant=request.user.tenant).values(
            "id", "module", "action", "object_type", "object_id", "created_at"
        )[:20]
        accounts = CustomUser.objects.filter(tenant=request.user.tenant).values(
            "id", "username", "full_name", "user_type", "is_active", "last_login", "updated_at"
        )
        return success_response(
            {
                "status": "connected",
                "summary": {
                    "active_users": CustomUser.objects.filter(tenant=request.user.tenant, is_active=True).count(),
                    "inactive_users": CustomUser.objects.filter(tenant=request.user.tenant, is_active=False).count(),
                    "active_roles": Role.objects.filter(tenant=request.user.tenant, status=Role.Status.ACTIVE).count(),
                    "credential_references": len(credentials),
                },
                "credential_references": list(credentials),
                "accounts": list(accounts),
                "recent_audit": list(audit),
                "credential_contract": "alias_fingerprint_reference_only",
            }
        )
