from django.db import migrations


def create_influencer_manager_role(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Role = apps.get_model("permissions", "Role")
    DataScope = apps.get_model("permissions", "DataScope")
    Tenant = apps.get_model("tenants", "Tenant")

    permissions = list(Permission.objects.filter(code__in=("influencers.view", "influencers.manage")))
    for role in Role.objects.filter(code="001"):
        role.permissions.remove(*permissions)

    for tenant in Tenant.objects.all().iterator():
        role, _ = Role.objects.update_or_create(
            tenant=tenant,
            code="002",
            defaults={"name": "达人管理", "status": "active"},
        )
        role.permissions.set(permissions)
        DataScope.objects.update_or_create(
            tenant=tenant,
            role=role,
            scope_type="all",
            defaults={"config": {}},
        )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0021_seed_influencer_permissions")]
    operations = [migrations.RunPython(create_influencer_manager_role, migrations.RunPython.noop)]
