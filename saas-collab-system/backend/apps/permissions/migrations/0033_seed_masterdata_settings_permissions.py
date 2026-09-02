from django.db import migrations


PERMISSION_CODES = (
    "masterdata.settings.view",
    "masterdata.settings.manage",
)


def seed_masterdata_settings_permissions(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Role = apps.get_model("permissions", "Role")
    from apps.permissions.catalog import PERMISSION_DEFINITIONS, permission_defaults

    definitions = {
        item["code"]: item
        for item in PERMISSION_DEFINITIONS
        if item["code"] in PERMISSION_CODES
    }
    permissions = []
    for code in PERMISSION_CODES:
        permission, _ = Permission.objects.update_or_create(
            code=code,
            defaults=permission_defaults(definitions[code]),
        )
        permissions.append(permission)
    for role in Role.objects.filter(code="administrator", status="active"):
        role.permissions.add(*permissions)


class Migration(migrations.Migration):
    dependencies = [
        ("permissions", "0032_seed_live_readonly_sync_permission"),
    ]

    operations = [
        migrations.RunPython(seed_masterdata_settings_permissions, migrations.RunPython.noop),
    ]
