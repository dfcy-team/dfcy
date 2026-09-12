import json

from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
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
from apps.permissions.packages import permission_package_catalog
from apps.permissions.services import (
    check_user_permission,
    get_permission_data_scopes,
    get_user_delegable_permission_codes,
    get_undelegable_role_permission_codes,
)
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
    department_tree_ids,
    require_all_scope,
    require_department_create_scope,
    require_user_create_scope,
)
from apps.masterdata.models import (
    CountrySiteMaster,
    PlatformMaster,
    StoreMaster,
    SupplierMaster,
    WarehouseMaster,
)
from apps.tenants.models import Department, Tenant

from .models import CustomUser
from .system_serializers import (
    DepartmentAdminSerializer,
    PermissionAdminSerializer,
    RoleAdminSerializer,
    RoleCopySerializer,
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


def _query_bool(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _scope_signature(scope_type, config):
    """Normalize one data scope for safe before/after comparisons."""
    normalized = config if isinstance(config, dict) else {}
    if scope_type == DataScope.ScopeType.ALL:
        # Existing administrator rows historically use either {} or
        # {"all": true}; both represent the same effective scope.
        normalized = {"all": True}
    return scope_type, json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def _scope_changed(before_scopes, scope_type, config):
    current = {
        _scope_signature(scope.get("scope_type"), scope.get("config"))
        for scope in before_scopes
    }
    return current != {_scope_signature(scope_type, config)}

def _safe_department_tree(departments):
    """Build a visible forest and break legacy parent cycles fail-closed."""
    rows = list(departments)
    visible_ids = {row.pk for row in rows}
    parent_by_id = {row.pk: row.parent_id for row in rows}

    def safe_parent_id(node_id):
        parent_id = parent_by_id.get(node_id)
        if parent_id not in visible_ids:
            return None
        seen = {node_id}
        current = parent_id
        while current in visible_ids:
            if current in seen:
                return None
            seen.add(current)
            current = parent_by_id.get(current)
        return parent_id

    nodes = {
        row.pk: {
            "id": row.pk,
            "name": row.name,
            "parent_id": safe_parent_id(row.pk),
            "status": row.status,
            "children": [],
        }
        for row in rows
    }
    roots = []
    for node in nodes.values():
        parent_id = node["parent_id"]
        if parent_id in nodes:
            nodes[parent_id]["children"].append(node)
        else:
            node["parent_id"] = None
            roots.append(node)

    def sort_nodes(items):
        items.sort(key=lambda item: (item["name"].casefold(), item["id"]))
        for item in items:
            sort_nodes(item["children"])

    sort_nodes(roots)
    descendant_ids = {}

    def collect_descendants(node):
        values = {node["id"]}
        for child in node["children"]:
            values.update(collect_descendants(child))
        descendant_ids[node["id"]] = values
        return values

    for root in roots:
        collect_descendants(root)
    return roots, nodes, descendant_ids


def _department_user_counts(request, tenant, nodes, descendant_ids):
    users_permission = "system.users.view"
    if not check_user_permission(request.user, users_permission):
        return {department_id: None for department_id in nodes}
    if not get_permission_data_scopes(request.user, users_permission):
        return {department_id: None for department_id in nodes}

    users = CustomUser.objects.filter(tenant=tenant).prefetch_related(
        "internal_profile__departments",
    )
    users = filter_system_users(request.user, users, users_permission)
    assignments = []
    visible_ids = set(nodes)
    for user in users:
        profile = getattr(user, "internal_profile", None)
        if profile is None:
            continue
        department_ids = {department.pk for department in profile.departments.all()}
        if profile.department_id:
            department_ids.add(profile.department_id)
        assignments.append(department_ids & visible_ids)

    counts = {}
    for department_id in nodes:
        direct = sum(department_id in assigned for assigned in assignments)
        descendants = descendant_ids.get(department_id, {department_id}) - {department_id}
        descendant_count = sum(bool(assigned & descendants) for assigned in assignments)
        counts[department_id] = (direct, descendant_count)
    return counts


def _department_filter_ids(request, raw_department_id, include_descendants):
    try:
        department_id = int(raw_department_id)
    except (TypeError, ValueError):
        raise ValidationError({"department_id": "department_id 必须是正整数。"})
    if department_id < 1:
        raise ValidationError({"department_id": "department_id 必须是正整数。"})

    all_departments = Department.objects.filter(tenant=request.user.tenant)
    visible_departments = filter_departments(
        request.user,
        all_departments,
        "system.organization.view",
    )
    if not visible_departments.filter(pk=department_id).exists():
        from rest_framework.exceptions import NotFound

        raise NotFound("Department does not exist in the permitted organization scope.")
    visible_ids = set(visible_departments.values_list("pk", flat=True))
    if include_descendants:
        return department_tree_ids(all_departments, {department_id}) & visible_ids
    return {department_id}


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


def ensure_roles_delegable(request, roles):
    """Reject any role whose effective permissions exceed the actor's grant."""
    denied_codes = sorted(get_undelegable_role_permission_codes(request.user, roles))
    if denied_codes:
        raise PermissionDenied(
            f"Roles contain permissions outside the delegable grant: {', '.join(denied_codes)}"
        )


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


class DepartmentTreeView(APIView):
    """Return the caller's tenant-scoped organization as a visible forest."""

    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "system.organization.view"
    write_permission_code = "system.organization.manage"

    def get(self, request):
        tenant = request.user.tenant
        departments = filter_departments(
            request.user,
            Department.objects.filter(tenant=tenant).select_related("parent"),
            self.read_permission_code,
        )
        roots, nodes, descendant_ids = _safe_department_tree(departments)
        counts = _department_user_counts(request, tenant, nodes, descendant_ids)
        for department_id, node in nodes.items():
            value = counts.get(department_id)
            node["direct_user_count"] = value[0] if isinstance(value, tuple) else value
            node["descendant_user_count"] = value[1] if isinstance(value, tuple) else value
        return success_response({
            "items": roots,
            "results": roots,
            "count": len(nodes),
            "tenant": {"id": tenant.pk, "name": tenant.name, "code": tenant.code},
        })


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
        raw_department_id = request.query_params.get("department_id")
        if raw_department_id not in (None, ""):
            department_ids = _department_filter_ids(
                request,
                raw_department_id,
                _query_bool(request.query_params.get("include_descendants")),
            )
            queryset = queryset.filter(
                Q(internal_profile__department_id__in=department_ids)
                | Q(internal_profile__departments__id__in=department_ids)
            ).distinct()
        if _query_bool(request.query_params.get("unassigned")):
            queryset = queryset.filter(
                user_type=CustomUser.UserType.INTERNAL,
                internal_profile__department__isnull=True,
                internal_profile__departments__isnull=True,
            )
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
        role_codes = serializer.validated_data.get("role_codes", [])
        assignable_roles = filter_assignable_roles(
            request.user,
            Role.objects.filter(
                tenant=request.user.tenant,
                status=Role.Status.ACTIVE,
            ),
            self.write_permission_code,
        )
        denied_role_codes = sorted(
            set(role_codes) - set(assignable_roles.filter(code__in=role_codes).values_list("code", flat=True))
        )
        if denied_role_codes:
            raise PermissionDenied(
                f"Roles outside the assignable data scope: {', '.join(denied_role_codes)}"
            )
        roles = list(assignable_roles.filter(code__in=role_codes))
        ensure_roles_delegable(request, roles)
        ensure_admin_role_assignment_allowed(
            request,
            request.user.tenant,
            role_codes,
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
        department_update = (
            "department_id" in serializer.validated_data
            or "department_ids" in serializer.validated_data
        )
        if department_update and user.user_type != CustomUser.UserType.INTERNAL:
            raise ValidationError({"department_ids": "只有内部用户可以配置部门归属。"})
        profile = getattr(user, "internal_profile", None)
        if department_update and profile is None:
            raise ValidationError({"department_ids": "内部用户缺少组织档案，无法配置部门归属。"})
        current_department_ids = (
            list(profile.departments.values_list("id", flat=True))
            if profile is not None else []
        )
        if department_update:
            if "department_ids" in serializer.validated_data:
                department_ids = list(serializer.validated_data["department_ids"])
            else:
                department_ids = current_department_ids
            if "department_id" in serializer.validated_data:
                primary_department_id = serializer.validated_data["department_id"]
                if primary_department_id is not None and primary_department_id not in department_ids:
                    department_ids.insert(0, primary_department_id)
            elif "department_ids" in serializer.validated_data:
                primary_department_id = department_ids[0] if department_ids else None
            else:
                primary_department_id = profile.department_id
            visible_departments = filter_departments(
                request.user,
                Department.objects.filter(tenant=request.user.tenant),
                self.write_permission_code,
            )
            visible_department_ids = set(visible_departments.values_list("id", flat=True))
            selected_ids = set(department_ids)
            if primary_department_id is not None:
                selected_ids.add(primary_department_id)
            if not selected_ids.issubset(visible_department_ids):
                raise PermissionDenied("所选部门超出当前用户管理数据范围。")
        else:
            department_ids = current_department_ids
            primary_department_id = profile.department_id if profile is not None else None
        before = {
            "full_name": user.full_name,
            "email_masked": UserAdminSerializer(user).data.get("email_masked", ""),
            "phone_masked": UserAdminSerializer(user).data.get("phone_masked", ""),
            "department_id": profile.department_id if profile is not None else None,
            "department_ids": current_department_ids,
        }
        user_updates = []
        for field in ("full_name", "email", "phone"):
            if field in serializer.validated_data:
                setattr(user, field, serializer.validated_data[field])
                user_updates.append(field)
        if user_updates:
            user.save(update_fields=[*user_updates, "updated_at"])
        if department_update:
            profile.departments.set(department_ids)
            profile.department_id = primary_department_id
            profile.save(update_fields=["department", "updated_at"])
        write_operation_log(
            tenant=request.user.tenant, user=request.user, module="system", action="user_profile_update",
            object_type="user", object_id=user.pk, before_data=before,
            after_data={
                "full_name": user.full_name,
                "email_masked": UserAdminSerializer(user).data.get("email_masked", ""),
                "phone_masked": UserAdminSerializer(user).data.get("phone_masked", ""),
                "department_id": profile.department_id if profile is not None else None,
                "department_ids": list(profile.departments.values_list("id", flat=True))
                if profile is not None else [],
            },
        )
        return success_response(UserAdminSerializer(user, context={"request": request}).data)

    @transaction.atomic
    def delete(self, request, pk):
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
        if user.pk == request.user.pk:
            raise StateConflict("当前登录用户不能删除自己的账号，请先停用或交接。")
        ensure_not_last_tenant_administrator(target_tenant, user, role_codes=[])
        user_id = user.pk
        username = user.username
        try:
            user.delete()
        except ProtectedError as exc:
            blocker_names = sorted({
                str(getattr(obj._meta, "verbose_name", "业务数据"))
                for obj in exc.protected_objects
            })
            detail = "、".join(blocker_names[:3])
            suffix = f"（{detail}）" if detail else ""
            raise StateConflict(f"用户存在业务数据关联{suffix}，无法删除，只能停用。") from exc
        write_operation_log(
            tenant=target_tenant, user=request.user, module="system", action="user_delete",
            object_type="user", object_id=user_id,
            before_data={**audit_context(request, target_tenant), "username": username},
        )
        return success_response({"deleted": True, "id": user_id, "username": username})


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
        ensure_roles_delegable(request, roles)
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


class RoleCopyView(APIView):
    """Copy a tenant-local role into a new, editable custom role."""

    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "system.roles.view"
    write_permission_code = "system.roles.manage"

    @transaction.atomic
    def post(self, request, pk):
        target_tenant = requested_tenant(request)
        require_all_scope(request.user, self.write_permission_code)
        source = get_object_or_404(
            Role.objects.select_for_update().filter(tenant=target_tenant).prefetch_related("permissions", "data_scopes"),
            pk=pk,
        )

        source_permission_codes = set(source.permissions.values_list("code", flat=True))
        if not _is_platform_superuser(request.user) and not user_is_tenant_administrator(
            request.user, target_tenant
        ):
            delegable_permissions = get_user_delegable_permission_codes(request.user)
            denied_permissions = sorted(source_permission_codes - delegable_permissions)
            if denied_permissions:
                raise PermissionDenied(
                    "不能复制包含当前用户无权委派权限的角色：" + ", ".join(denied_permissions)
                )

        serializer = RoleCopySerializer(
            data=request.data,
            context={"request": request, "target_tenant": target_tenant},
        )
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data
        try:
            copied = Role.objects.create(
                tenant=target_tenant,
                name=validated["name"],
                code=validated["code"],
                description=validated.get("description", source.description),
                role_type=Role.RoleType.CUSTOM,
                is_protected=False,
                status=Role.Status.ACTIVE,
            )
            copied.permissions.set(source.permissions.all())
            # Restrict the copied scope rows to the resolved tenant even if a
            # legacy database row was manually corrupted to point elsewhere.
            source_scopes = list(
                source.data_scopes.filter(tenant=target_tenant).values("scope_type", "config")
            )
            DataScope.objects.bulk_create([
                DataScope(
                    tenant=target_tenant,
                    role=copied,
                    scope_type=scope["scope_type"],
                    config=scope["config"],
                )
                for scope in source_scopes
            ])
        except IntegrityError as exc:
            raise ValidationError({"code": "当前租户内的系统标识已存在，请换一个。"}) from exc

        write_operation_log(
            tenant=target_tenant,
            user=request.user,
            module="system",
            action="role_copy",
            object_type="role",
            object_id=copied.pk,
            before_data={
                **audit_context(request, target_tenant),
                "source_role_id": source.pk,
                "source_role_code": source.code,
                "permissions": sorted(source_permission_codes),
                "data_scopes": source_scopes,
            },
            after_data={
                **audit_context(request, target_tenant),
                "role_id": copied.pk,
                "name": copied.name,
                "code": copied.code,
                "role_type": copied.role_type,
                "is_protected": copied.is_protected,
                "status": copied.status,
                "permissions": sorted(source_permission_codes),
                "data_scopes": source_scopes,
            },
        )
        copied = Role.objects.prefetch_related("permissions", "data_scopes").get(pk=copied.pk)
        return success_response(
            RoleAdminSerializer(
                copied,
                context={"request": request, "target_tenant": target_tenant},
            ).data,
            status=201,
        )


class RoleScopeOptionsView(APIView):
    """Return tenant-scoped business dimensions for a custom role scope.

    Tenant isolation is implicit and cannot be selected in this response.  We
    intentionally do not return departments, users, or roles: those were the
    old organization-scope dimensions and are no longer valid for new role
    permission submissions.  Every queryset is filtered to the target tenant
    before serialization so a platform administrator cannot accidentally use
    an object from another tenant.
    """

    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "system.roles.manage"
    write_permission_code = "system.roles.manage"

    def get(self, request):
        require_all_scope(request.user, self.read_permission_code)
        tenant = requested_tenant(request)
        active = "active"
        return success_response({
            "platforms": list(
                PlatformMaster.objects.filter(tenant=tenant, status=active)
                .values("id", "code", "name")
            ),
            "sites": list(
                CountrySiteMaster.objects.filter(tenant=tenant, status=active)
                .values("id", "code", "name", "country_code", "currency")
            ),
            "stores": list(
                StoreMaster.objects.filter(tenant=tenant, status=active)
                .values("id", "code", "name", "country_code", "platform_id")
            ),
            "warehouses": list(
                WarehouseMaster.objects.filter(tenant=tenant, status=active)
                .values("id", "code", "name", "country_code")
            ),
            "suppliers": list(
                SupplierMaster.objects.filter(tenant=tenant, status=active)
                .values("id", "code", "name")
            ),
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
            raise StateConflict("租户管理员角色由权限目录自动同步，不能手工修改权限。")
        serializer = RolePermissionUpdateSerializer(
            data=request.data,
            context={"request": request, "target_tenant": target_tenant},
        )
        serializer.is_valid(raise_exception=True)
        requested_permission_codes = set(serializer.validated_data["permission_codes"])
        if not _is_platform_superuser(request.user) and not user_is_tenant_administrator(
            request.user, target_tenant
        ):
            delegable_permissions = get_user_delegable_permission_codes(request.user)
            denied_permissions = sorted(requested_permission_codes - delegable_permissions)
            if denied_permissions:
                raise PermissionDenied(
                    "不能配置当前用户无权委派的权限：" + ", ".join(denied_permissions)
                )
        before = list(role.permissions.values_list("code", flat=True))
        before_scopes = list(role.data_scopes.values("scope_type", "config"))
        permission_codes = set(serializer.validated_data["permission_codes"])
        package_selections = serializer.validated_data.get("package_selections")
        # Quick assignment is module-local.  Any module that was not touched
        # by the quick form keeps its existing canonical grants, so selecting
        # one package cannot accidentally wipe unrelated responsibilities.
        if package_selections is not None:
            touched_modules = set(package_selections)
            permission_codes.update(
                role.permissions.exclude(module__in=touched_modules).values_list("code", flat=True)
            )
        permission_codes = sorted(permission_codes)

        # Retired menu grants stay attached for auditability even though they
        # are no longer offered in the active permission directory.  A normal
        # role edit must not silently revoke them merely because the frontend
        # no longer renders the retired checkbox.
        permission_codes = sorted(set(permission_codes) | set(
            role.permissions.filter(
                permission_type=Permission.PermissionType.MENU,
                metadata__registry_status="inactive",
            ).values_list("code", flat=True)
        ))

        # A role manager may delegate only permissions already granted to the
        # actor through an all-tenant role.  Existing grants that were not
        # touched by a quick package remain intact, but a request may not use
        # role management itself as an implicit grant of unrelated catalog
        # capabilities.
        if not _is_platform_superuser(request.user) and not user_is_tenant_administrator(
            request.user, target_tenant
        ):
            delegable_permissions = get_user_delegable_permission_codes(request.user)
            if _scope_changed(
                before_scopes,
                serializer.validated_data["scope_type"],
                serializer.validated_data["scope_config"],
            ) and (set(before) - delegable_permissions):
                raise PermissionDenied(
                    "目标角色包含调用者无权委派的现有权限，不能修改其数据范围。"
                )
            before_set = set(before)
            newly_granted = set(permission_codes) - before_set
            denied_permissions = sorted(
                newly_granted - delegable_permissions
            )
            if denied_permissions:
                raise PermissionDenied(
                    "只能委派调用者已有全部数据范围的权限：" + ", ".join(denied_permissions)
                )

        # department_tree is implemented by the system organization/user/role
        # scope helpers.  Reject mixed roles here instead of persisting a
        # globally valid DataScope value that unrelated modules would interpret
        # inconsistently or silently as no data.
        if serializer.validated_data["scope_type"] == DataScope.ScopeType.DEPARTMENT_TREE:
            unsupported_modules = sorted(
                set(
                    Permission.objects.filter(code__in=permission_codes)
                    .exclude(module="system")
                    .values_list("module", flat=True)
                )
            )
            if unsupported_modules:
                raise ValidationError({
                    "scope_type": "department_tree 仅支持 system 模块权限，不能与其他模块混用。"
                })

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
                "package_selections": package_selections,
                "extra_permission_codes": serializer.validated_data.get("extra_permission_codes", []),
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
        if role.code == TENANT_ADMIN_ROLE_CODE or role.is_protected:
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
        if role.code == TENANT_ADMIN_ROLE_CODE or role.is_protected:
            raise StateConflict("内置受保护角色不能删除。")
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
        if role.code == TENANT_ADMIN_ROLE_CODE or role.is_protected:
            raise StateConflict("内置受保护角色不能停用。")
        status = request.data.get("status")
        if status is None and isinstance(request.data.get("is_active"), bool):
            status = Role.Status.ACTIVE if request.data["is_active"] else Role.Status.INACTIVE
        if status not in {Role.Status.ACTIVE, Role.Status.INACTIVE}:
            raise ValidationError({"status": "status must be active or inactive."})
        if role.status == status:
            raise StateConflict("Role is already in the requested status.")
        if status == Role.Status.ACTIVE:
            ensure_roles_delegable(request, [role])
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
        queryset = Permission.objects.exclude(
            Q(
                permission_type=Permission.PermissionType.MENU,
                metadata__registry_status="inactive",
            )
        )
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


class PermissionPackageCollectionView(APIView):
    """Return quick-assignment metadata derived from the trusted catalog."""

    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "system.roles.view"
    write_permission_code = "system.roles.manage"

    def get(self, request):
        if request.query_params.get("tenant_id") not in (None, ""):
            # The catalog is global, but an explicit tenant context must still
            # pass the same platform-superuser boundary as role operations.
            requested_tenant(request)
        return success_response({
            "levels": [
                {"code": "none", "name": "无权限"},
                {"code": "read", "name": "只读"},
                {"code": "operate", "name": "可操作"},
                {"code": "admin", "name": "模块管理员"},
            ],
            "packages": permission_package_catalog(),
            "high_risk_policy": "operate/admin 不自动授予高风险权限，需通过 extra_permission_codes 明确确认。",
        })


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
