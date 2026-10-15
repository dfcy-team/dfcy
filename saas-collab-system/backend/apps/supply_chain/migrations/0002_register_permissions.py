from django.db import migrations


def register(apps, schema_editor):
    Permission = apps.get_model("permissions", "Permission")
    for code, name, action, description in (
        ("supply.v2.view", "查看新版供应链", "v2.view", "查看当前租户及授权数据范围内的新版供应链单据。"),
        ("supply.v2.manage", "维护新版供应链", "v2.manage", "操作新版供应链单据；不授予生产发布或外部群发送权限。"),
    ):
        Permission.objects.using(schema_editor.connection.alias).get_or_create(code=code, defaults={
            "name": name, "module": "supply", "action": action, "description": description,
            "permission_type": "action", "metadata": {},
        })
    # Preserve existing role grants; do not provision or auto-grant any role.
    # Reverse also preserves catalog/grant history rather than deleting records.


class Migration(migrations.Migration):
    dependencies = [
        ("supply_chain", "0001_initial"),
        ("permissions", "0051_history_range_permission_description"),
    ]
    operations = [migrations.RunPython(register, migrations.RunPython.noop)]
