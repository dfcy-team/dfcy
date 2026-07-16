from django.db import migrations


PERMISSIONS = (
    (
        "rpa.tasks.view",
        "View RPA tasks and runs",
        "tasks.view",
        "View tenant and data-scope filtered RPA task and run metadata.",
    ),
    (
        "rpa.tasks.manage",
        "Manage RPA manual queue",
        "tasks.manage",
        "Assign manual review and authorize mock-only retries without executing platform actions.",
    ),
    (
        "rpa.devices.view",
        "View RPA devices",
        "devices.view",
        "View masked tenant and data-scope filtered RPA device metadata.",
    ),
    (
        "rpa.devices.dry_run",
        "Run RPA device dry-run checks",
        "devices.dry_run",
        "Run audited local checks that never connect to a real platform or execute browser automation.",
    ),
    (
        "rpa.stability.view",
        "View RPA stability evidence",
        "stability.view",
        "View account locks, masked page signatures, and task/run state summaries.",
    ),
)


def seed_permissions(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    for code, name, action, description in PERMISSIONS:
        Permission.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "module": "rpa",
                "action": action,
                "description": description,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0009_seed_ui_p2_permissions")]
    operations = [migrations.RunPython(seed_permissions, migrations.RunPython.noop)]
