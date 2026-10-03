"""Reviewed deployment companion. Default: inspect only; never sends Feishu.

Run in Django shell, on the approved release, by the architect.
apply requires FEISHU_SCOPE_APPROVED=True and REVIEWED_SOURCE_HASHES populated.
rollback additionally requires the exact result receipt from a successful apply.
All writes use existing audited application views inside one outer transaction.
"""
import hashlib
import inspect
import json

from django.db import connection, transaction
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.exceptions import PermissionDenied

from apps.accounts.models import CustomUser
from apps.accounts.system_views import RoleCollectionView, RolePermissionView, RoleStatusView
from apps.accounts.authorization_views import RoleResourcePolicyView, AuthorizationBatchPreviewView, AuthorizationBatchApplyView
from apps.permissions.authorization import authorization_version, template_version
from apps.permissions.models import Role, UserRole, PermissionChange
from apps.permissions.resource_policies import RESOURCE_DEFINITIONS
from apps.tenants.models import Tenant
from apps.integrations.models import FeishuConfigRule
from apps.reports.datasets import DATASETS, selected_permission

TENANT_ID = 1
ACTOR_ID = 1
SHARED_ROLE_ID = 36
USER_IDS = [59, 60]
ROLE_CODE = "phase1-feishu-report-view-v1"
WAREHOUSE_IDS = [2, 3, 4]
STORE_IDS = [6, 30, 31, 32, 33, 34, 35, 36, 37, 41, 42, 43, 47, 56, 58, 59, 60]
EXPECTED_ROLE36_VERSION = "cf5f373b6c70a3a82e4229aabd394cf6508511124ba199478f22090d48f08c1d"
EXPECTED_RULES_DIGEST = "f5f1711e3c9cd422bbfe49b040c3ca92db6d530c38e7492c8e004fcb7353b707"
EXPECTED_BINDINGS = {
    59: "f8b932e824c0b96c7ae4647f40b6acfe3bbb83b8fcb47a9c4a601c178ce00a26",
    60: "42bf06ad14ab4523831ba13305831ac430c15c8f0faf5a8bf50fc8e3c4221899",
}
BINDING_FIELDS = ("id", "user_id", "role_id", "source", "context_key", "membership_id", "status", "valid_until")
POLICIES = [
    {"resource_code": "reports.sales", "permission_code": "*", "scope_type": "custom", "config": {"store_ids": STORE_IDS}},
    {"resource_code": "reports.inventory", "permission_code": "*", "scope_type": "custom", "config": {"warehouse_ids": WAREHOUSE_IDS}},
]
# Root fills this from the independently reviewed candidate. Empty => no apply.
REVIEWED_SOURCE_HASHES = {'feishu_reports': '3973ddff05be6f0df8f94dcdc23008d5111cf05869136e443b424119bce06968', 'datasets': '79223fbed74ebf844dfbab33353ad3fcff536df52647b8f41a994e9cb36480a9', 'report_scopes': '67b69c48230b06a7ef7ca0c839d7a8f62d96fbe28e3c476753970b61c42a6517', 'resource_policies': '82d0094b6843fbf51fb54347df6aa0b4df60f83b4c9b6f3e20cb24f49e7a2682'}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def bindings(user_id, exclude_role_id=None):
    rows = UserRole.objects.filter(tenant_id=TENANT_ID, user_id=user_id)
    if exclude_role_id is not None:
        rows = rows.exclude(role_id=exclude_role_id)
    return list(rows.order_by("pk").values(*BINDING_FIELDS))


def rules_digest():
    return digest(list(FeishuConfigRule.objects.filter(tenant_id=TENANT_ID, kind="report").order_by("pk").values("id", "code", "enabled", "config")))


def call(view, method, path, payload, actor, **kwargs):
    request = getattr(APIRequestFactory(), method)(path, payload, format="json")
    force_authenticate(request, user=actor)
    response = view.as_view()(request, **kwargs)
    if not 200 <= response.status_code < 300:
        # Report safe error class/status only; no raw identities or credentials.
        raise RuntimeError(f"{view.__name__} refused ({response.status_code}); transaction rolled back")
    return response.data["data"]


def source_guard():
    from apps.integrations import feishu_reports
    from apps.reports import datasets, scopes
    from apps.permissions import resource_policies
    modules = {"feishu_reports": feishu_reports, "datasets": datasets, "report_scopes": scopes, "resource_policies": resource_policies}
    assert set(REVIEWED_SOURCE_HASHES) == set(modules), "Reviewed source hashes not installed"
    for key, module in modules.items():
        with open(inspect.getfile(module), "rb") as source:
            # Git may convert Windows line endings during checkout.
            assert hashlib.sha256(source.read().replace(b"\r\n", b"\n")).hexdigest() == REVIEWED_SOURCE_HASHES[key], "Deployed candidate differs from review"


