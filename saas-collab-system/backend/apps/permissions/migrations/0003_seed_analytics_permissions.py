from django.db import migrations


PERMISSIONS = (
    (
        "analytics.view",
        "View analytics",
        "analytics",
        "view",
        "View tenant-scoped metric definitions and read-only BI aggregates.",
    ),
    (
        "analytics.calculate",
        "Calculate analytics",
        "analytics",
        "calculate",
        "Run tenant-scoped mock BI metric aggregation.",
    ),
    (
        "analytics.manage",
        "Manage analytics definitions",
        "analytics",
        "manage",
        "Create audited versions of tenant-scoped analytics metric definitions.",
    ),
)


def seed_analytics_permissions(apps, schema_editor):
    permission_model = apps.get_model("permissions", "Permission")
    for code, name, module, action, description in PERMISSIONS:
        permission_model.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "module": module,
                "action": action,
                "description": description,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0002_seed_action_permissions")]

    operations = [migrations.RunPython(seed_analytics_permissions, migrations.RunPython.noop)]
