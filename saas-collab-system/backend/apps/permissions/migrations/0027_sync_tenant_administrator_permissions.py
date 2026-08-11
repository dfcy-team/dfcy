from django.db import migrations


ROLE_CODE = "administrator"


def sync_tenant_administrator_permissions(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Role = apps.get_model("permissions", "Role")

    permissions = list(Permission.objects.all())
    for role in Role.objects.filter(code=ROLE_CODE):
        role.permissions.set(permissions)


class Migration(migrations.Migration):
    dependencies = [("permissions", "0026_align_product_listing_permissions")]

    operations = [
        migrations.RunPython(sync_tenant_administrator_permissions, migrations.RunPython.noop),
    ]
