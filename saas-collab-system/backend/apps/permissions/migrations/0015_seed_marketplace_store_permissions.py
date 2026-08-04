from django.db import migrations


PERMISSIONS = (
    (
        "integrations.store.view",
        "View marketplace store authorizations",
        "store.view",
        "View tenant and store scoped Shopee or TikTok Shop authorization metadata.",
    ),
    (
        "integrations.store.authorize",
        "Authorize marketplace stores",
        "store.authorize",
        "Create a marketplace store authorization using custody references.",
    ),
    (
        "integrations.store.revoke",
        "Revoke marketplace store authorizations",
        "store.revoke",
        "Revoke one authorized marketplace store and append an audit record.",
    ),
    (
        "integrations.store.sync",
        "Synchronize marketplace stores",
        "store.sync",
        "Request an approved marketplace store synchronization action.",
    ),
    (
        "integrations.store.retry",
        "Retry marketplace store operations",
        "store.retry",
        "Retry one failed marketplace store operation.",
    ),
    (
        "integrations.credential.rotate",
        "Rotate marketplace credential references",
        "credential.rotate",
        "Atomically rotate custody references without receiving platform credentials.",
    ),
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
    dependencies = [("permissions", "0014_seed_ui_p8_permissions")]
    operations = [migrations.RunPython(seed_permissions, migrations.RunPython.noop)]