def batch(actor, role_codes, reason):
    payload = {"operation": "transfer", "replace_source": "position", "user_ids": USER_IDS, "role_codes": role_codes, "reason": reason}
    preview = call(AuthorizationBatchPreviewView, "post", "/api/internal/system/authorization/batches/preview/", payload, actor)
    return call(AuthorizationBatchApplyView, "post", "/api/internal/system/authorization/batches/apply/", {"preview_token": preview["preview_token"]}, actor)


def inspect_plan():
    rows = [{"user_id": user.pk, "bindings_sha256": digest(bindings(user.pk)), "authorization_version": authorization_version(user),
        "position_tenant_binding_count": user.user_roles.filter(tenant_id=TENANT_ID, source="position", context_key="tenant").count()}
        for user in CustomUser.objects.filter(tenant_id=TENANT_ID, pk__in=USER_IDS).order_by("pk")]
    return {"status": "dry_run", "production_writes": 0, "external_provider_calls": 0, "targets": rows,
        "report_resources_registered": all(code in RESOURCE_DEFINITIONS for code in ("reports.sales", "reports.inventory")),
        "role36_template_version": template_version(Role.objects.get(tenant_id=TENANT_ID, pk=SHARED_ROLE_ID)), "report_rules_sha256": rules_digest(),
        "dedicated_role_exists": Role.objects.filter(tenant_id=TENANT_ID, code=ROLE_CODE).exists(), "proposed_policies": POLICIES}


