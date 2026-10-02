from django.db import migrations


def register(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Role = apps.get_model("permissions", "Role")
    permissions = []
    for code, name, action in [
        ("integrations.history.view", "查看历史补采批次", "history.view"),
        ("integrations.history.manage", "管理历史补采批次", "history.manage"),
    ]:
        permission, _ = Permission.objects.update_or_create(code=code, defaults={
            "name": name, "module": "integrations", "action": action,
            "description": "Shopee 销售订单、退货退款和财务流水历史补采；沿用店铺数据范围。",
        })
        permissions.append(permission)
    # Do not broaden existing data scope, nor grant live execution to new roles.
    for role in Role.objects.filter(code="administrator", status="active"):
        role.permissions.add(*permissions)


class Migration(migrations.Migration):
    dependencies = [("permissions", "0049_authorization_bindings_resource_policies")]
    operations = [migrations.RunPython(register, migrations.RunPython.noop)]
