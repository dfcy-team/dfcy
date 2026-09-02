from django.db import migrations


PERMISSION_DEFINITIONS = (
    (
        "pilot.performance.execute",
        "Execute pilot performance",
        "performance.execute",
        "Execute approved pilot performance runs through the allow-listed runner.",
    ),
    (
        "pilot.recovery.execute",
        "Execute recovery drills",
        "recovery.execute",
        "Execute approved recovery plans through the allow-listed runner.",
    ),
    (
        "pilot.release.execute",
        "Execute pilot releases",
        "release.execute",
        "Deploy approved pilot releases through the allow-listed runner.",
    ),
    (
        "pilot.release.rollback.execute",
        "Execute pilot rollbacks",
        "release.rollback.execute",
        "Roll back approved pilot releases through the allow-listed runner.",
    ),
)


def seed_pilot_execution_permissions(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Role = apps.get_model("permissions", "Role")
    permissions = []
    for code, name, action, description in PERMISSION_DEFINITIONS:
        permission, _ = Permission.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "module": "pilot",
                "action": action,
                "description": description,
            },
        )
        permissions.append(permission)

    # The built-in administrator is catalog-managed and must not silently lose
    # access when a new execution capability is installed. Other roles retain
    # explicit least-privilege assignments.
    for role in Role.objects.filter(code="administrator", status="active"):
        role.permissions.add(*permissions)


def remove_pilot_execution_permissions(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Permission.objects.filter(code__in=[item[0] for item in PERMISSION_DEFINITIONS]).delete()


class Migration(migrations.Migration):
    dependencies = [("permissions", "0036_seed_operation_audit_permissions")]

    operations = [
        migrations.RunPython(seed_pilot_execution_permissions, remove_pilot_execution_permissions),
    ]
