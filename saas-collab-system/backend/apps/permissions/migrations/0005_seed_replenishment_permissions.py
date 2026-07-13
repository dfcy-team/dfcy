from django.db import migrations


PERMISSIONS = (
    ("replenishment.view", "View replenishment recommendations", "replenishment", "view", "View tenant and data-scope filtered replenishment recommendations."),
    ("replenishment.evaluate", "Evaluate replenishment recommendations", "replenishment", "evaluate", "Generate mock replenishment recommendations without creating purchase orders."),
    ("replenishment.review", "Review replenishment recommendations", "replenishment", "review", "Accept or reject recommendations without executing procurement."),
)


def seed_permissions(apps, schema_editor):
    permission_model = apps.get_model("permissions", "Permission")
    for code, name, module, action, description in PERMISSIONS:
        permission_model.objects.update_or_create(
            code=code,
            defaults={"name": name, "module": module, "action": action, "description": description},
        )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0004_seed_alert_permissions")]
    operations = [migrations.RunPython(seed_permissions, migrations.RunPython.noop)]
