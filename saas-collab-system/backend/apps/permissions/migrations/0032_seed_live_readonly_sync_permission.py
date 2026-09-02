from django.db import migrations


def seed_permission(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Permission.objects.update_or_create(
        code="integrations.run_live_readonly",
        defaults={
            "name": "Run live readonly synchronization",
            "module": "integrations",
            "action": "run_live_readonly",
            "description": "Queue an approved production readonly synchronization job.",
        },
    )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0031_seed_integration_custody_permissions")]
    operations = [migrations.RunPython(seed_permission, migrations.RunPython.noop)]
