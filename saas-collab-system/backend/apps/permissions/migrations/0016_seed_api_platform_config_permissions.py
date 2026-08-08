from django.db import migrations


PERMISSIONS = (
    ("integrations.config.view", "View API platform configurations", "config.view", "View tenant-scoped API platform configuration metadata."),
    ("integrations.config.create", "Create API platform configurations", "config.create", "Create a tenant-scoped Shopee or TikTok Shop configuration."),
    ("integrations.config.update", "Update API platform configurations", "config.update", "Update non-secret API platform configuration fields."),
    ("integrations.config.verify", "Verify API platform configurations", "config.verify", "Run an approved connection verification without enabling synchronization."),
    ("integrations.config.disable", "Disable API platform configurations", "config.disable", "Disable one tenant-scoped API platform configuration."),
    ("integrations.credential.clear", "Clear API platform credentials", "credential.clear", "Revoke and clear custody references after explicit confirmation."),
    ("integrations.audit.view", "View integration audit logs", "audit.view", "View redacted tenant-scoped integration audit records."),
)


def seed_permissions(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    for code, name, action, description in PERMISSIONS:
        Permission.objects.update_or_create(
            code=code,
            defaults={"name": name, "module": "integrations", "action": action, "description": description},
        )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0015_seed_marketplace_store_permissions")]
    operations = [migrations.RunPython(seed_permissions, migrations.RunPython.noop)]
