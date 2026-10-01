"""Auditable authorization previews and atomic, version-checked batches."""
import hashlib
import json
import uuid
from copy import copy

from django.core import signing
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from .lifecycle import permission_is_effective
from .models import DataScope, OrgMembership, PermissionChange, Role, UserRole
from .resource_policies import active_bindings
from .services import _menu_action_codes, get_permission_data_scopes

PREVIEW_SALT = "permission-batch-v1"


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def template_version(role):
    return digest({"id": role.pk, "status": role.status, "updated_at": role.updated_at,
                   "permissions": list(role.permissions.order_by("code").values("code", "metadata")),
                   "scopes": list(role.data_scopes.order_by("scope_type").values("scope_type", "config")),
                   "resource_policies": list(role.resource_policies.order_by("resource_code", "permission_code").values(
                       "resource_code", "permission_code", "scope_type", "config", "schema_version"))})


def authorization_version(user, capability_version=None):
    from apps.accounts.serializers import CurrentUserSerializer
    # Binding source/state is part of the concurrency contract even when two
    # bindings currently happen to grant the same effective operation.
    return digest({"capability_version": capability_version or CurrentUserSerializer(user).data["authorization_version"],
                   "bindings": list(UserRole.objects.filter(tenant_id=user.tenant_id, user=user).order_by("pk").values(
                       "id", "role_id", "source", "context_key", "membership_id", "status", "valid_until"))})


def binding_codes(bindings):
    codes = set()
    for binding in bindings:
        if binding.status != "active" or binding.role.status != "active":
            continue
        if binding.valid_until and binding.valid_until <= timezone.now():
            continue
        for permission in binding.role.permissions.all():
            if not permission_is_effective(permission.metadata):
                continue
            codes.add(permission.code)
            if permission.permission_type == "menu":
                codes.update(code for code in _menu_action_codes({"code": permission.code, "metadata": permission.metadata}) if code.endswith(".view"))
    from .lifecycle import inactive_permission_codes
    return codes - inactive_permission_codes()


def effective_grants(user):
    from .lifecycle import inactive_permission_codes
    inactive_codes = inactive_permission_codes()
    cache = {}
    bindings = list(active_bindings(user).select_related("role", "membership").prefetch_related("role__permissions"))
    rows = {}
    for binding in bindings:
        for permission in binding.role.permissions.all():
            if not permission_is_effective(permission.metadata):
                continue
            codes = [(permission.code, permission.permission_type, "explicit")]
            if permission.permission_type == "menu":
                codes.extend((code, "action", "legacy_menu") for code in _menu_action_codes({"code": permission.code, "metadata": permission.metadata}) if code.endswith(".view"))
            for code, surface, origin in codes:
                if code in inactive_codes:
                    continue
                row = rows.setdefault(code, {"code": code, "permission_type": surface, "allowed": bool(user.is_active), "sources": []})
                row["sources"].append({"role_id": binding.role_id, "role_code": binding.role.code,
                    "source": binding.source, "origin": origin, "membership_id": binding.membership_id,
                    "assigned_by_id": binding.assigned_by_id, "valid_until": binding.valid_until,
                    "scope": [scope for scope in get_permission_data_scopes(user, code, cache=cache) if scope.get("role_id") == binding.role_id] if surface == "action" else []})
    return {"user_id": user.pk, "authorization_version": authorization_version(user),
            "permissions": sorted(rows.values(), key=lambda row: row["code"]),
            "bindings": [{"id": binding.pk, "role_id": binding.role_id, "role_code": binding.role.code,
                          "source": binding.source, "membership_id": binding.membership_id, "valid_until": binding.valid_until}
                         for binding in bindings],
            "offboarding_checklist": [
                {"item": "账户与旧 access/refresh 令牌", "status": "active" if user.is_active else "blocked"},
                {"item": "所有岗位、组织与临时绑定", "status": "revoke_on_offboard"},
                {"item": "已生成导出文件", "status": "download_rechecked_and_blocked"},
                {"item": "未执行审批与异步任务", "status": "requires_current_actor_recheck"},
                {"item": "共享 RPA/API 凭据与外部会话归属", "status": "manual_owner_review_no_shared_credentials_deleted"},
            ]}


