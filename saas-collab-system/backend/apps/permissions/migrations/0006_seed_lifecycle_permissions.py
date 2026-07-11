from django.db import migrations


PERMISSIONS = (
    ("products.lifecycle.view", "View product lifecycle reviews", "products", "lifecycle.view", "View tenant and data-scope filtered lifecycle reviews and decisions."),
    ("products.lifecycle.evaluate", "Evaluate product lifecycle", "products", "lifecycle.evaluate", "Generate mock product lifecycle recommendations."),
    ("products.lifecycle.confirm", "Confirm product lifecycle reviews", "products", "lifecycle.confirm", "Confirm or reject standard lifecycle recommendations."),
    ("products.lifecycle.high_risk_confirm", "Confirm high-risk lifecycle reviews", "products", "lifecycle.high_risk_confirm", "Confirm clearance, stopped, or archived lifecycle recommendations."),
)


def seed_permissions(apps, schema_editor):
    permission_model = apps.get_model("permissions", "Permission")
    for code, name, module, action, description in PERMISSIONS:
        permission_model.objects.update_or_create(
            code=code,
            defaults={"name": name, "module": module, "action": action, "description": description},
        )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0005_seed_replenishment_permissions")]
    operations = [migrations.RunPython(seed_permissions, migrations.RunPython.noop)]
