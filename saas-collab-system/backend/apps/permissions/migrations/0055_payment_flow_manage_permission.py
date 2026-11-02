from django.db import migrations


def seed(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Permission.objects.update_or_create(
        code="workflow.approvals.manage",
        defaults={"name": "Manage approval flows", "module": "workflow", "action": "approvals.manage",
                  "description": "Create and publish immutable versioned payment approval rules."},
    )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0054_role_permissions_customized")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
