import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.permissions.catalog import PERMISSION_DEFINITIONS, permission_defaults
from apps.permissions.models import Permission, Role
from apps.permissions.role_catalog import sync_tenant_administrator_role
from apps.tenants.models import Tenant


def test_pilot_production_execution_permissions_are_distinct_catalog_entries():
    execution_codes = {
        "pilot.performance.execute",
        "pilot.recovery.execute",
        "pilot.release.execute",
        "pilot.release.rollback.execute",
    }
    catalog_codes = {definition["code"] for definition in PERMISSION_DEFINITIONS}

    assert execution_codes <= catalog_codes
    assert "pilot.performance.record" not in execution_codes
    assert "pilot.recovery.record" not in execution_codes
    assert "pilot.release.record" not in execution_codes


@pytest.mark.django_db
def test_permission_catalog_is_seeded_with_current_metadata():
    for definition in PERMISSION_DEFINITIONS:
        permission = Permission.objects.get(code=definition["code"])
        for field, expected in permission_defaults(definition).items():
            assert getattr(permission, field) == expected

    # Menu permissions are source-registered by the release sync command;
    # migrations intentionally do not execute mutable frontend JavaScript.
    call_command("sync_permissions")
    call_command("sync_permissions", "--check")


@pytest.mark.django_db
def test_sync_permissions_repairs_missing_and_stale_entries():
    missing_code = "integrations.run"
    stale_code = "products.status.confirm"
    Permission.objects.filter(code=missing_code).delete()
    Permission.objects.filter(code=stale_code).update(name="Stale permission name")

    with pytest.raises(CommandError):
        call_command("sync_permissions", "--check")

    call_command("sync_permissions")
    call_command("sync_permissions", "--check")

    assert Permission.objects.filter(code=missing_code).exists()
    expected = next(item for item in PERMISSION_DEFINITIONS if item["code"] == stale_code)
    assert Permission.objects.get(code=stale_code).name == expected["name"]


@pytest.mark.django_db
def test_catalog_sync_repairs_missing_administrator_fields_without_changing_other_roles():
    call_command("sync_permissions")
    tenant = Tenant.objects.create(name="Admin field sync", code="admin-field-sync")
    administrator = sync_tenant_administrator_role(tenant)
    fields = Permission.objects.filter(code__startswith="field.employee_readonly.")
    assert fields.exists()
    administrator.permissions.remove(*fields)
    ordinary = Role.objects.create(tenant=tenant, name="Field reader", code="field-reader")
    ordinary.permissions.add(fields.first())
    ordinary_codes = set(ordinary.permissions.values_list("code", flat=True))

    with pytest.raises(CommandError):
        call_command("sync_permissions", "--dry-run")
    assert not administrator.permissions.filter(code__startswith="field.employee_readonly.").exists()

    call_command("sync_permissions")
    assert set(fields.values_list("code", flat=True)) <= set(administrator.permissions.values_list("code", flat=True))
    before = set(administrator.permissions.values_list("code", flat=True))
    call_command("sync_permissions", "--check")
    call_command("sync_permissions")
    assert set(administrator.permissions.values_list("code", flat=True)) == before
    assert set(ordinary.permissions.values_list("code", flat=True)) == ordinary_codes