@transaction.atomic
def configure(mode, receipt=None):
    assert globals().get("FEISHU_SCOPE_APPROVED") is True, "This batch has not been approved"
    source_guard()
    Tenant.objects.select_for_update().get(pk=TENANT_ID)
    actor = CustomUser.objects.get(pk=ACTOR_ID, tenant_id=TENANT_ID, user_type="internal", is_active=True)
    users = list(CustomUser.objects.select_for_update().filter(tenant_id=TENANT_ID, pk__in=USER_IDS, user_type="internal", is_active=True).order_by("pk"))
    assert len(users) == 2
    shared = Role.objects.select_for_update().get(tenant_id=TENANT_ID, pk=SHARED_ROLE_ID)
    list(UserRole.objects.select_for_update().filter(tenant_id=TENANT_ID, user_id__in=USER_IDS).order_by("pk"))
    list(FeishuConfigRule.objects.select_for_update().filter(tenant_id=TENANT_ID, kind="report").order_by("pk"))
    assert template_version(shared) == EXPECTED_ROLE36_VERSION, "Shared role changed; re-review required"
    assert rules_digest() == EXPECTED_RULES_DIGEST, "Report rules changed; re-review required"

    if mode == "apply":
        assert not Role.objects.filter(tenant_id=TENANT_ID, code=ROLE_CODE).exists(), "Dedicated role already exists; inspect instead"
        for user in users:
            assert digest(bindings(user.pk)) == EXPECTED_BINDINGS[user.pk], "Original binding changed; re-review required"
            assert not user.user_roles.filter(tenant_id=TENANT_ID, source="position", context_key="tenant").exists(), "Position tenant scope is not empty"
        created = call(RoleCollectionView, "post", "/api/internal/system/roles/", {
            "name": "首期飞书日报查看", "code": ROLE_CODE, "status": "active", "description": "仅兰鑫、詹志强的首期日报范围，实际查询仍与业务权限取交集。"}, actor)
        role_id = created["id"]
        call(RolePermissionView, "put", f"/api/internal/system/roles/{role_id}/permissions/", {
            "action_permission_codes": ["reports.view"], "menu_permission_codes": [], "field_permission_codes": [],
            "scope_type": "custom", "scope_config": {"warehouse_ids": WAREHOUSE_IDS}}, actor, pk=role_id)
        role = Role.objects.get(pk=role_id, tenant_id=TENANT_ID)
        call(RoleResourcePolicyView, "put", f"/api/internal/system/roles/{role_id}/resource-policies/", {
            "expected_version": template_version(role), "policies": POLICIES}, actor, pk=role_id)
        assert set(role.permissions.values_list("code", flat=True)) == {"reports.view"}
        assert not role.user_roles.exists()
        applied = batch(actor, [ROLE_CODE], "首期飞书日报范围修正：仅59/60，三仓及既有17店范围")
        for user in users:
            assert digest(bindings(user.pk, role_id)) == EXPECTED_BINDINGS[user.pk], "Existing bindings changed"
            assert user.user_roles.filter(tenant_id=TENANT_ID, role_id=role_id, source="position", context_key="tenant", status="active").count() == 1
            # Capability/scope gate only, no heavy business query and no delivery.
            fresh = CustomUser.objects.get(pk=user.pk)
            for dataset in ("sales", "sales_skus", "refunds", "inventory"):
                selected_permission(fresh, DATASETS[dataset])
            for dataset in ("finance", "inventory_value"):
                try:
                    selected_permission(fresh, DATASETS[dataset])
                except PermissionDenied:
                    pass
                else:
                    raise AssertionError("Finance scope unexpectedly became available")
        assert set(role.user_roles.values_list("user_id", flat=True)) == set(USER_IDS)
        assert rules_digest() == EXPECTED_RULES_DIGEST and template_version(shared) == EXPECTED_ROLE36_VERSION
        return {"status": "applied", "role_id": role_id, "role_code": ROLE_CODE, "user_ids": USER_IDS, "batch_id": applied["batch_id"],
            "batch_changes_sha256": digest(applied["changes"]),
            "role_template_version": template_version(Role.objects.get(pk=role_id)), "original_bindings_sha256": EXPECTED_BINDINGS,
            "new_bindings_sha256": {user.pk: digest(bindings(user.pk)) for user in users}, "report_rules_sha256": EXPECTED_RULES_DIGEST, "external_provider_calls": 0}

    assert mode == "rollback" and receipt and receipt.get("status") == "applied", "Exact apply receipt required"
    assert receipt.get("role_code") == ROLE_CODE and receipt.get("user_ids") == USER_IDS
    assert {int(key): value for key, value in receipt.get("original_bindings_sha256", {}).items()} == EXPECTED_BINDINGS
    assert receipt.get("report_rules_sha256") == EXPECTED_RULES_DIGEST
    audit = PermissionChange.objects.select_for_update().get(tenant_id=TENANT_ID, actor_id=ACTOR_ID,
        batch_id=receipt["batch_id"], operation="transfer")
    assert digest(audit.changes) == receipt.get("batch_changes_sha256"), "Apply audit differs from receipt"
    assert sorted(change["user_id"] for change in audit.changes) == USER_IDS
    for change in audit.changes:
        before_roles, after_roles = set(change["before_roles"]), set(change["after_roles"])
        assert before_roles == {shared.code} and after_roles == {shared.code, ROLE_CODE}, "Audit is not this role addition"
        assert not change["removed"], "Apply audit removed an existing capability"
    role = Role.objects.select_for_update().get(tenant_id=TENANT_ID, pk=receipt["role_id"], code=ROLE_CODE)
    assert template_version(role) == receipt["role_template_version"], "Dedicated role changed; inspect before rollback"
    assert set(role.user_roles.values_list("user_id", flat=True)) == set(USER_IDS)
    for user in users:
        expected_new = receipt["new_bindings_sha256"].get(str(user.pk), receipt["new_bindings_sha256"].get(user.pk))
        assert digest(bindings(user.pk)) == expected_new, "Binding changed; stop rollback"
        assert digest(bindings(user.pk, role.pk)) == EXPECTED_BINDINGS[user.pk]
        positions = list(user.user_roles.filter(tenant_id=TENANT_ID, source="position", context_key="tenant").values_list("role_id", flat=True))
        assert positions == [role.pk], "Additional position binding; stop rollback"
    rolled_back = batch(actor, [], "回退首期飞书日报专用角色，仅移除本批次position租户级绑定")
    assert not role.user_roles.exists()
    call(RoleStatusView, "post", f"/api/internal/system/roles/{role.pk}/status/", {"status": "inactive"}, actor, pk=role.pk)
    for user in users:
        assert digest(bindings(user.pk)) == EXPECTED_BINDINGS[user.pk]
    assert rules_digest() == EXPECTED_RULES_DIGEST and template_version(shared) == EXPECTED_ROLE36_VERSION
    return {"status": "rolled_back", "role_id": role.pk, "batch_id": rolled_back["batch_id"], "external_provider_calls": 0}


def readonly(execute, sql, params, many, context):
    assert sql.lstrip().lstrip("(").lstrip().split(None, 1)[0].upper() in {"SELECT", "SHOW", "SET"}
    return execute(sql, params, many, context)


mode = globals().get("FEISHU_SCOPE_MODE", "dry_run")
if mode == "dry_run":
    with connection.execute_wrapper(readonly):
        result = inspect_plan()
else:
    result = configure(mode, globals().get("FEISHU_SCOPE_APPLY_RECEIPT"))
print("RESULT_JSON=" + json.dumps(result, default=str, ensure_ascii=True, separators=(",", ":")))
