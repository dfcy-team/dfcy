"""Exercise audited configuration and rollback against an isolated database."""
from pathlib import Path
from uuid import uuid4

import pytest

from apps.permissions.models import DataScope, Permission, PermissionChange, Role, RoleResourcePolicy, UserRole
from tests.test_sales_management import create_scope, grant, user_for

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def plan():
    tenant, _, store, warehouse = create_scope("report-configuration")
    actor = user_for(tenant, "report-configuration-actor")
    for code in ("system.roles.manage", "system.roles.view", "system.users.manage", "system.users.view", "reports.view"):
        grant(actor, code)
    users = [user_for(tenant, f"report-configuration-user-{index}") for index in (1, 2)]
    shared = Role.objects.create(tenant=tenant, name="Original operations", code="original-operations")
    codes = ("reports.view", "sales_management.view", "analytics.view")
    for code in codes:
        permission, _ = Permission.objects.get_or_create(code=code, defaults={"name": code, "module": "reports", "action": "view"})
        shared.permissions.add(permission)
    DataScope.objects.create(tenant=tenant, role=shared, scope_type="custom", config={"platform_ids": [store.platform_id], "warehouse_ids": [warehouse.pk]})
    for resource, config in (("sales_management.sales", {"store_ids": [store.pk]}), ("commerce.inventory", {"all": True})):
        RoleResourcePolicy.objects.create(tenant=tenant, role=shared, resource_code=resource, permission_code="*", scope_type="all" if resource == "commerce.inventory" else "custom", config=config)
    for user in users:
        UserRole.objects.create(tenant=tenant, user=user, role=shared)
    source = (Path(__file__).resolve().parents[1] / "scripts/configure_phase1_feishu_report_scope.py").read_text(encoding="utf-8")
    # Import helpers without running the command's default read-only main block.
    namespace = {}
    exec(compile(source.split('\nmode = globals().get("FEISHU_SCOPE_MODE"', 1)[0], "configuration-candidate", "exec"), namespace)
    namespace.update(TENANT_ID=tenant.pk, ACTOR_ID=actor.pk, SHARED_ROLE_ID=shared.pk, USER_IDS=[user.pk for user in users],
        STORE_IDS=[store.pk], WAREHOUSE_IDS=[warehouse.pk], FEISHU_SCOPE_APPROVED=True)
    namespace["POLICIES"] = [
        {"resource_code": "reports.sales", "permission_code": "*", "scope_type": "custom", "config": {"store_ids": [store.pk]}},
        {"resource_code": "reports.inventory", "permission_code": "*", "scope_type": "custom", "config": {"warehouse_ids": [warehouse.pk]}},
    ]
    namespace["EXPECTED_ROLE36_VERSION"] = namespace["template_version"](shared)
    namespace["EXPECTED_RULES_DIGEST"] = namespace["rules_digest"]()
    namespace["EXPECTED_BINDINGS"] = {user.pk: namespace["digest"](namespace["bindings"](user.pk)) for user in users}
    # Deployment source hashing is exercised by the architect before production;
    # these database tests focus on actual API transactions and binding ownership.
    namespace["source_guard"] = lambda: None
    return namespace


def test_configuration_apply_and_rollback_preserve_original_bindings(plan):
    receipt = plan["configure"]("apply")
    assert receipt["status"] == "applied"
    assert PermissionChange.objects.filter(batch_id=receipt["batch_id"]).exists()
    for user_id in plan["USER_IDS"]:
        assert plan["digest"](plan["bindings"](user_id, receipt["role_id"])) == plan["EXPECTED_BINDINGS"][user_id]
    rolled_back = plan["configure"]("rollback", receipt)
    assert rolled_back["status"] == "rolled_back"
    assert Role.objects.get(pk=receipt["role_id"]).status == "inactive"
    for user_id in plan["USER_IDS"]:
        assert plan["digest"](plan["bindings"](user_id)) == plan["EXPECTED_BINDINGS"][user_id]


@pytest.mark.parametrize("tamper", ["missing_batch", "changed_audit_digest"])
def test_rollback_rejects_invalid_receipt_without_removing_bindings(plan, tamper):
    receipt = plan["configure"]("apply")
    original = {user_id: plan["bindings"](user_id) for user_id in plan["USER_IDS"]}
    if tamper == "missing_batch":
        receipt["batch_id"] = str(uuid4())
    else:
        receipt["batch_changes_sha256"] = "invalid"
    with pytest.raises((PermissionChange.DoesNotExist, AssertionError)):
        plan["configure"]("rollback", receipt)
    assert {user_id: plan["bindings"](user_id) for user_id in plan["USER_IDS"]} == original
    assert Role.objects.get(pk=receipt["role_id"]).status == "active"


def test_failed_post_binding_gate_rolls_back_entire_configuration(plan):
    def rejected_gate(*args):
        raise RuntimeError("simulated failed acceptance")
    plan["selected_permission"] = rejected_gate
    with pytest.raises(RuntimeError, match="simulated failed acceptance"):
        plan["configure"]("apply")
    assert not Role.objects.filter(tenant_id=plan["TENANT_ID"], code=plan["ROLE_CODE"]).exists()
    assert not PermissionChange.objects.filter(tenant_id=plan["TENANT_ID"]).exists()
    for user_id in plan["USER_IDS"]:
        assert plan["digest"](plan["bindings"](user_id)) == plan["EXPECTED_BINDINGS"][user_id]


def test_configuration_stops_if_target_binding_changed(plan):
    binding = UserRole.objects.get(tenant_id=plan["TENANT_ID"], user_id=plan["USER_IDS"][0])
    binding.status = "inactive"
    binding.save(update_fields=["status"])
    with pytest.raises(AssertionError, match="Original binding changed"):
        plan["configure"]("apply")
    assert not Role.objects.filter(tenant_id=plan["TENANT_ID"], code=plan["ROLE_CODE"]).exists()
