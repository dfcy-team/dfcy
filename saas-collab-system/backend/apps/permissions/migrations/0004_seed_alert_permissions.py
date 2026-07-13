from django.db import migrations


PERMISSIONS = (
    ("alerts.view", "View operational alerts", "alerts", "view", "View tenant and data-scope filtered operational alerts."),
    ("alerts.evaluate", "Evaluate operational alerts", "alerts", "evaluate", "Run mock tenant-scoped inventory alert evaluations."),
    ("alerts.manage", "Manage operational alerts", "alerts", "manage", "Assign, silence, handle, and close tenant-scoped operational alerts."),
)


def seed_permissions(apps, schema_editor):
    permission_model = apps.get_model("permissions", "Permission")
    for code, name, module, action, description in PERMISSIONS:
        permission_model.objects.update_or_create(
            code=code,
            defaults={"name": name, "module": module, "action": action, "description": description},
        )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0003_seed_analytics_permissions")]
    operations = [migrations.RunPython(seed_permissions, migrations.RunPython.noop)]
