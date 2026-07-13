from django.db import migrations


PERMISSIONS = (
    ("reports.view", "View report catalog and exports", "reports", "view", "View tenant and data-scope filtered report metadata."),
    ("reports.export", "Request report exports", "reports", "export", "Create audited placeholder report export requests."),
)


def seed_permissions(apps, schema_editor):
    permission_model = apps.get_model("permissions", "Permission")
    for code, name, module, action, description in PERMISSIONS:
        permission_model.objects.update_or_create(
            code=code,
            defaults={"name": name, "module": module, "action": action, "description": description},
        )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0007_seed_config_permissions")]
    operations = [migrations.RunPython(seed_permissions, migrations.RunPython.noop)]
