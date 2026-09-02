from django.db import migrations


PERMISSIONS = (
    ("development.product_archive.view", "查看开发产品档案", "product_archive.view"),
    ("development.product_archive.manage", "维护开发产品档案", "product_archive.manage"),
    ("development.product_archive.confirm", "确认并转正开发产品档案", "product_archive.confirm"),
)


def seed(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Role = apps.get_model("permissions", "Role")
    permissions = []
    for code, name, action in PERMISSIONS:
        permission, _ = Permission.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "module": "development",
                "action": action,
                "description": "开发产品虚拟测品档案的生命周期权限。",
            },
        )
        permissions.append(permission)
    for role in Role.objects.filter(code="product_developer", status="active"):
        role.permissions.add(*permissions)


class Migration(migrations.Migration):
    dependencies = [("permissions", "0027_sync_tenant_administrator_permissions")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
