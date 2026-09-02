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
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.permissions.role_catalog import TENANT_ADMIN_ROLE_CODE
from apps.permissions.ui_p2_scopes import (
    filter_assignable_roles,
    filter_departments,
    filter_roles,
    filter_system_users,
    require_all_scope,
    require_department_create_scope,
    require_user_create_scope,
)
from apps.tenants.models import Department

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
        return success_response(paginated_data(request, queryset, UserAdminSerializer, page=page, page_size=page_size))

    def post(self, request):
        serializer = UserAdminSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
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
        return success_response(UserAdminSerializer(user).data, status=201)


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
        return success_response(UserAdminSerializer(user).data)


class UserStatusView(APIView):
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
        is_active = request.data.get("is_active")
        if not isinstance(is_active, bool):
            raise ValidationError({"is_active": "A boolean value is required."})
        if user.pk == request.user.pk and not is_active:
            raise StateConflict("The current user cannot deactivate their own account.")
        before = user.is_active
        user.is_active = is_active
        user.save(update_fields=["is_active", "updated_at"])
        write_operation_log(
            tenant=request.user.tenant, user=request.user, module="system", action="user_status_change",
            object_type="user", object_id=user.pk, before_data={"is_active": before}, after_data={"is_active": is_active},
        )
        return success_response(UserAdminSerializer(user).data)


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
        queryset = CustomUser.objects.filter(tenant=request.user.tenant)
        user = get_object_or_404(
            filter_system_users(request.user, queryset, self.write_permission_code).select_for_update(),
            pk=pk,
        )
        serializer = UserRoleUpdateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        role_codes = serializer.validated_data["role_codes"]
        assignable_roles = filter_assignable_roles(
            request.user,
            Role.objects.filter(tenant=request.user.tenant, status=Role.Status.ACTIVE),
            self.write_permission_code,
        )
        roles = list(assignable_roles.filter(code__in=role_codes))
        allowed_codes = {role.code for role in roles}
        denied_codes = sorted(set(role_codes) - allowed_codes)
        if denied_codes:
            raise PermissionDenied(f"Roles outside the assignable data scope: {', '.join(denied_codes)}")
        before = list(user.user_roles.filter(tenant=request.user.tenant).values_list("role__code", flat=True))
        UserRole.objects.filter(tenant=request.user.tenant, user=user).delete()
        for role in roles:
            UserRole.objects.create(tenant=request.user.tenant, user=user, role=role)
        write_operation_log(
            tenant=request.user.tenant, user=request.user, module="system", action="user_roles_update",
            object_type="user", object_id=user.pk, before_data={"roles": before}, after_data={"roles": role_codes},
        )
        return success_response(UserAdminSerializer(user).data)


class UserRoleOptionCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "system.users.manage"
    write_permission_code = "system.users.manage"

    def get(self, request):
        queryset = Role.objects.filter(
            tenant=request.user.tenant,
            status=Role.Status.ACTIVE,
        )
        queryset = filter_assignable_roles(request.user, queryset, self.read_permission_code)
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
        queryset = Role.objects.filter(tenant=request.user.tenant).prefetch_related("permissions", "data_scopes")
        queryset = filter_roles(request.user, queryset, self.read_permission_code)
        search = request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(code__icontains=search))
        page, page_size = pagination(request)
        return success_response(paginated_data(request, queryset, RoleAdminSerializer, page=page, page_size=page_size))

    def post(self, request):
        require_all_scope(request.user, self.write_permission_code)
        serializer = RoleAdminSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        try:
            role = serializer.save(tenant=request.user.tenant)
        except IntegrityError as exc:
            # Serializer validation closes the normal duplicate path.  Keep a
            # concurrent create from leaking a database 500 when the unique
            # tenant/code constraint wins the race.
            raise ValidationError({"code": "Role code must be unique within the current tenant."}) from exc
        write_operation_log(
            tenant=request.user.tenant, user=request.user, module="system", action="role_create",
            object_type="role", object_id=role.pk, after_data={"code": role.code, "status": role.status},
        )
        return success_response(RoleAdminSerializer(role).data, status=201)


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
        tenant = request.user.tenant
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
            "users": UserAdminSerializer(users, many=True).data,
            "roles": RoleOptionSerializer(roles, many=True).data,
        })


class RolePermissionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "system.roles.view"
    write_permission_code = "system.roles.manage"

    @transaction.atomic
    def put(self, request, pk):
        require_all_scope(request.user, self.write_permission_code)
        role = get_object_or_404(
            Role.objects.select_for_update(),
            pk=pk,
            tenant=request.user.tenant,
        )
        if role.code == TENANT_ADMIN_ROLE_CODE:
            raise StateConflict("The built-in administrator role is synchronized from the permission catalog.")
        serializer = RolePermissionUpdateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        before = list(role.permissions.values_list("code", flat=True))
        before_scopes = list(role.data_scopes.values("scope_type", "config"))
        permission_codes = serializer.validated_data["permission_codes"]
        role.permissions.set(Permission.objects.filter(code__in=permission_codes))
        DataScope.objects.filter(tenant=request.user.tenant, role=role).delete()
        DataScope.objects.create(
            tenant=request.user.tenant,
            role=role,
            scope_type=serializer.validated_data["scope_type"],
            config=serializer.validated_data["scope_config"],
        )
        write_operation_log(
            tenant=request.user.tenant, user=request.user, module="system", action="role_permissions_update",
            object_type="role", object_id=role.pk,
            before_data={"permissions": before, "data_scopes": before_scopes},
            after_data={
                "permissions": permission_codes,
                "data_scopes": [{
                    "scope_type": serializer.validated_data["scope_type"],
                    "config": serializer.validated_data["scope_config"],
                }],
            },
        )
        return success_response(RoleAdminSerializer(role).data)


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
        role = get_object_or_404(
            Role.objects.select_for_update().prefetch_related("permissions", "data_scopes"),
            tenant=request.user.tenant,
            pk=pk,
        )
        if role.code == TENANT_ADMIN_ROLE_CODE:
            raise StateConflict("The built-in administrator role is synchronized from the permission catalog.")
        serializer = RoleAdminSerializer(
            role,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        before_data = {"name": role.name, "code": role.code, "status": role.status}
        try:
            role = serializer.save()
        except IntegrityError as exc:
            raise ValidationError({"code": "Role code must be unique within the current tenant."}) from exc
        write_operation_log(
            tenant=request.user.tenant, user=request.user, module="system", action="role_update",
            object_type="role", object_id=role.pk, before_data=before_data,
            after_data={"name": role.name, "code": role.code, "status": role.status},
        )
        return success_response(RoleAdminSerializer(role).data)

    @transaction.atomic
    def delete(self, request, pk):
        require_all_scope(request.user, self.write_permission_code)
        role = get_object_or_404(
            Role.objects.select_for_update(),
            tenant=request.user.tenant,
            pk=pk,
        )
        if role.code == TENANT_ADMIN_ROLE_CODE:
            raise StateConflict("The built-in administrator role cannot be deleted.")
        if role.user_roles.filter(tenant=request.user.tenant).exists():
            raise StateConflict("角色仍绑定用户，不能删除；请先停用并解除角色绑定。")
        before_data = {"name": role.name, "code": role.code, "status": role.status}
        role_id = role.pk
        role.delete()
        write_operation_log(
            tenant=request.user.tenant, user=request.user, module="system", action="role_delete",
            object_type="role", object_id=role_id, before_data=before_data,
        )
        return success_response({"deleted": True, "id": role_id})


class RoleStatusView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "system.roles.view"
    write_permission_code = "system.roles.manage"

    @transaction.atomic
    def post(self, request, pk):
        require_all_scope(request.user, self.write_permission_code)
        role = get_object_or_404(
            Role.objects.select_for_update().prefetch_related("permissions", "data_scopes"),
            tenant=request.user.tenant,
            pk=pk,
        )
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
            tenant=request.user.tenant, user=request.user, module="system", action="role_status_change",
            object_type="role", object_id=role.pk,
            before_data={"status": before}, after_data={"status": role.status},
        )
        return success_response(RoleAdminSerializer(role).data)


class PermissionCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "system.roles.view"
    write_permission_code = "system.roles.manage"

    def get(self, request):
        queryset = Permission.objects.all()
        module = request.query_params.get("module", "").strip()
        if module:
            queryset = queryset.filter(module=module)
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
