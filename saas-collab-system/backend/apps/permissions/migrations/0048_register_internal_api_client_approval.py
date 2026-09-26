from django.db import migrations


def register(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Role = apps.get_model("permissions", "Role")
    DataScope = apps.get_model("permissions", "DataScope")
    permission, _ = Permission.objects.update_or_create(
        code="integrations.internal_api_client.approve",
        defaults={
            "name": "审核内部 API 调用方",
            "module": "integrations",
            "action": "internal_api_client.approve",
            "description": "审核当前租户的只读 API 调用方配置。",
        },
    )
    for role in Role.objects.filter(code="administrator", status="active"):
        role.permissions.add(permission)
        DataScope.objects.update_or_create(
            tenant=role.tenant, role=role, scope_type="all", defaults={"config": {}},
        )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0047_register_product_cost_permissions")]
    operations = [migrations.RunPython(register, migrations.RunPython.noop)]
