from django.db import migrations


CODE = "menu.sales_management.sales_management_realtime_board.view"


def register(apps, schema_editor):
    # Register discoverability only; retain all existing role grants and scopes.
    apps.get_model("permissions", "Permission").objects.update_or_create(
        code=CODE,
        defaults={
            "name": "实时数据大屏", "module": "sales_management",
            "action": "sales_management_realtime_board.view",
            "description": "显示实时数据大屏入口", "permission_type": "menu",
            "metadata": {
                "path": "/sales-management/realtime-board", "route": "/sales-management/realtime-board",
                "resource": "sales_management_realtime_board", "parent": "销售管理",
                "action_codes": ["sales_management.view"], "source": "frontend/src/router/menu.js",
                "status": "active",
            },
        },
    )


class Migration(migrations.Migration):
    dependencies = [("permissions", "0052_history_task_recovery_description")]
    operations = [migrations.RunPython(register, migrations.RunPython.noop)]
