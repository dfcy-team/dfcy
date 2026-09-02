from django.db import migrations


PERMISSIONS = (
    ("development.product_archive.view", "View development product archives", "view"),
    ("development.product_archive.manage", "Manage virtual development product archives", "manage"),
    ("development.product_archive.confirm", "Confirm and formalize development product archives", "confirm"),
)


def seed(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Role = apps.get_model("permissions", "Role")
    for code, name, action in PERMISSIONS:
        permission, _ = Permission.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "module": "development",
                "action": action,
                "description": "Lifecycle control for virtual development product archives.",
            },
        )
        # The existing product developer role owns the development workspace;
        # grant the new capability without creating a new menu or role.
        for role in Role.objects.filter(code="product_developer", status="active"):
            role.permissions.add(permission)


class Migration(migrations.Migration):
    dependencies = [("permissions", "0028_seed_platform_product_detail_permissions")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
