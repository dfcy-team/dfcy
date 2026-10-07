"""Tenant-local permission management: preview first, then atomic apply."""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.common.exceptions import StateConflict
from apps.common.responses import success_response
from apps.permissions.api_permissions import DeclaredApplicationPermission
from apps.permissions.authorization import authorization_version, template_version, effective_grants, preview_batch, load_preview, apply_batch
from apps.permissions.models import OrgMembership, PermissionChange, Role, RoleResourcePolicy, UserRole
from apps.permissions.resource_policies import RESOURCE_DEFINITIONS, validate_resource_policy, permission_resource
from apps.permissions.services import check_user_permission, get_permission_data_scopes
from apps.permissions.ui_p2_scopes import filter_system_users, filter_assignable_roles, require_all_scope
from apps.tenants.models import Department, Tenant
from .models import CustomUser
from .system_views import ensure_admin_role_assignment_allowed, ensure_privileged_target_action, ensure_roles_delegable


def managed_users(request, permission="system.users.manage"):
    return filter_system_users(request.user, CustomUser.objects.filter(tenant=request.user.tenant), permission)


def selected_roles(request, codes):
    if not isinstance(codes, list) or any(not isinstance(code, str) for code in codes):
        raise ValidationError("岗位编码必须为数组。")
    roles = list(filter_assignable_roles(request.user, Role.objects.filter(tenant=request.user.tenant, status="active"), "system.users.manage").filter(code__in=codes))
    if {role.code for role in roles} != set(codes):
        raise PermissionDenied("岗位不存在或超出当前用户可分配范围。")
    ensure_roles_delegable(request, roles)
    return roles


def validate_batch_targets(request, users, roles, operation, source):
    from apps.permissions.role_catalog import effective_administrator_bindings
    administrator_ids = set(effective_administrator_bindings(request.user.tenant).values_list("user_id", flat=True))
    removing_admins = set()
    for user in users:
        ensure_privileged_target_action(request, request.user.tenant, user)
        before = list(user.user_roles.filter(tenant=user.tenant, status="active").values_list("role__code", flat=True))
        retained = list(user.user_roles.filter(tenant=user.tenant, status="active").exclude(source=source, context_key="tenant").values_list("role__code", flat=True))
        after = retained + [role.code for role in roles] if operation == "transfer" else []
        ensure_admin_role_assignment_allowed(request, user.tenant, after, before_role_codes=before)
        if user.pk in administrator_ids and (operation == "offboard" or "administrator" not in after):
            removing_admins.add(user.pk)
    if removing_admins and not administrator_ids - removing_admins:
        raise StateConflict("该批次会移除最后一名租户管理员，整个批次不能提交。")


class AuthorizationVersionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return success_response({"authorization_version": authorization_version(request.user)})


class EffectivePermissionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "system.users.manage"

    def get(self, request, pk):
        user = get_object_or_404(managed_users(request), pk=pk)
        membership_id = request.query_params.get("membership_id")
        if membership_id:
            membership = get_object_or_404(OrgMembership, pk=membership_id, tenant=user.tenant, user=user, status="active")
            user._active_membership_id = membership.pk
        return success_response(effective_grants(user))


class AuthorizationSimulationView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    write_permission_code = "system.users.manage"

    def post(self, request):
        user = get_object_or_404(managed_users(request), pk=request.data.get("user_id"))
        if request.data.get("membership_id"):
            membership = get_object_or_404(OrgMembership, pk=request.data["membership_id"], tenant=user.tenant, user=user, status="active")
            user._active_membership_id = membership.pk
        code = request.data.get("permission_code")
        if not isinstance(code, str) or not code:
            raise ValidationError("请选择已登记的操作权限。")
        resource = request.data.get("resource_code") or permission_resource(code)
        scopes = get_permission_data_scopes(user, code, resource_code=resource)
        allowed = check_user_permission(user, code) and bool(scopes)
        reason = "授权允许；实际业务请求仍校验对象租户、字段和范围。" if allowed else "账户、成员、操作权限或数据范围未满足。"
        target = request.data.get("target")
        if target is not None:
            try:
                normalized = validate_resource_policy(user.tenant_id, resource, "custom", target)
            except DjangoValidationError as exc:
                raise ValidationError({"target": exc.messages}) from exc
            allowed = allowed and any(scope["scope_type"] == "all" or all(
                key in scope["config"] and set(values) <= set(scope["config"][key]) for key, values in normalized.items()
            ) for scope in scopes)
            reason = "候选对象匹配授权范围。" if allowed else "候选对象未匹配授权范围。"
        grants = effective_grants(user)
        sources = next((row["sources"] for row in grants["permissions"] if row["code"] == code), [])
        return success_response({"allowed": allowed, "reason": reason, "scopes": scopes, "sources": sources})


