import importlib

import pytest
from django.apps import apps as django_apps

from apps.permissions.catalog import PERMISSION_DEFINITIONS, permission_defaults
from apps.permissions.models import Permission, Role
from apps.tenants.models import Tenant


MIGRATION = importlib.import_module(
    "apps.permissions.migrations.0039_register_warehouse_connector_role_permissions"
)
WAREHOUSE_CONNECTOR_CODES = set(MIGRATION.PERMISSION_CODES)


@pytest.mark.django_db
def test_warehouse_connector_permission_catalog_has_explicit_boundaries():
    definitions = {item["code"]: item for item in PERMISSION_DEFINITIONS}

    assert WAREHOUSE_CONNECTOR_CODES == {
        "masterdata.view",
        "masterdata.manage",
        "integrations.config.view",
        "integrations.config.create",
        "integrations.config.update",
        "integrations.config.verify",
        "integrations.config.disable",
        "integrations.credential.rotate",
    }
    for code in WAREHOUSE_CONNECTOR_CODES:
        definition = definitions[code]
        permission = Permission.objects.get(code=code)
        assert permission_defaults(definition) == {
            field: getattr(permission, field)
            for field in permission_defaults(definition)
        }
        assert all("" < value for value in (definition["name"], definition["description"]))

    assert "不授予实际连接器配置或凭据轮换" in definitions["masterdata.manage"]["description"]
    assert "integrations.config.*" in definitions["masterdata.manage"]["description"]
    assert "credential.rotate" in definitions["masterdata.manage"]["description"]
    assert "不读取" in definitions["integrations.credential.rotate"]["description"]


@pytest.mark.django_db
def test_warehouse_connector_migration_updates_metadata_and_only_active_administrators():
    tenant = Tenant.objects.create(name="Connector permission tenant", code="connector-permission-tenant")
    inactive_tenant = Tenant.objects.create(name="Inactive permission tenant", code="inactive-permission-tenant")
    inactive_admin = Role.objects.create(
        tenant=inactive_tenant,
        name="停用管理员",
        code="administrator",
        status=Role.Status.INACTIVE,
    )
    active_admin = Role.objects.create(
        tenant=tenant,
        name="管理员",
        code="administrator",
        status=Role.Status.ACTIVE,
    )
    ordinary = Role.objects.create(
        tenant=tenant,
        name="仓储查看员",
        code="warehouse_viewer",
        status=Role.Status.ACTIVE,
    )
    legacy, _ = Permission.objects.get_or_create(
        code="warehouse.legacy.view",
        defaults={"name": "旧权限", "module": "warehouse", "action": "legacy.view"},
    )
    ordinary.permissions.add(legacy)

    Permission.objects.filter(code__in=WAREHOUSE_CONNECTOR_CODES).delete()
    MIGRATION.register_warehouse_connector_permissions(django_apps, None)

    active_codes = set(active_admin.permissions.values_list("code", flat=True))
    inactive_codes = set(inactive_admin.permissions.values_list("code", flat=True))
    ordinary_codes = set(ordinary.permissions.values_list("code", flat=True))

    assert WAREHOUSE_CONNECTOR_CODES <= active_codes
    assert not WAREHOUSE_CONNECTOR_CODES & inactive_codes
    assert ordinary_codes == {legacy.code}
    assert Permission.objects.filter(code__in=WAREHOUSE_CONNECTOR_CODES).count() == len(WAREHOUSE_CONNECTOR_CODES)
    assert MIGRATION.Migration.dependencies == [("permissions", "0038_split_permission_surfaces")]
    assert MIGRATION.Migration.operations[0].reverse_code is MIGRATION.migrations.RunPython.noop
