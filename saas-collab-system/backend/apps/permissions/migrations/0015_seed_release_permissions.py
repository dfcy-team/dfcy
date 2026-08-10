from django.db import migrations


PERMISSIONS = (
    (
        "release.contract.view",
        "View release contracts",
        "contract.view",
        "View tenant-scoped release contracts and masked evidence.",
    ),
    (
        "release.contract.manage",
        "Manage release contracts",
        "contract.manage",
        "Create contracts, record gates, submit review, and cancel eligible contracts.",
    ),
    (
        "release.contract.approve",
        "Approve release contracts",
        "contract.approve",
        "Record independent business, technical, security, or rollback decisions.",
    ),
    (
        "release.contract.execute",
        "Record release execution",
        "contract.execute",
        "Record build, upload, platform review, release, observation, and rollback results.",
    ),
)


def seed_permissions(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    for code, name, action, description in PERMISSIONS:
        Permission.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "module": "release",
                "action": action,
                "description": description,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0014_seed_ui_p8_permissions")]
    operations = [migrations.RunPython(seed_permissions, migrations.RunPython.noop)]