class AuthorizationBatchPreviewView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    write_permission_code = "system.users.manage"

    def post(self, request):
        ids = request.data.get("user_ids")
        if not isinstance(ids, list) or not 1 <= len(ids) <= 100 or any(type(value) is not int or value < 1 for value in ids) or len(set(ids)) != len(ids):
            raise ValidationError("请选择 1 至 100 名不同成员。")
        users = list(managed_users(request).filter(pk__in=ids).order_by("pk"))
        if {user.pk for user in users} != set(ids):
            raise PermissionDenied("成员不存在或超出当前用户管理范围。")
        operation = request.data.get("operation", "transfer")
        source = request.data.get("replace_source", "position")
        roles = selected_roles(request, request.data.get("role_codes", [])) if operation == "transfer" else []
        validate_batch_targets(request, users, roles, operation, source)
        return success_response(preview_batch(request.user, users, roles, operation=operation, replace_source=source, reason=request.data.get("reason", "")))


class AuthorizationBatchApplyView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    write_permission_code = "system.users.manage"

    @transaction.atomic
    def post(self, request):
        plan = load_preview(request.user, request.data.get("preview_token", ""))
        # All administrator-removal entries share this lock, before user locks.
        # A second batch must observe the first batch's remaining admins.
        Tenant.objects.select_for_update().get(pk=request.user.tenant_id)
        previous = PermissionChange.objects.filter(tenant=request.user.tenant, batch_id=plan["batch_id"]).first()
        if previous:
            return success_response({"batch_id": str(previous.batch_id), "changes": previous.changes,
                "affected_user_ids": [row["user_id"] for row in previous.changes], "replayed": True})
        users = managed_users(request).filter(pk__in=[row["user_id"] for row in plan["changes"]])
        roles = list(Role.objects.filter(tenant=request.user.tenant, pk__in=plan["role_ids"]))
        # Recheck delegation and privilege boundaries at commit, never trust
        # the older signed preview as a continuing authorization grant.
        selected_roles(request, [role.code for role in roles])
        validate_batch_targets(request, list(users), roles, plan["operation"], plan["replace_source"])
        return success_response(apply_batch(request.user, plan, users, roles))


class PermissionChangeCollectionView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "system.users.manage"

    def get(self, request):
        require_all_scope(request.user, self.read_permission_code)
        rows = PermissionChange.objects.filter(tenant=request.user.tenant).order_by("-created_at")[:50]
        return success_response({"results": list(rows.values("batch_id", "actor_id", "operation", "reason", "created_at", "changes"))})


