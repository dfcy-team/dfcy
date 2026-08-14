from django.db import migrations


PERMISSION_CODE = "sales_management.sync.rerun"
DESCRIPTION_UPDATES = {
    "sales_management.export": "Request and download audited masked sales exports within the active scope.",
    "sales_management.sync.view": "View tenant and data-scope filtered safe sync references.",
}
PREVIOUS_DESCRIPTIONS = {
    "sales_management.export": "Request audited masked sales exports within the active scope.",
    "sales_management.sync.view": "View safe sync references and request audited idempotent reruns.",
}


def seed_permission(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Role = apps.get_model("permissions", "Role")
    permission, _ = Permission.objects.update_or_create(
        code=PERMISSION_CODE,
        defaults={
            "name": "Request sales sync rerun",
            "module": "sales_management",
            "action": "sync.rerun",
            "description": "Request an audited idempotent rerun within the active data scope.",
        },
    )
    for role in Role.objects.filter(code="administrator"):
        role.permissions.add(permission)
    for code, description in DESCRIPTION_UPDATES.items():
        Permission.objects.filter(code=code).update(description=description)


def remove_permission(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Permission.objects.filter(code=PERMISSION_CODE).delete()
    for code, description in PREVIOUS_DESCRIPTIONS.items():
        Permission.objects.filter(code=code).update(description=description)


class Migration(migrations.Migration):
    dependencies = [("permissions", "0028_seed_sales_management_permissions")]
    operations = [migrations.RunPython(seed_permission, remove_permission)]
