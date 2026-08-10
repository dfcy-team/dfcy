from django.db import migrations


PERMISSIONS = (
    ("supply.packing.view", "View packing batches", "view"),
    ("supply.packing.create", "Create packing batches", "create"),
    ("supply.packing.manage", "Manage packing boxes", "manage"),
    ("supply.packing.complete", "Complete packing batches", "complete"),
    ("supply.packing.change.review", "Review packing changes", "review"),
)


def seed_permissions(apps, schema_editor):
    permission = apps.get_model("permissions", "Permission")
    for code, name, action in PERMISSIONS:
        permission.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "module": "supply",
                "action": action,
                "description": "SC-F2 frozen packing permission.",
            },
        )


def remove_permissions(apps, schema_editor):
    permission = apps.get_model("permissions", "Permission")
    permission.objects.filter(code__in=[item[0] for item in PERMISSIONS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("permissions", "0017_merge_release_and_supply_permissions"),
    ]

    operations = [
        migrations.RunPython(seed_permissions, remove_permissions),
    ]
