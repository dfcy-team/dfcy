from django.db import migrations


def register(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    Role = apps.get_model("permissions", "Role")
    permissions = []
    for code, name, action, description in [
        ("integrations.history.view", "查看历史补采批次", "history.view", "查看当前租户和店铺数据范围内的历史补采进度。"),
        ("integrations.history.manage", "管理历史补采批次", "history.manage", "创建、暂停、继续和重试历史补采；须同时具备真实只读同步权限。"),
    ]:
        permission, _ = Permission.objects.update_or_create(code=code, defaults={
            "name": name, "module": "integrations", "action": action,
            "description": description, "permission_type": "action", "metadata": {},
        })
        permissions.append(permission)
    # Do not broaden existing data scope, nor grant live execution to new roles.
    for role in Role.objects.filter(code="administrator", status="active"):
        role.permissions.add(*permissions)


class Migration(migrations.Migration):
    dependencies = [("permissions", "0049_authorization_bindings_resource_policies")]
    operations = [migrations.RunPython(register, migrations.RunPython.noop)]
