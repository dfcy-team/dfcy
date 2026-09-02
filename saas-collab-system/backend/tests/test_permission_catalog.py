import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.permissions.catalog import PERMISSION_DEFINITIONS, permission_defaults
from apps.permissions.models import Permission


@pytest.mark.django_db
def test_permission_catalog_is_seeded_with_current_metadata():
    for definition in PERMISSION_DEFINITIONS:
        permission = Permission.objects.get(code=definition["code"])
        for field, expected in permission_defaults(definition).items():
            assert getattr(permission, field) == expected

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
