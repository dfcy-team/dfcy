import io
import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.accounts.serializers import CurrentUserSerializer
from apps.permissions.lifecycle import effective_permissions
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.permissions.services import (
    check_user_permission, get_field_permission_map, get_permission_data_scopes,
    get_user_all_scope_permission_codes, get_user_permission_categories,
)
from apps.tenants.models import Tenant

pytestmark = pytest.mark.django_db


def actor_with_role(*permissions):
    tenant = Tenant.objects.create(name="Lifecycle", code="lifecycle")
    actor = CustomUser.objects.create_user(
        username="lifecycle-user", password=None, tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    role = Role.objects.create(tenant=tenant, name="Reader", code="reader")
    role.permissions.set(permissions)
    UserRole.objects.create(tenant=tenant, user=actor, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type="all", config={})
    return actor, role


@pytest.mark.parametrize("marker,status", [
    ("registry_status", "inactive"), ("registry_status", "retired"),
    ("status", "inactive"), ("status", "retired"),
])
def test_retired_menu_keeps_history_but_cannot_open_api_or_contribute_scope(marker, status):
    menu = Permission.objects.get(code="menu.system.users.view")
    menu.metadata = {marker: status, "action_codes": ["system.users.view", "system.users.manage"]}
    menu.save(update_fields=["metadata"])
    actor, role = actor_with_role(menu)
    client = APIClient()
    client.force_authenticate(actor)

    assert not check_user_permission(actor, "system.users.view")
    assert not check_user_permission(actor, "system.users.manage")
    assert get_permission_data_scopes(actor, "system.users.view") == []
    assert client.get("/api/internal/system/users/").status_code == 403
    snapshot = client.get("/api/internal/auth/me/").json()["data"]
    assert menu.code not in snapshot["menu_permission_codes"]
    assert "system.users.view" not in snapshot["action_permission_codes"]
    assert "system.users.view" not in snapshot["all_scope_permission_codes"]
    assert role.permissions.filter(pk=menu.pk).exists()


def test_navigation_hiding_does_not_revoke_read_or_allow_write():
    menu = Permission.objects.get(code="menu.system.users.view")
    menu.metadata = {"status": "active", "navigation_hidden": True,
                     "action_codes": ["system.users.view", "system.users.manage"]}
    menu.save(update_fields=["metadata"])
    actor, _ = actor_with_role(menu)
    assert check_user_permission(actor, "system.users.view")
    assert not check_user_permission(actor, "system.users.manage")
    assert get_permission_data_scopes(actor, "system.users.view")[0]["scope_type"] == "all"


def test_retired_menu_does_not_revoke_explicit_shared_action():
    menu = Permission.objects.get(code="menu.system.users.view")
    menu.metadata = {"registry_status": "inactive", "action_codes": ["system.users.view"]}
    menu.save(update_fields=["metadata"])
    actor, _ = actor_with_role(menu, Permission.objects.get(code="system.users.view"))
    assert check_user_permission(actor, "system.users.view")
    assert get_permission_data_scopes(actor, "system.users.view")
    assert "system.users.view" in CurrentUserSerializer(actor).data["action_permission_codes"]


def test_retired_action_cannot_be_revived_by_menu_superuser_or_legacy_role_fallback():
    action = Permission.objects.get(code="finance.view")
    action.metadata = {"registry_status": "retired"}
    action.save(update_fields=["metadata"])
    menu = Permission.objects.create(
        code="menu.test.finance.view", name="Finance", module="finance", action="view",
        permission_type="menu", metadata={"action_codes": ["finance.view"]},
    )
    actor, role = actor_with_role(menu, action)
    role.code = "finance"
    role.save(update_fields=["code"])
    from apps.permissions.services import user_has_finance_permission
    assert not check_user_permission(actor, action.code)
    assert not user_has_finance_permission(actor, action.code)
    assert get_permission_data_scopes(actor, action.code) == []
    assert action.code not in get_user_permission_categories(actor)["action"]
    assert action.code not in get_user_all_scope_permission_codes(actor)
    assert action.code not in CurrentUserSerializer(actor).data["action_permission_codes"]
    actor.is_superuser = True
    actor.save(update_fields=["is_superuser"])
    assert not check_user_permission(actor, action.code)
    assert get_permission_data_scopes(actor, action.code) == []
    assert action.code not in CurrentUserSerializer(actor).data["permissions"]


@pytest.mark.parametrize("metadata", [{}, {"status": "active"}, {"registry_status": None}])
def test_missing_or_null_json_status_does_not_hide_active_legacy_permissions(metadata):
    action = Permission.objects.get(code="system.users.view")
    action.metadata = metadata
    action.save(update_fields=["metadata"])
    actor, _ = actor_with_role(action)
    assert effective_permissions().filter(pk=action.pk).exists()
    assert check_user_permission(actor, action.code)


def test_retired_field_is_denied_even_when_legacy_default_or_superuser_allows_fields():
    field = Permission.objects.get(code="field.system.users.full_name.view")
    field.metadata = {"resource": "users", "status": "retired"}
    field.save(update_fields=["metadata"])
    actor, _ = actor_with_role(field)
    assert get_field_permission_map(actor, [field.code], default=True) == {field.code: False}
    actor.is_superuser = True
    assert get_field_permission_map(actor, [field.code], default=True) == {field.code: False}


def test_lifecycle_revocation_takes_effect_in_next_request():
    action = Permission.objects.get(code="system.users.view")
    actor, _ = actor_with_role(action)
    client = APIClient()
    client.force_authenticate(actor)
    assert client.get("/api/internal/system/users/").status_code == 200
    action.metadata = {"registry_status": "retired"}
    action.save(update_fields=["metadata"])
    assert client.get("/api/internal/system/users/").status_code == 403


def test_orphan_check_reports_bounded_samples_without_changing_permissions_or_grants():
    call_command("sync_permissions")
    orphan = Permission.objects.create(
        code="legacy.unregistered.action", name="Legacy", module="legacy", action="action",
    )
    actor, role = actor_with_role(orphan)
    output = io.StringIO()
    with pytest.raises(CommandError, match="orphan_permissions"):
        call_command("sync_permissions", "--check", "--strict-orphans", "--report-json", stdout=output)
    report = json.loads(next(line for line in output.getvalue().splitlines() if line.startswith("{")))
    assert report["read_only"] is True
    assert report["active_orphan_permission_count"] >= 1
    assert len(report["orphan_samples"]) <= 20
    orphan.refresh_from_db()
    assert orphan.metadata == {}
    assert role.permissions.filter(pk=orphan.pk).exists()
    assert check_user_permission(actor, orphan.code)


def test_reviewed_retired_orphan_is_audit_history_not_active_drift():
    call_command("sync_permissions")
    baseline_output = io.StringIO()
    call_command("sync_permissions", "--check", "--report-json", stdout=baseline_output)
    baseline = json.loads(next(line for line in baseline_output.getvalue().splitlines() if line.startswith("{")))
    orphan = Permission.objects.create(
        code="legacy.retired.field", name="Retired", module="legacy", action="view",
        permission_type="field", metadata={"registry_status": "retired"},
    )
    actor, role = actor_with_role(orphan)
    output = io.StringIO()
    call_command("sync_permissions", "--check", "--report-json", stdout=output)
    report = json.loads(next(line for line in output.getvalue().splitlines() if line.startswith("{")))
    assert report["active_orphan_permission_count"] == baseline["active_orphan_permission_count"]
    assert report["inactive_role_link_count"] >= 1
    assert report["potentially_affected_users"] == 1
    assert role.permissions.filter(pk=orphan.pk).exists()
    assert not get_field_permission_map(actor, [orphan.code], default=True)[orphan.code]