class RoleResourcePolicyView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "system.roles.view"
    write_permission_code = "system.roles.manage"

    def payload(self, role):
        return {"template_version": template_version(role), "definitions": [{"resource_code": code, "name": value["name"], "dimensions": value["dimensions"]} for code, value in RESOURCE_DEFINITIONS.items()],
                "policies": list(role.resource_policies.order_by("resource_code", "permission_code").values("resource_code", "permission_code", "scope_type", "config"))}

    def get(self, request, pk):
        from .system_views import role_target
        return success_response(self.payload(role_target(request, pk)))

    @transaction.atomic
    def put(self, request, pk):
        from .system_views import role_target
        from apps.audit.services import write_operation_log
        require_all_scope(request.user, self.write_permission_code)
        ref = role_target(request, pk)
        role = Role.objects.select_for_update().get(pk=ref.pk)
        if role.code == "administrator":
            raise StateConflict("租户全权管理员的范围不能通过岗位表单修改。")
        ensure_roles_delegable(request, [role])
        if request.data.get("expected_version") != template_version(role):
            raise StateConflict("角色权限或范围已变化，请重新加载。")
        policies = request.data.get("policies")
        if not isinstance(policies, list) or len(policies) > 50:
            raise ValidationError("资源范围必须为最多 50 项的数组。")
        before = self.payload(role)
        normalized = []
        seen = set()
        for row in policies:
            if not isinstance(row, dict):
                raise ValidationError("资源范围条目必须是对象。")
            resource, code = row.get("resource_code"), row.get("permission_code", "*")
            if (resource, code) in seen:
                raise ValidationError("资源与操作范围重复。")
            seen.add((resource, code))
            if code != "*" and (permission_resource(code) != resource or not role.permissions.filter(code=code, permission_type="action").exists()):
                raise ValidationError("操作范围必须对应此角色已授予的资源操作。")
            try:
                config = validate_resource_policy(role.tenant_id, resource, row.get("scope_type"), row.get("config", {}))
            except DjangoValidationError as exc:
                raise ValidationError({"policies": exc.messages}) from exc
            normalized.append(RoleResourcePolicy(tenant=role.tenant, role=role, resource_code=resource, permission_code=code, scope_type=row["scope_type"], config=config))
        role.resource_policies.all().delete()
        for policy in normalized:
            policy.save()
        write_operation_log(tenant=role.tenant, user=request.user, module="system", action="role_resource_policies_update",
            object_type="role", object_id=role.pk, before_data=before, after_data=self.payload(role))
        return success_response(self.payload(role))


class OrgMembershipBindingView(APIView):
    permission_classes = [DeclaredApplicationPermission]
    read_permission_code = "system.users.manage"
    write_permission_code = "system.users.manage"

    def get(self, request, pk):
        user = get_object_or_404(managed_users(request), pk=pk)
        return success_response({"authorization_version": authorization_version(user), "memberships": list(user.org_memberships.filter(tenant=user.tenant).values("id", "department_id", "status", "valid_until")),
            "bindings": list(user.user_roles.filter(tenant=user.tenant).values("id", "role_id", "membership_id", "source", "context_key", "status", "valid_until"))})

    @transaction.atomic
    def put(self, request, pk):
        from apps.audit.services import write_operation_log
        user = get_object_or_404(managed_users(request).select_for_update(), pk=pk)
        ensure_privileged_target_action(request, user.tenant, user)
        if request.data.get("expected_version") != authorization_version(user):
            raise StateConflict("成员授权已变化，请重新加载。")
        department = get_object_or_404(Department, tenant=user.tenant, pk=request.data.get("department_id"), status="active")
        roles = selected_roles(request, request.data.get("role_codes", []))
        if any(role.code == "administrator" for role in roles):
            raise ValidationError("租户全权管理员只能使用租户级绑定。")
        until = request.data.get("valid_until")
        valid_until = parse_datetime(until) if isinstance(until, str) else None
        if until and (valid_until is None or valid_until.tzinfo is None):
            raise ValidationError("到期时间必须是包含时区的日期时间。")
        membership, _ = OrgMembership.objects.get_or_create(tenant=user.tenant, user=user, department=department)
        membership.status = request.data.get("status", "active")
        if membership.status not in {"active", "inactive"}:
            raise ValidationError("成员状态无效。")
        membership.save()
        source = "position"
        UserRole.objects.filter(tenant=user.tenant, user=user, membership=membership, source=source).delete()
        for role in roles:
            UserRole.objects.create(tenant=user.tenant, user=user, role=role, membership=membership,
                context_key=f"department:{department.pk}", source=source, valid_until=valid_until, assigned_by=request.user)
        write_operation_log(tenant=user.tenant, user=request.user, module="system", action="organization_role_binding_update", object_type="user", object_id=user.pk,
            after_data={"membership_id": membership.pk, "department_id": department.pk, "roles": [role.code for role in roles], "status": membership.status, "valid_until": valid_until})
        return success_response({"membership_id": membership.pk, "authorization_version": authorization_version(user)})
