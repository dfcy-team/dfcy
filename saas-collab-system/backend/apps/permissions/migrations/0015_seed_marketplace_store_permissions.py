from django.db import migrations


PERMISSIONS = (
    (
        "integrations.store.view",
        "View marketplace store authorizations",
        "store.view",
        "View scoped Shopee and TikTok Shop authorization metadata.",
    ),
    (
        "integrations.store.authorize",
        "Authorize marketplace stores",
        "store.authorize",
        "Create or refresh scoped marketplace store authorizations; real actions remain pending.",
    ),
    (
        "integrations.store.revoke",
        "Revoke marketplace store authorizations",
        "store.revoke",
        "Revoke scoped marketplace store authorizations; real actions remain pending.",
    ),
    (
        "integrations.store.sync",
        "Sync marketplace stores",
        "store.sync",
        "Request scoped marketplace store synchronization; real actions remain pending.",
    ),
    (
        "integrations.store.retry",
        "Retry marketplace store operations",
        "store.retry",
        "Retry scoped marketplace operations; real actions remain pending.",
    ),
    (
        "integrations.credential.rotate",
        "Rotate marketplace credential references",
        "credential.rotate",
        "Rotate external credential references without storing credential material.",
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
