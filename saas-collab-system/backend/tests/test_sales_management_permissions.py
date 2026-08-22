import pytest
from django.core.management import call_command

from apps.permissions.catalog import PERMISSION_DEFINITIONS, permission_defaults
from apps.permissions.models import Permission, Role
from apps.tenants.models import Tenant


SALES_CODES = {
    "sales_management.view",
    "sales_management.orders.view",
    "sales_management.returns.view",
    "sales_management.stores.view",
    "sales_management.skus.view",
    "sales_management.export",
    "sales_management.data_quality.view",
    "sales_management.sync.view",
}


@pytest.mark.django_db
def test_sales_management_permission_catalog_metadata_is_complete():
    definitions = {item["code"]: item for item in PERMISSION_DEFINITIONS}
    assert set(definitions) >= SALES_CODES
    for code in SALES_CODES:
        permission = Permission.objects.get(code=code)
        for field, expected in permission_defaults(definitions[code]).items():
            assert getattr(permission, field) == expected


@pytest.mark.django_db
def test_permission_sync_grants_new_sales_permissions_only_to_administrator():
    tenant = Tenant.objects.create(name="Sales permissions tenant", code="sales-permission-contract")
    administrator = Role.objects.create(tenant=tenant, code="administrator", name="管理员", status="active")
    viewer = Role.objects.create(tenant=tenant, code="sales_viewer", name="销售查看", status="active")
    administrator.permissions.clear()
    viewer.permissions.clear()

    call_command("sync_permissions")

    assert SALES_CODES <= set(administrator.permissions.values_list("code", flat=True))
    assert not SALES_CODES & set(viewer.permissions.values_list("code", flat=True))
