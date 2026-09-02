from django.db import migrations


PERMISSIONS = (
    ("integrations.store.view", "View marketplace store authorizations", "store.view", "View tenant-scoped store authorization metadata."),
    ("integrations.store.authorize", "Authorize marketplace stores", "store.authorize", "Create a controlled marketplace store authorization."),
    ("integrations.store.revoke", "Revoke marketplace store authorizations", "store.revoke", "Revoke a store authorization with an audit record."),
    ("integrations.store.sync", "Synchronize marketplace stores", "store.sync", "Request an approved store synchronization action."),
    ("integrations.store.retry", "Retry marketplace store operations", "store.retry", "Retry a failed marketplace store operation."),
    ("integrations.credential.rotate", "Rotate marketplace credential references", "credential.rotate", "Rotate custody references without receiving platform secrets."),
    ("integrations.config.view", "View API platform configurations", "config.view", "View tenant-scoped API platform configuration metadata."),
    ("integrations.config.create", "Create API platform configurations", "config.create", "Create a tenant-scoped platform configuration."),
    ("integrations.config.update", "Update API platform configurations", "config.update", "Update non-secret platform configuration fields."),
    ("integrations.config.verify", "Verify API platform configurations", "config.verify", "Verify an approved platform connection."),
    ("integrations.config.disable", "Disable API platform configurations", "config.disable", "Disable a tenant-scoped platform configuration."),
    ("integrations.credential.clear", "Clear API platform credentials", "credential.clear", "Revoke and clear custody references after confirmation."),
    ("integrations.audit.view", "View integration audit logs", "audit.view", "View redacted tenant-scoped integration audit records."),
)


def seed_permissions(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    for code, name, action, description in PERMISSIONS:
        Permission.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "module": "integrations",
                "action": action,
                "description": description,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0030_seed_sales_management_permissions")]
    operations = [migrations.RunPython(seed_permissions, migrations.RunPython.noop)]
