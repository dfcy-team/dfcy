from django.db import transaction
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


class UserCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "system.users.view"
    write_permission_code = "system.users.manage"

    def get(self, request):
        queryset = CustomUser.objects.filter(tenant=request.user.tenant).prefetch_related("user_roles__role")
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
        user = serializer.save()
        write_operation_log(
            tenant=request.user.tenant, user=request.user, module="system", action="user_create",
            object_type="user", object_id=user.pk, after_data={"username": user.username, "is_active": user.is_active},
        )
        return success_response(UserAdminSerializer(user).data, status=201)


class UserStatusView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "system.users.view"
    write_permission_code = "system.users.manage"

    def post(self, request, pk):
        queryset = CustomUser.objects.filter(tenant=request.user.tenant)
        user = get_object_or_404(filter_system_users(request.user, queryset, self.write_permission_code), pk=pk)
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


class UserRoleView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "system.users.view"
    write_permission_code = "system.users.manage"

    @transaction.atomic
    def put(self, request, pk):
        queryset = CustomUser.objects.filter(tenant=request.user.tenant)
        user = get_object_or_404(filter_system_users(request.user, queryset, self.write_permission_code), pk=pk)
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
        role = serializer.save(tenant=request.user.tenant)
        write_operation_log(
            tenant=request.user.tenant, user=request.user, module="system", action="role_create",
            object_type="role", object_id=role.pk, after_data={"code": role.code, "status": role.status},
        )
        return success_response(RoleAdminSerializer(role).data, status=201)


class RolePermissionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "system.roles.view"
    write_permission_code = "system.roles.manage"

    @transaction.atomic
    def put(self, request, pk):
        require_all_scope(request.user, self.write_permission_code)
        role = get_object_or_404(Role, pk=pk, tenant=request.user.tenant)
        serializer = RolePermissionUpdateSerializer(data=request.data)
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
                "recent_audit": list(audit),
                "credential_contract": "alias_fingerprint_reference_only",
            }
        )
