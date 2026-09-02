from django.db import migrations


PERMISSION_CODES = (
    "sales_management.view",
    "sales_management.orders.view",
    "sales_management.returns.view",
    "sales_management.stores.view",
    "sales_management.skus.view",
    "sales_management.export",
    "sales_management.data_quality.view",
    "sales_management.sync.view",
)


def seed_sales_management_permissions(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Role = apps.get_model("permissions", "Role")
    from apps.permissions.catalog import PERMISSION_DEFINITIONS, permission_defaults

    definitions = {
        definition["code"]: definition
        for definition in PERMISSION_DEFINITIONS
        if definition["code"] in PERMISSION_CODES
    }
    permissions = []
    for code in PERMISSION_CODES:
        definition = definitions.get(code)
        if definition is None:
            continue
        permission, _ = Permission.objects.update_or_create(
            code=code,
            defaults=permission_defaults(definition),
        )
        permissions.append(permission)

    # Only the built-in administrator role receives new catalog capabilities.
    # Other roles must be explicitly granted them by an authorized operator.
    for role in Role.objects.filter(code="administrator", status="active"):
        role.permissions.add(*permissions)


class Migration(migrations.Migration):
    dependencies = [("permissions", "0029_sync_development_product_archive_permission_metadata")]

    operations = [
        migrations.RunPython(seed_sales_management_permissions, migrations.RunPython.noop),
    ]
