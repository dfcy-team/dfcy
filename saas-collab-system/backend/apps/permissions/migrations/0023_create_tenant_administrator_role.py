from django.db import migrations


ROLE_CODE = "administrator"


def create_tenant_administrator_roles(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Role = apps.get_model("permissions", "Role")
    DataScope = apps.get_model("permissions", "DataScope")
    Tenant = apps.get_model("tenants", "Tenant")

    permissions = list(Permission.objects.all())
    for tenant in Tenant.objects.all().iterator():
        role, _ = Role.objects.update_or_create(
            tenant=tenant,
            code=ROLE_CODE,
            defaults={"name": "管理员", "status": "active"},
        )
        role.permissions.set(permissions)
        DataScope.objects.filter(tenant=tenant, role=role).exclude(scope_type="all").delete()
        DataScope.objects.update_or_create(
            tenant=tenant,
            role=role,
            scope_type="all",
            defaults={"config": {}},
        )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0022_create_influencer_manager_role")]
    operations = [migrations.RunPython(create_tenant_administrator_roles, migrations.RunPython.noop)]
