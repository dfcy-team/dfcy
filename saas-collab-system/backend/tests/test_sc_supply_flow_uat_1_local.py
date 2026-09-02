import json

import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from apps.masterdata.models import SupplierMaster
from apps.packing.models import PackingStandardVersion, _packing_domain_write_context
from apps.permissions.models import Permission
from apps.purchasing.uat_data import (
    ALL_CONSOLIDATION_PERMISSIONS,
    ALL_PACKING_PERMISSIONS,
    ALL_PURCHASE_PERMISSIONS,
    ALL_SHIPMENT_PERMISSIONS,
    DATA_VERSION,
)
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db(transaction=True)


PERMISSION_CODES = (
    *ALL_PURCHASE_PERMISSIONS,
    *ALL_PACKING_PERMISSIONS,
    *ALL_CONSOLIDATION_PERMISSIONS,
    *ALL_SHIPMENT_PERMISSIONS,
)


def _command(action, **kwargs):
    options = {
        "environment": "local",
        "database_name": str(connection.settings_dict["NAME"]),
        "data_version": DATA_VERSION,
        "payload": "fixture-v1",
        "confirm_local": True,
        "allow_inmemory_test": True,
        "as_json": True,
    }
    options.update(kwargs)
    return call_command("seed_supply_flow_uat", action, **options)


@pytest.fixture(autouse=True)
def seed_local_dependencies():
    for code in PERMISSION_CODES:
        Permission.objects.get_or_create(
            code=code,
            defaults={"name": code, "module": "sc-uat", "action": code.rsplit(".", 1)[-1]},
        )
    with _packing_domain_write_context():
        PackingStandardVersion.objects.get_or_create(
            code="packing-v1",
            version=1,
            defaults={"title": "UAT standard", "rules": {"exact_completion_required": True}, "is_active": True},
        )


def test_wrong_environment_is_fail_closed_without_creating_tenants(capsys):
    with pytest.raises(CommandError, match="environment local"):
        _command("generate", environment="production")
    assert not Tenant.objects.filter(code="SC-UAT-A").exists()


def test_production_settings_marker_is_rejected_even_when_debug_is_true(monkeypatch):
    # DEBUG is not an environment boundary: a production settings module must
    # remain fail-closed even if a local test mutates DEBUG to True.
    monkeypatch.setattr(settings, "SETTINGS_MODULE", "config.settings.prod", raising=False)
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings.prod")
    monkeypatch.setattr(settings, "DEBUG", True, raising=False)
    with pytest.raises(CommandError, match="non-local settings module"):
        _command("generate")
    assert not Tenant.objects.filter(code="SC-UAT-A").exists()


@pytest.mark.parametrize(
    "remote_name",
    (
        r"\\\\server\\share\\SC-UAT.sqlite3",
        "//server/share/SC-UAT.sqlite3",
        "file://server/share/SC-UAT.sqlite3",
    ),
)
def test_network_sqlite_path_is_rejected_without_writes(monkeypatch, remote_name):
    # Simulate a loaded SQLite connection whose configured NAME points to a
    # UNC/network URI.  The command must stop before any tenant is created.
    monkeypatch.setitem(connection.settings_dict, "NAME", remote_name)
    with pytest.raises(CommandError, match="SQLite database path"):
        _command("generate")
    assert not Tenant.objects.filter(code="SC-UAT-A").exists()


def test_generate_is_idempotent_and_check_catches_tampering():
    _command("generate")
    _command("generate")
    _command("check")
    supplier = SupplierMaster.objects.get(tenant__code="SC-UAT-A", code="SC-UAT-SUP-A")
    original = supplier.name
    supplier.name = "tampered"
    supplier.save(update_fields=["name", "updated_at"])
    with pytest.raises(CommandError, match="Supplier"):
        _command("check")
    supplier.name = original
    supplier.save(update_fields=["name", "updated_at"])


def test_same_version_different_payload_conflicts_and_scope_matrix_is_present():
    _command("generate")
    with pytest.raises(CommandError, match="version/payload marker"):
        _command("generate", payload="different-fixture")
    tenant_a = Tenant.objects.get(code="SC-UAT-A")
    tenant_b = Tenant.objects.get(code="SC-UAT-B")
    assert tenant_a.status == Tenant.Status.ACTIVE
    assert tenant_b.status == Tenant.Status.ACTIVE
    assert SupplierMaster.objects.filter(tenant=tenant_a, code__startswith="SC-UAT-").count() == 3
    assert SupplierMaster.objects.filter(tenant=tenant_b, code="SC-UAT-SUP-X").count() == 1


def test_cleanup_deactivates_only_named_uat_tenant_and_retains_audit_graph():
    _command("generate")
    unrelated = Tenant.objects.create(code="non-uat-tenant", name="Non-UAT tenant")
    _command("cleanup", tenant_codes=["SC-UAT-A"])
    assert Tenant.objects.get(code="SC-UAT-A").status == Tenant.Status.INACTIVE
    assert Tenant.objects.get(code="SC-UAT-B").status == Tenant.Status.ACTIVE
    assert Tenant.objects.get(pk=unrelated.pk).status == Tenant.Status.ACTIVE
    with pytest.raises(CommandError, match="inactive"):
        _command("generate")