def preview_batch(actor, users, roles, *, operation, replace_source, reason):
    if operation not in {"transfer", "offboard"} or replace_source not in {"legacy", "position"}:
        raise ValidationError("批次类型或替换来源无效。")
    if not str(reason).strip():
        raise ValidationError("请填写授权变更原因。")
    changes = []
    role_versions = {str(role.pk): template_version(role) for role in roles}
    for user in users:
        bindings = list(UserRole.objects.filter(tenant=user.tenant, user=user).select_related("role").prefetch_related("role__permissions"))
        before_codes = binding_codes([binding for binding in bindings if binding.membership_id is None]) if user.is_active else set()
        preserved = [binding for binding in bindings if binding.source != replace_source or binding.context_key != "tenant"]
        after_bindings = preserved + [UserRole(tenant=user.tenant, user=user, role=role, source=replace_source) for role in roles]
        after_codes = binding_codes([binding for binding in after_bindings if binding.membership_id is None]) if operation == "transfer" and user.is_active else set()
        changes.append({"user_id": user.pk, "username": user.username, "authorization_version": authorization_version(user),
                        "added": sorted(after_codes - before_codes), "removed": sorted(before_codes - after_codes),
                        "retained": sorted(before_codes & after_codes),
                        "before_roles": sorted({binding.role.code for binding in bindings}),
                        "after_roles": sorted({binding.role.code for binding in after_bindings}) if operation == "transfer" else []})
    plan = {"actor_id": actor.pk, "tenant_id": actor.tenant_id, "operation": operation,
            "replace_source": replace_source, "reason": str(reason).strip()[:240],
            "role_ids": [role.pk for role in roles], "role_versions": role_versions, "changes": changes,
            "batch_id": str(uuid.uuid4())}
    return {"preview_token": signing.dumps(plan, salt=PREVIEW_SALT, compress=True), "changes": changes,
            "warnings": ["调岗仅替换选定来源的租户级绑定；其他岗位和组织绑定保留。"] if operation == "transfer" else
                        ["离职会停用账户及全部组织/角色绑定，旧令牌立即失效；共享凭据需按归属人工复核。"]}


def load_preview(actor, token):
    try:
        plan = signing.loads(token, salt=PREVIEW_SALT, max_age=600)
    except signing.BadSignature as exc:
        raise ValidationError("预览已过期或无效，请重新预览。") from exc
    if plan["actor_id"] != actor.pk or plan["tenant_id"] != actor.tenant_id:
        raise PermissionDenied("预览不属于当前操作者或租户。")
    return plan


@transaction.atomic
def apply_batch(actor, plan, users, roles):
    from apps.common.exceptions import StateConflict
    from apps.audit.services import write_operation_log
    existing = PermissionChange.objects.filter(batch_id=plan["batch_id"], tenant=actor.tenant).first()
    if existing:
        return {"batch_id": str(existing.batch_id), "changes": existing.changes, "affected_user_ids": [row["user_id"] for row in existing.changes], "replayed": True}
    locked_roles = list(Role.objects.select_for_update().filter(tenant=actor.tenant, pk__in=plan["role_ids"]).order_by("pk"))
    if {str(role.pk): template_version(role) for role in locked_roles} != plan["role_versions"]:
        raise StateConflict("岗位模板已被修改，请重新预览。")
    locked_users = {user.pk: user for user in users.select_for_update().order_by("pk")}
    # A simultaneous retry may have waited while the first request committed.
    # Recheck under the same target locks before comparing the old versions.
    existing = PermissionChange.objects.filter(batch_id=plan["batch_id"], tenant=actor.tenant).first()
    if existing:
        return {"batch_id": str(existing.batch_id), "changes": existing.changes,
                "affected_user_ids": [row["user_id"] for row in existing.changes], "replayed": True}
    if set(locked_users) != {row["user_id"] for row in plan["changes"]}:
        raise StateConflict("成员管理范围发生变化，请重新预览。")
    for change in plan["changes"]:
        if authorization_version(locked_users[change["user_id"]]) != change["authorization_version"]:
            raise StateConflict(f"用户 {change['user_id']} 的授权已变化，整个批次未提交，请重新预览。")
    for change in plan["changes"]:
        user = locked_users[change["user_id"]]
        if plan["operation"] == "offboard":
            user.is_active = False
            user.save(update_fields=["is_active"])
            UserRole.objects.filter(tenant=actor.tenant, user=user).update(status="inactive")
            OrgMembership.objects.filter(tenant=actor.tenant, user=user).update(status="inactive")
        else:
            UserRole.objects.filter(tenant=actor.tenant, user=user, source=plan["replace_source"], context_key="tenant").delete()
            for role in locked_roles:
                UserRole.objects.create(tenant=actor.tenant, user=user, role=role, source=plan["replace_source"], assigned_by=actor)
        change["new_authorization_version"] = authorization_version(user)
    audit = PermissionChange.objects.create(tenant=actor.tenant, actor=actor, batch_id=plan["batch_id"],
        reason=plan["reason"], operation=plan["operation"], changes=plan["changes"])
    write_operation_log(tenant=actor.tenant, user=actor, module="system", action="authorization_batch",
        object_type="permission_change", object_id=audit.pk, after_data={"batch_id": str(audit.batch_id), "operation": audit.operation,
        "reason": audit.reason, "affected_user_ids": sorted(locked_users)})
    return {"batch_id": str(audit.batch_id), "changes": audit.changes, "affected_user_ids": sorted(locked_users)}
