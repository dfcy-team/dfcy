from django.db import migrations


PERMISSIONS = (
    ("config.view", "View configuration", "config", "view", "View authorized tenant configuration metadata and masked values."),
    ("config.manage", "Manage tenant configuration", "config", "manage", "Create versioned tenant configuration values."),
    ("config.approve", "Approve configuration", "config", "approve", "Approve configuration versions with creator/approver separation."),
    ("config.rollback", "Rollback configuration", "config", "rollback", "Create a new configuration version from authorized history."),
    ("config.system.manage", "Manage system configuration", "config", "system.manage", "Access restricted system-scope configuration versions."),
)


def seed_permissions(apps, schema_editor):
    permission_model = apps.get_model("permissions", "Permission")
    for code, name, module, action, description in PERMISSIONS:
        permission_model.objects.update_or_create(
            code=code,
            defaults={"name": name, "module": module, "action": action, "description": description},
        )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0006_seed_lifecycle_permissions")]
    operations = [migrations.RunPython(seed_permissions, migrations.RunPython.noop)]
